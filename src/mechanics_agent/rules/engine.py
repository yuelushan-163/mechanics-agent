from __future__ import annotations

import math
from numbers import Real
from typing import Any

from mechanics_agent.models import (
    CaseSpec,
    CheckStatus,
    OverallStatus,
    RuleEvaluator,
    RuleResult,
    RuleSeverity,
    VerificationRule,
    VerificationStage,
    VerificationSummary,
)


MISSING = object()


class VerificationEngine:
    def evaluate(
        self,
        case: CaseSpec,
        stage: VerificationStage,
        evidence: dict[str, Any],
        rules: list[tuple[str, VerificationRule]],
    ) -> VerificationSummary:
        payload = {"case": case.model_dump(mode="python"), "evidence": evidence}
        results = [
            self._evaluate_rule(source_doc_id, rule, payload)
            for source_doc_id, rule in rules
            if rule.enabled
            and rule.stage == stage
            and ("*" in rule.analysis_types or case.analysis_type in rule.analysis_types)
        ]
        overall = OverallStatus.PASS
        if any(result.status == CheckStatus.BLOCK for result in results):
            overall = OverallStatus.BLOCK
        elif any(result.status == CheckStatus.WARN for result in results):
            overall = OverallStatus.WARN
        return VerificationSummary(
            case_id=case.case_id,
            stage=stage,
            overall=overall,
            results=results,
        )

    def _evaluate_rule(
        self,
        source_doc_id: str,
        rule: VerificationRule,
        payload: dict[str, Any],
    ) -> RuleResult:
        skip_paths = rule.config.get("skip_if_missing", [])
        if not isinstance(skip_paths, list):
            skip_paths = []
        missing_optional = [
            path
            for path in skip_paths
            if isinstance(path, str)
            and (_get_path(payload, path) is MISSING or _get_path(payload, path) is None)
        ]
        if missing_optional:
            return RuleResult(
                rule_id=rule.rule_id,
                name=rule.name,
                status=CheckStatus.NOT_APPLICABLE,
                message=f"本案例未设置可选判据：{', '.join(missing_optional)}",
                observed={"missing_optional_paths": missing_optional},
                source_doc_id=source_doc_id,
            )
        try:
            passed, message, observed = self._dispatch(rule, payload)
        except (TypeError, ValueError) as exc:
            passed = False
            message = f"规则输入无效：{exc}"
            observed = {"error": str(exc)}
        status = CheckStatus.PASS if passed else self._failure_status(rule.severity)
        return RuleResult(
            rule_id=rule.rule_id,
            name=rule.name,
            status=status,
            message=message,
            observed=observed,
            source_doc_id=source_doc_id,
        )

    def _dispatch(
        self, rule: VerificationRule, payload: dict[str, Any]
    ) -> tuple[bool, str, dict[str, Any]]:
        evaluators = {
            RuleEvaluator.REQUIRED_FIELD: self._required_field,
            RuleEvaluator.VECTOR_BALANCE: self._vector_balance,
            RuleEvaluator.RELATIVE_CHANGE: self._relative_change,
            RuleEvaluator.UPPER_BOUND: self._upper_bound,
            RuleEvaluator.RATIO_MIN: self._ratio_min,
            RuleEvaluator.EQUALS: self._equals,
            RuleEvaluator.EMPTY_COLLECTION: self._empty_collection,
            RuleEvaluator.FINITE_NUMBER: self._finite_number,
        }
        return evaluators[rule.evaluator](rule.config, payload)

    def _required_field(
        self, config: dict[str, Any], payload: dict[str, Any]
    ) -> tuple[bool, str, dict[str, Any]]:
        path = _required_config(config, "path")
        value = _get_path(payload, path)
        min_items = int(config.get("min_items", 0))
        present = value is not MISSING and value is not None and value != ""
        if present and min_items:
            present = hasattr(value, "__len__") and len(value) >= min_items
        message = (
            f"{path} 已提供"
            if present
            else f"缺少必填输入 {path}"
        )
        return present, message, {"path": path, "present": present, "min_items": min_items}

    def _vector_balance(
        self, config: dict[str, Any], payload: dict[str, Any]
    ) -> tuple[bool, str, dict[str, Any]]:
        external = _number_vector(_value_from(config, payload, "external_path"))
        reaction = _number_vector(_value_from(config, payload, "reaction_path"))
        if len(external) != len(reaction):
            raise ValueError("外载荷与反力向量维数不一致")
        residual = [left + right for left, right in zip(external, reaction, strict=True)]
        denominator = max(_norm(external), float(config.get("epsilon", 1e-12)))
        ratio = _norm(residual) / denominator
        threshold = _resolve_number(config, payload, "threshold", "threshold_path")
        passed = ratio <= threshold
        return (
            passed,
            f"载荷—反力不平衡率 {ratio:.6g}，限值 {threshold:.6g}",
            {
                "external": external,
                "reaction": reaction,
                "residual": residual,
                "ratio": ratio,
                "threshold": threshold,
            },
        )

    def _relative_change(
        self, config: dict[str, Any], payload: dict[str, Any]
    ) -> tuple[bool, str, dict[str, Any]]:
        coarse = _number(_value_from(config, payload, "coarse_path"))
        fine = _number(_value_from(config, payload, "fine_path"))
        denominator = max(abs(fine), float(config.get("epsilon", 1e-12)))
        ratio = abs(fine - coarse) / denominator
        threshold = _resolve_number(config, payload, "threshold", "threshold_path")
        passed = ratio <= threshold
        return (
            passed,
            f"两级结果相对变化 {ratio:.6g}，限值 {threshold:.6g}",
            {"coarse": coarse, "fine": fine, "ratio": ratio, "threshold": threshold},
        )

    def _upper_bound(
        self, config: dict[str, Any], payload: dict[str, Any]
    ) -> tuple[bool, str, dict[str, Any]]:
        value = _number(_value_from(config, payload, "value_path"))
        limit = _resolve_number(config, payload, "limit", "limit_path")
        passed = value <= limit
        return (
            passed,
            f"实测值 {value:.6g}，上限 {limit:.6g}",
            {"value": value, "limit": limit},
        )

    def _ratio_min(
        self, config: dict[str, Any], payload: dict[str, Any]
    ) -> tuple[bool, str, dict[str, Any]]:
        numerator = _number(_value_from(config, payload, "numerator_path"))
        denominator = _number(_value_from(config, payload, "denominator_path"))
        if abs(denominator) <= float(config.get("epsilon", 1e-12)):
            raise ValueError("比值分母为零")
        ratio = numerator / denominator
        minimum = _resolve_number(config, payload, "minimum", "minimum_path")
        passed = ratio >= minimum
        return (
            passed,
            f"计算比值 {ratio:.6g}，最低要求 {minimum:.6g}",
            {
                "numerator": numerator,
                "denominator": denominator,
                "ratio": ratio,
                "minimum": minimum,
            },
        )

    def _equals(
        self, config: dict[str, Any], payload: dict[str, Any]
    ) -> tuple[bool, str, dict[str, Any]]:
        value = _value_from(config, payload, "value_path")
        expected = config.get("expected", MISSING)
        if expected is MISSING and "expected_path" in config:
            expected = _value_from(config, payload, "expected_path")
        if expected is MISSING:
            raise ValueError("规则缺少 expected 或 expected_path")
        case_sensitive = bool(config.get("case_sensitive", True))
        compared_value, compared_expected = value, expected
        if not case_sensitive and isinstance(value, str) and isinstance(expected, str):
            compared_value, compared_expected = value.casefold(), expected.casefold()
        passed = compared_value == compared_expected
        return (
            passed,
            f"实测值 {value!r}，期望值 {expected!r}",
            {"value": value, "expected": expected},
        )

    def _empty_collection(
        self, config: dict[str, Any], payload: dict[str, Any]
    ) -> tuple[bool, str, dict[str, Any]]:
        path = _required_config(config, "path")
        value = _get_path(payload, path)
        if value is MISSING or value is None:
            value = []
        if not hasattr(value, "__len__") or isinstance(value, (str, bytes)):
            raise TypeError(f"{path} 不是集合")
        passed = len(value) == 0
        return passed, f"{path} 项数为 {len(value)}", {"path": path, "count": len(value)}

    def _finite_number(
        self, config: dict[str, Any], payload: dict[str, Any]
    ) -> tuple[bool, str, dict[str, Any]]:
        path = _required_config(config, "path")
        value = _number(_get_path(payload, path))
        passed = math.isfinite(value)
        return passed, f"{path}={value!r}", {"path": path, "value": value}

    @staticmethod
    def _failure_status(severity: RuleSeverity) -> CheckStatus:
        return CheckStatus.BLOCK if severity == RuleSeverity.BLOCK else CheckStatus.WARN


def _get_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return MISSING
    return current


def _value_from(config: dict[str, Any], payload: dict[str, Any], key: str) -> Any:
    path = _required_config(config, key)
    value = _get_path(payload, path)
    if value is MISSING or value is None:
        raise ValueError(f"缺少规则输入 {path}")
    return value


def _resolve_number(
    config: dict[str, Any],
    payload: dict[str, Any],
    literal_key: str,
    path_key: str,
) -> float:
    if path_key in config:
        return _number(_value_from(config, payload, path_key))
    if literal_key in config:
        return _number(config[literal_key])
    raise ValueError(f"规则缺少 {literal_key} 或 {path_key}")


def _required_config(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"规则配置缺少字符串字段 {key}")
    return value


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"期望数值，实际为 {value!r}")
    return float(value)


def _number_vector(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)) or not value:
        raise TypeError("期望非空数值向量")
    return [_number(item) for item in value]


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))
