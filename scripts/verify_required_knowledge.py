from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalCase:
    case_id: str
    query: str
    expected_any: tuple[str, ...]
    must_contain: tuple[str, ...] = ()


CASES = (
    RetrievalCase("load_value", "载荷大小、数值和单位必须明确，能否根据承重用途猜载荷", ("MATRIX-K001",), ("不得", "推测")),
    RetrievalCase("load_direction", "载荷方向、坐标系、正负号和随动方向", ("MATRIX-K002",), ("坐标系",)),
    RetrievalCase("load_region", "载荷作用区域、作用面积和分布方式", ("MATRIX-K003",), ("载荷传递路径",)),
    RetrievalCase("load_time", "载荷随时间变化，静态、周期、冲击和幅值曲线", ("MATRIX-K004",), ("Amplitude",)),
    RetrievalCase("support_type", "固支、铰支、滚动支承还是弹性支承", ("MATRIX-K005",), ("自由度",)),
    RetrievalCase("gravity_inertia_temperature", "重力、惯性、转速、温度是否参与", ("MATRIX-K006",), ("重力", "热应力")),
    RetrievalCase("load_combinations", "多个载荷工况是否组合，非线性工况能否线性叠加", ("MATRIX-K007",), ("线性叠加",)),
    RetrievalCase("rigid_body_overconstraint", "约束是否造成过约束或刚体运动", ("MATRIX-K008",), ("刚体运动", "过约束")),
    RetrievalCase("beam_idealization", "细长构件什么时候使用梁单元", ("MATRIX-K009",), ("局部三维应力",)),
    RetrievalCase("shell_idealization", "薄壁结构什么时候使用壳单元", ("MATRIX-K010",), ("厚度方向应力",)),
    RetrievalCase("solid_idealization", "局部三维应力、复杂接触和塑性区域使用实体单元", ("MATRIX-K011",), ("实体",)),
    RetrievalCase("defeaturing", "哪些圆角、小孔和螺纹可以删除", ("MATRIX-K012",), ("删除", "可回溯")),
    RetrievalCase("protected_features", "哪些孔、接触面、载荷面绝不能删除", ("MATRIX-K013",), ("保护集合",)),
    RetrievalCase("submodel", "什么时候使用全局模型加局部子模型", ("MATRIX-K014",), ("子模型",)),
    RetrievalCase("unit_system", "Abaqus没有内置单位体系，mm N MPa如何保持一致", ("MATRIX-K017",), ("一致体系",)),
    RetrievalCase("elastic_properties", "材料弹性模量、泊松比、密度必须保存", ("MATRIX-K018", "MATRIX-K021"), ("弹性模量",)),
    RetrievalCase("strength_properties", "材料屈服强度、抗拉强度、牌号和热处理状态", ("MATRIX-K019",), ("牌号", "热处理")),
    RetrievalCase("plastic_curve", "塑性应力应变曲线，真应力和塑性应变转换", ("MATRIX-K020",), ("真应力", "塑性应变")),
    RetrievalCase("temperature_material", "材料温度依赖、参考温度和热膨胀系数", ("MATRIX-K022",), ("温度",)),
    RetrievalCase("material_traceability", "材料数据来源、版本、审核状态和生效日期", ("MATRIX-K024",), ("可追溯",)),
    RetrievalCase("element_order", "一阶与二阶单元有什么差异，网格不是越细越好", ("MATRIX-K026", "MATRIX-K031"), ("单元",)),
    RetrievalCase("shear_locking", "剪切锁死如何识别和处理", ("MATRIX-K028",), ("剪切锁死",)),
    RetrievalCase("volumetric_locking", "体积锁死和近不可压缩材料", ("MATRIX-K029",), ("体积锁死",)),
    RetrievalCase("hourglass", "小时玻璃和低阶减缩积分零能模式", ("MATRIX-K030",), ("小时玻璃",)),
    RetrievalCase("stress_singularity", "孔边、尖角、约束点的应力奇异，单节点最大应力能否作为结论", ("MATRIX-K033",), ("单节点", "设计结论")),
    RetrievalCase("mesh_convergence", "对位移、应变能和工程关注区域应力做网格收敛", ("MATRIX-K035",), ("收敛",)),
    RetrievalCase("geometric_nonlinearity", "几何非线性、大位移、大转动和屈曲后", ("MATRIX-K036",), ("几何非线性",)),
    RetrievalCase("material_nonlinearity", "材料非线性、塑性、超弹和损伤", ("MATRIX-K037",), ("材料非线性",)),
    RetrievalCase("contact_nonlinearity", "接触非线性、开闭、摩擦和有限滑移", ("MATRIX-K038",), ("接触",)),
    RetrievalCase("physical_instability", "真实结构失稳与数值失稳如何区分", ("MATRIX-K039",), ("真实物理现象",)),
    RetrievalCase("convergence_diagnosis", "不收敛属于数值问题、材料积分还是接触状态", ("MATRIX-K041",), ("收敛",)),
)


def search(base_url: str, query: str, top_k: int) -> list[dict[str, object]]:
    body = json.dumps({"query": query, "top_k": top_k}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/knowledge/search",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify mandatory mechanics knowledge retrieval")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    results: list[dict[str, object]] = []
    failures = 0
    for case in CASES:
        try:
            hits = search(args.base_url, case.query, args.top_k)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            failures += 1
            results.append({"case_id": case.case_id, "passed": False, "error": str(exc)})
            continue

        hit_by_id = {
            str(hit.get("document", {}).get("doc_id")): hit.get("document", {})
            for hit in hits
        }
        matched_id = next((item for item in case.expected_any if item in hit_by_id), None)
        combined = ""
        if matched_id:
            document = hit_by_id[matched_id]
            combined = f"{document.get('title', '')}\n{document.get('content', '')}"
        missing_terms = [term for term in case.must_contain if term not in combined]
        passed = matched_id is not None and not missing_terms
        failures += int(not passed)
        results.append(
            {
                "case_id": case.case_id,
                "passed": passed,
                "matched_id": matched_id,
                "missing_terms": missing_terms,
                "top_ids": list(hit_by_id)[: args.top_k],
            }
        )

    report = {
        "total": len(CASES),
        "passed": len(CASES) - failures,
        "failed": failures,
        "results": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
