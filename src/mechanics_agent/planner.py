from __future__ import annotations

import json
import re
from typing import Protocol

import httpx

from mechanics_agent.config import Settings
from mechanics_agent.models import (
    AnalysisPlan,
    CaseSpec,
    ModelUsageStatus,
    SearchHit,
    VerificationRule,
)
from mechanics_agent.usage import ModelUsageTracker


class PlannerError(RuntimeError):
    pass


_PLAN_LIST_FIELDS = (
    "assumptions",
    "missing_inputs",
    "cad_actions",
    "fea_actions",
    "applicable_rule_ids",
    "risk_flags",
    "approval_required",
)

_APPROVAL_TRUE_VALUES = {"是", "需要", "required", "true", "yes"}
_APPROVAL_FALSE_VALUES = {"否", "无", "不需要", "not required", "false", "no"}


def _normalize_approval_text(value: str) -> str | None:
    text = value.strip()
    lowered = text.lower()
    if lowered in _APPROVAL_FALSE_VALUES:
        return None
    if lowered in _APPROVAL_TRUE_VALUES:
        return "模型标记该计划需要工程师审核"
    return text or None


def _normalize_plan_payload(payload: object) -> dict[str, object]:
    """Repair common JSON-shape mistakes without inventing engineering content."""
    if not isinstance(payload, dict):
        raise TypeError("analysis plan must be a JSON object")

    normalized = dict(payload)
    for field_name in _PLAN_LIST_FIELDS:
        value = normalized.get(field_name, [])
        if value is None:
            normalized[field_name] = []
        elif isinstance(value, str):
            if field_name == "approval_required":
                approval_text = _normalize_approval_text(value)
                normalized[field_name] = [approval_text] if approval_text else []
            else:
                text = value.strip()
                normalized[field_name] = [text] if text else []
        elif isinstance(value, list):
            if field_name == "approval_required":
                normalized[field_name] = [
                    approval_text
                    for item in value
                    if isinstance(item, str)
                    and (approval_text := _normalize_approval_text(item))
                ]
            else:
                normalized[field_name] = value
        else:
            raise TypeError(f"{field_name} must be a string array")
    return normalized


class Planner(Protocol):
    @property
    def name(self) -> str: ...

    async def plan(
        self,
        case: CaseSpec,
        knowledge_hits: list[SearchHit],
        rules: list[tuple[str, VerificationRule]],
    ) -> AnalysisPlan: ...

    async def test_connection(self) -> dict[str, object]: ...

    async def close(self) -> None: ...


class LocalPlanner:
    @property
    def name(self) -> str:
        return "local-deterministic"

    async def plan(
        self,
        case: CaseSpec,
        knowledge_hits: list[SearchHit],
        rules: list[tuple[str, VerificationRule]],
    ) -> AnalysisPlan:
        missing_inputs: list[str] = []
        if case.unit_system is None:
            missing_inputs.append("单位体系")
        if case.material is None:
            missing_inputs.append("材料牌号与状态")
        if not case.loads:
            missing_inputs.append("载荷")
        if not case.boundary_conditions:
            missing_inputs.append("边界条件")
        if case.geometry is None:
            missing_inputs.append("几何输入方式与关键尺寸")
        if case.material and not case.material.source_id:
            missing_inputs.append("材料数据来源")

        assumptions = [
            "本地回退规划器不补猜缺失的力学输入",
            f"当前分析类型为 {case.analysis_type}",
        ]
        if case.geometry_type:
            assumptions.append(f"用户声明的几何类型为 {case.geometry_type}")

        cad_actions = [
            "读取或创建参数化CAD模型",
            "建立承载面、约束面、接触面和优化尺寸的稳定语义标记",
            "生成仿真专用几何并保留原始模型",
        ]
        fea_actions = [
            "根据理想化规则选择梁、壳或实体模型",
            "建立材料、分析步、载荷、约束和输出请求",
            "执行数据检查后再提交基准作业",
            "从ODB提取验算证据并运行确定性规则",
        ]
        risk_flags = []
        if missing_inputs:
            risk_flags.append("存在关键输入缺失，禁止自动提交正式求解")
        if not knowledge_hits:
            risk_flags.append("知识库未检索到相关已审核条目")

        return AnalysisPlan(
            case_id=case.case_id,
            summary=f"为“{case.title}”生成 {case.analysis_type} 分析计划",
            assumptions=assumptions,
            missing_inputs=missing_inputs,
            cad_actions=cad_actions,
            fea_actions=fea_actions,
            applicable_rule_ids=[rule.rule_id for _, rule in rules],
            risk_flags=risk_flags,
            approval_required=list(
                dict.fromkeys(
                    [
                        "确认载荷作用区域与方向",
                        "确认边界条件不会造成过约束或刚体运动",
                        *case.required_confirmations,
                        "正式设计结论由工程师审核",
                    ]
                )
            ),
        )

    async def close(self) -> None:
        return None

    async def test_connection(self) -> dict[str, object]:
        return {
            "status": "ok",
            "planner": self.name,
            "response": {"message": "本地确定性规划器无需外部连接"},
        }


class OpenAICompatiblePlanner:
    def __init__(
        self,
        *,
        provider_id: str,
        provider_label: str,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens: int,
        temperature: float,
        request_timeout_seconds: float,
        extra_request_fields: dict[str, object] | None = None,
        usage_tracker: ModelUsageTracker | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.provider_label = provider_label
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra_request_fields = extra_request_fields or {}
        self.usage_tracker = usage_tracker
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=request_timeout_seconds,
            transport=transport,
        )

    @property
    def name(self) -> str:
        return f"{self.provider_id}:{self.model}"

    async def plan(
        self,
        case: CaseSpec,
        knowledge_hits: list[SearchHit],
        rules: list[tuple[str, VerificationRule]],
    ) -> AnalysisPlan:
        allowed_rule_ids = {rule.rule_id for _, rule in rules}
        context = {
            "case": case.model_dump(mode="json"),
            "knowledge": [
                {
                    "doc_id": hit.document.doc_id,
                    "title": hit.document.title,
                    "content": hit.document.content,
                    "sources": [
                        source.model_dump(mode="json") for source in hit.document.sources
                    ],
                }
                for hit in knowledge_hits
            ],
            "verification_rules": [
                {
                    "doc_id": doc_id,
                    "rule_id": rule.rule_id,
                    "name": rule.name,
                    "description": rule.description,
                    "stage": rule.stage.value,
                    "severity": rule.severity.value,
                }
                for doc_id, rule in rules
            ],
        }
        system_prompt = (
            "你是有限元分析规划助手。只根据输入案例和已审核知识生成计划；"
            "不得补猜载荷、约束、材料或单位；不得宣布仿真合格。"
            "输出必须是一个JSON对象，字段严格为：case_id, summary, assumptions, "
            "missing_inputs, cad_actions, fea_actions, applicable_rule_ids, risk_flags, "
            "approval_required。所有列表字段都必须是字符串数组，"
            "即使只有一项或没有内容，也必须分别写成[\"内容\"]或[]；"
            "approval_required禁止输出‘是’或‘否’。"
        )
        request_body: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": "请生成可审计的CAD/CAE分析计划：\n"
                    + json.dumps(context, ensure_ascii=False),
                },
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            **self.extra_request_fields,
        }

        response = await self._post_completion(request_body, operation="plan")
        try:
            content = response.json()["choices"][0]["message"]["content"]
            parsed = _normalize_plan_payload(
                json.loads(_strip_json_fence(content))
            )
            plan = AnalysisPlan.model_validate(parsed)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as exc:
            raise PlannerError(
                f"{self.provider_label} returned an invalid analysis plan"
            ) from exc

        plan.case_id = case.case_id
        plan.applicable_rule_ids = sorted(
            rule_id for rule_id in set(plan.applicable_rule_ids) if rule_id in allowed_rule_ids
        )
        # Verification is independent of the LLM, so every applicable rule remains visible.
        plan.applicable_rule_ids = sorted(allowed_rule_ids)
        plan.approval_required = list(
            dict.fromkeys(
                [
                    *plan.approval_required,
                    *case.required_confirmations,
                    "正式设计结论由工程师审核",
                ]
            )
        )
        return plan

    async def test_connection(self) -> dict[str, object]:
        request_body: dict[str, object] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是接口测试助手，只输出JSON对象。",
                },
                {
                    "role": "user",
                    "content": (
                        '返回 {"status":"ok","message":"规划模型连接成功"}，'
                        "不要输出其他内容。"
                    ),
                },
            ],
            "temperature": 0.0,
            "max_tokens": min(self.max_tokens, 256),
            "response_format": {"type": "json_object"},
            **self.extra_request_fields,
        }
        response = await self._post_completion(
            request_body,
            operation="connection_test",
        )
        try:
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(_strip_json_fence(content))
            if not isinstance(parsed, dict):
                raise TypeError("response is not a JSON object")
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise PlannerError(
                f"{self.provider_label} returned an invalid connection test response"
            ) from exc
        provider_trace_id = (
            response.headers.get("x-siliconcloud-trace-id")
            or response.headers.get("x-request-id")
        )
        return {
            "status": "ok",
            "planner": self.name,
            "provider_trace_id": provider_trace_id,
            "response": parsed,
        }

    async def close(self) -> None:
        await self.client.aclose()

    async def _post_completion(
        self,
        request_body: dict[str, object],
        *,
        operation: str,
    ) -> httpx.Response:
        started_at = ModelUsageTracker.start_timer()
        try:
            response = await self.client.post("/chat/completions", json=request_body)
        except httpx.HTTPError as exc:
            if self.usage_tracker:
                await self.usage_tracker.record_response(
                    provider=self.provider_id,
                    model=self.model,
                    operation=operation,
                    response_body=None,
                    status=ModelUsageStatus.ERROR,
                    started_at=started_at,
                    error_type=type(exc).__name__,
                )
            raise PlannerError(
                f"{self.provider_label} connection failed: {exc}"
            ) from exc
        provider_trace_id = (
            response.headers.get("x-siliconcloud-trace-id")
            or response.headers.get("x-request-id")
        )
        try:
            response_body: object | None = response.json()
        except ValueError:
            response_body = None
        if response.status_code != 200:
            if self.usage_tracker:
                await self.usage_tracker.record_response(
                    provider=self.provider_id,
                    model=self.model,
                    operation=operation,
                    response_body=response_body,
                    status=ModelUsageStatus.ERROR,
                    started_at=started_at,
                    http_status=response.status_code,
                    provider_request_id=provider_trace_id,
                    error_type=f"HTTP_{response.status_code}",
                )
            trace_suffix = (
                f" provider_trace_id={provider_trace_id}" if provider_trace_id else ""
            )
            raise PlannerError(
                f"{self.provider_label} returned HTTP {response.status_code}: "
                f"{response.text[:500]}{trace_suffix}"
            )
        if self.usage_tracker:
            await self.usage_tracker.record_response(
                provider=self.provider_id,
                model=self.model,
                operation=operation,
                response_body=response_body,
                status=ModelUsageStatus.SUCCESS,
                started_at=started_at,
                http_status=response.status_code,
                provider_request_id=provider_trace_id,
            )
        return response


class KimiPlanner(OpenAICompatiblePlanner):
    def __init__(
        self,
        settings: Settings,
        *,
        usage_tracker: ModelUsageTracker | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not settings.kimi_api_key:
            raise ValueError("MOONSHOT_API_KEY is required for Kimi planner")
        self.settings = settings
        extra_request_fields: dict[str, object] = {}
        if (
            settings.kimi_thinking_enabled
            and "thinking" not in settings.kimi_model.casefold()
        ):
            extra_request_fields["thinking"] = {"type": "enabled"}
        super().__init__(
            provider_id="kimi",
            provider_label="Kimi",
            api_key=settings.kimi_api_key,
            base_url=settings.kimi_base_url,
            model=settings.kimi_model,
            max_tokens=settings.kimi_max_tokens,
            temperature=1.0,
            request_timeout_seconds=settings.request_timeout_seconds,
            extra_request_fields=extra_request_fields,
            usage_tracker=usage_tracker,
            transport=transport,
        )


class SiliconFlowPlanner(OpenAICompatiblePlanner):
    def __init__(
        self,
        settings: Settings,
        *,
        usage_tracker: ModelUsageTracker | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not settings.siliconflow_api_key:
            raise ValueError(
                "SILICONFLOW_API_KEY is required for SiliconFlow planner"
            )
        self.settings = settings
        extra_request_fields: dict[str, object] = {}
        if settings.siliconflow_enable_thinking is not None:
            extra_request_fields["enable_thinking"] = (
                settings.siliconflow_enable_thinking
            )
        super().__init__(
            provider_id="siliconflow",
            provider_label="SiliconFlow",
            api_key=settings.siliconflow_api_key,
            base_url=settings.siliconflow_base_url,
            model=settings.siliconflow_model,
            max_tokens=settings.siliconflow_max_tokens,
            temperature=0.2,
            request_timeout_seconds=settings.request_timeout_seconds,
            extra_request_fields=extra_request_fields,
            usage_tracker=usage_tracker,
            transport=transport,
        )


def build_planner(
    settings: Settings,
    *,
    usage_tracker: ModelUsageTracker | None = None,
) -> Planner:
    if settings.planner_mode == "kimi":
        return KimiPlanner(settings, usage_tracker=usage_tracker)
    if settings.planner_mode == "siliconflow":
        return SiliconFlowPlanner(settings, usage_tracker=usage_tracker)
    if settings.planner_mode == "auto" and settings.kimi_api_key:
        return KimiPlanner(settings, usage_tracker=usage_tracker)
    if settings.planner_mode == "auto" and settings.siliconflow_api_key:
        return SiliconFlowPlanner(settings, usage_tracker=usage_tracker)
    return LocalPlanner()


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else text
