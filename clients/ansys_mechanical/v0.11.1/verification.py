"""Deterministic checks for the supported Mechanical linear-static workflow."""
import math

RULE_VERSION = "ansys252-linear-static-loads-2"


def positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(name + " must be a positive finite number")
    return value


def validate_verification(value):
    if not isinstance(value, dict):
        raise ValueError("verification must be an object")
    allowed = {"mesh_convergence", "max_displacement_mm", "acceptance_source"}
    if set(value) - allowed:
        raise ValueError("Unknown verification fields")
    if "max_displacement_mm" in value:
        positive(value["max_displacement_mm"], "max_displacement_mm")
        if not isinstance(value.get("acceptance_source"), str) or not value["acceptance_source"].strip():
            raise ValueError("位移允许值必须提供验收依据 acceptance_source")
    if "mesh_convergence" in value:
        mesh = value["mesh_convergence"]
        required = {"relative_tolerance", "threshold_source", "refinement_factor", "max_levels", "max_elements"}
        if not isinstance(mesh, dict) or set(mesh) != required:
            raise ValueError("mesh_convergence requires exactly: " + ", ".join(sorted(required)))
        positive(mesh["relative_tolerance"], "relative_tolerance")
        if mesh["relative_tolerance"] >= 1:
            raise ValueError("收敛相对变化阈值必须在 0 与 1 之间")
        if not isinstance(mesh["threshold_source"], str) or not mesh["threshold_source"].strip():
            raise ValueError("必须填写收敛阈值的项目/验证依据")
        positive(mesh["refinement_factor"], "refinement_factor")
        if not 0.4 <= mesh["refinement_factor"] <= 0.9:
            raise ValueError("refinement_factor must be between 0.4 and 0.9")
        for key, lo, hi in (("max_levels", 2, 4), ("max_elements", 1, 2000000)):
            if type(mesh[key]) is not int or not lo <= mesh[key] <= hi:
                raise ValueError("%s must be an integer between %s and %s" % (key, lo, hi))
    return value


def compare_levels(previous, current, tolerance):
    """Same global total-deformation quantity in mm, from independent model copies."""
    a = previous["deformation_max_mm"]
    b = current["deformation_max_mm"]
    for x in (a, b):
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0:
            raise ValueError("Invalid deformation evidence")
    if current["mesh_elements"] <= previous["mesh_elements"]:
        return {"status": "block", "reason": "细化后单元数未增加，不能作为独立网格收敛证据"}
    if b == 0:
        return {"status": "block", "reason": "零位移结果不能用于相对变化收敛判定"}
    change = abs(b - a) / abs(b)
    return {"status": "pass" if change <= tolerance else "block", "relative_change": change,
        "relative_tolerance": tolerance, "quantity": "global_max_total_deformation_mm",
        "reason": "两档网格的位移比较；不代表应力收敛或工程验收"}


def evaluate(result, options, convergence):
    rules = []
    def add(rule_id, status, reason, **evidence):
        rules.append(dict(rule_id=rule_id, status=status, reason=reason, **evidence))
    add("POST-JOB-001", "pass" if result.get("status") == "Done" else "block", "Mechanical 求解状态")
    balance=result.get("reaction_balance",{}).get("passed",False)
    add("POST-FORCE-001", "pass" if balance is True else ("warn" if balance is None else "block"),
        result.get('reaction_balance',{}).get('note') or "整体力平衡",evidence=result.get("reaction_balance"))
    if "moment_balance" in result:
        add("POST-MOMENT-001","pass" if result["moment_balance"]["passed"] else "block","纯力矩工况的反力矩平衡",evidence=result["moment_balance"])
    if result.get("load",{}).get("type")=="remote_force":
        add("POST-REMOTE-MOMENT-001","warn","远程力的附加力矩及参考点须人工复核",evidence=result.get("reaction_moment_Nmm"))
    add("POST-MESH-001", convergence["status"], convergence["reason"], evidence=convergence)
    findings = result.get("preflight_review", {}).get("findings", [])
    add("PRE-MESH-QUALITY-001", "block" if any(f.get("level") == "block" for f in findings) else
        ("warn" if any(f.get("code") in ("mesh_quality_warning", "mesh_quality_unavailable") for f in findings) else "pass"),
        "保留 Mechanical 网格质量检查和人工复核项")
    messages = [m for m in result.get("messages", []) if m.get("severity", "").lower() not in ("info", "information")]
    add("POST-WARN-001", "warn" if messages else "pass", "未分类的求解器警告必须人工复核", evidence=messages)
    add("PRE-MAT-001", "warn", "当前只检查材料已分配；弹性参数、来源和线弹性适用性仍需人工核对")
    if "max_displacement_mm" in options:
        actual = result.get("deformation_max_mm")
        if actual is None:
            add("POST-DISP-001", "block", "已设置位移限值，但结果中没有可用的最大总变形数值",
                limit_mm=options["max_displacement_mm"], source=options["acceptance_source"])
        else:
            add("POST-DISP-001", "pass" if actual <= options["max_displacement_mm"] else "block",
                "全模型最大总变形上限；不用于指定分量或指定区域限值", actual_mm=actual,
                limit_mm=options["max_displacement_mm"], source=options["acceptance_source"])
    else:
        add("POST-DISP-001", "not_applicable", "未设置位移验收限值，不判定刚度合格")
    add("POST-SF-001", "not_applicable", "尚未提供受控材料许用值与应力评价方法，不判定强度合格")
    return {"version": RULE_VERSION, "status": "blocked" if any(r["status"] == "block" for r in rules) else
        ("human_review_required" if any(r["status"] == "warn" for r in rules) else "passed"), "rules": rules}
