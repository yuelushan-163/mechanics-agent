from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import openpyxl


SUPPORTED_DOCUMENT_TYPES = {"knowledge", "material", "benchmark", "solver_error"}


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def document_id(prefix: str, value: Any) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", text(value)).strip("-")
    if not normalized:
        raise ValueError(f"Cannot build document ID from {value!r}")
    return f"{prefix}-{normalized}" if prefix else normalized


def source(workbook: Path, sheet: str, row: int, last_column: str) -> list[dict[str, str]]:
    return [
        {
            "title": workbook.name,
            "locator": f"{sheet}!A{row}:{last_column}{row}",
            "version": "2026-07-30",
            "page_or_section": f"{sheet} 第 {row} 行",
        }
    ]


def join_sections(sections: list[tuple[str, Any]]) -> str:
    return "\n".join(f"{label}：{text(value)}" for label, value in sections if text(value))


def base_document(
    *,
    doc_id: str,
    title: str,
    content: str,
    domain: str,
    tags: list[str],
    sources: list[dict[str, str]],
    metadata: dict[str, Any],
    doc_type: str = "knowledge",
) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "doc_type": doc_type,
        "title": title,
        "content": content,
        "domain": domain,
        "analysis_types": ["*"],
        "tags": [item for item in dict.fromkeys(tags) if item],
        "status": "approved",
        "evidence_level": "internal",
        "sources": sources,
        "metadata": {
            "approval_scope": "retrieval_and_planning_only",
            "requires_engineer_validation": True,
            **metadata,
        },
    }


def knowledge_documents(workbook: Path, sheet: Any) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for row in range(5, sheet.max_row + 1):
        knowledge_id = text(sheet.cell(row, 1).value)
        if not knowledge_id:
            continue
        domain = text(sheet.cell(row, 2).value)
        point = text(sheet.cell(row, 5).value)
        original_type = text(sheet.cell(row, 11).value) or "knowledge"
        stored_type = original_type if original_type in SUPPORTED_DOCUMENT_TYPES else "knowledge"
        severity = text(sheet.cell(row, 10).value)
        priority = text(sheet.cell(row, 14).value)
        content = join_sections(
            [
                ("典型问题或触发场景", sheet.cell(row, 3).value),
                ("必须获取的信息", sheet.cell(row, 4).value),
                ("知识点", point),
                ("知识内容", sheet.cell(row, 6).value),
                ("Agent处理方式", sheet.cell(row, 7).value),
                ("验算与证据", sheet.cell(row, 8).value),
                ("信息缺失后果", sheet.cell(row, 9).value),
                ("严重级别", severity),
                ("适用阶段", sheet.cell(row, 12).value),
                ("来源要求", sheet.cell(row, 13).value),
                ("首版优先级", priority),
            ]
        )
        documents.append(
            base_document(
                doc_id=document_id("MATRIX", knowledge_id),
                doc_type=stored_type,
                title=f"{knowledge_id}｜{point}",
                content=content,
                domain=domain,
                tags=[domain, knowledge_id, point, severity, priority, original_type],
                sources=source(workbook, sheet.title, row, "N"),
                metadata={
                    "source_sheet": sheet.title,
                    "source_row": row,
                    "knowledge_id": knowledge_id,
                    "original_document_type": original_type,
                    "stored_document_type": stored_type,
                    "severity": severity,
                    "priority": priority,
                    "stage": text(sheet.cell(row, 12).value),
                    "source_requirement": text(sheet.cell(row, 13).value),
                    "executable": False,
                },
            )
        )
    return documents


def field_documents(workbook: Path, sheet: Any) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for row in range(5, sheet.max_row + 1):
        field_id = text(sheet.cell(row, 1).value)
        if not field_id:
            continue
        group = text(sheet.cell(row, 2).value)
        field_name = text(sheet.cell(row, 4).value)
        required = text(sheet.cell(row, 6).value)
        content = join_sections(
            [
                ("字段分组", group),
                ("JSON路径", sheet.cell(row, 3).value),
                ("字段名称", field_name),
                ("数据类型或单位", sheet.cell(row, 5).value),
                ("是否必填", required),
                ("适用条件", sheet.cell(row, 7).value),
                ("示例", sheet.cell(row, 8).value),
                ("校验规则", sheet.cell(row, 9).value),
                ("缺失处理", sheet.cell(row, 10).value),
                ("对应知识编号", sheet.cell(row, 11).value),
            ]
        )
        documents.append(
            base_document(
                doc_id=document_id("FIELD", field_id),
                title=f"{field_id}｜输入字段：{field_name}",
                content=content,
                domain="必填输入字段",
                tags=["必填输入字段", field_id, group, field_name, required],
                sources=source(workbook, sheet.title, row, "K"),
                metadata={
                    "source_sheet": sheet.title,
                    "source_row": row,
                    "field_id": field_id,
                    "field_group": group,
                    "json_path": text(sheet.cell(row, 3).value),
                    "required": required,
                    "knowledge_ids": text(sheet.cell(row, 11).value),
                    "executable": False,
                },
            )
        )
    return documents


def rule_spec_documents(workbook: Path, sheet: Any) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for row in range(5, sheet.max_row + 1):
        rule_id = text(sheet.cell(row, 1).value)
        if not rule_id:
            continue
        stage = text(sheet.cell(row, 2).value)
        problem = text(sheet.cell(row, 3).value)
        calculator = text(sheet.cell(row, 6).value)
        content = join_sections(
            [
                ("阶段", stage),
                ("对应问题", problem),
                ("所需输入或证据", sheet.cell(row, 4).value),
                ("知识依据", sheet.cell(row, 5).value),
                ("建议计算器", calculator),
                ("阈值来源", sheet.cell(row, 7).value),
                ("通过条件", sheet.cell(row, 8).value),
                ("失败动作", sheet.cell(row, 9).value),
                ("严重级别", sheet.cell(row, 10).value),
                ("是否允许自动修复", sheet.cell(row, 11).value),
                ("知识编号", sheet.cell(row, 12).value),
            ]
        )
        documents.append(
            base_document(
                doc_id=document_id("RULESPEC", rule_id),
                title=f"{rule_id}｜验算规则：{problem}",
                content=content,
                domain="验算规则",
                tags=["验算规则", rule_id, stage, calculator, text(sheet.cell(row, 10).value)],
                sources=source(workbook, sheet.title, row, "L"),
                metadata={
                    "source_sheet": sheet.title,
                    "source_row": row,
                    "rule_id": rule_id,
                    "stage": stage,
                    "suggested_calculator": calculator,
                    "knowledge_ids": text(sheet.cell(row, 12).value),
                    "original_document_type": "verification_rule",
                    "stored_document_type": "knowledge",
                    "executable": False,
                    "execution_note": "Rule specification is searchable but not executable until its calculator and config are approved and implemented.",
                },
            )
        )
    return documents


def classification_documents(workbook: Path, sheet: Any) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for row in range(5, sheet.max_row + 1):
        category = text(sheet.cell(row, 1).value)
        if not category:
            continue
        content = join_sections(
            [
                ("存储内容", sheet.cell(row, 2).value),
                ("主要结构化字段", sheet.cell(row, 3).value),
                ("检索方式", sheet.cell(row, 4).value),
                ("是否可执行", sheet.cell(row, 5).value),
                ("审核要求", sheet.cell(row, 6).value),
                ("典型示例", sheet.cell(row, 7).value),
                ("更新策略", sheet.cell(row, 8).value),
            ]
        )
        documents.append(
            base_document(
                doc_id=document_id("KBCLASS", category),
                title=f"ES知识库分类：{category}",
                content=content,
                domain="知识库治理",
                tags=["ES", "知识库治理", category],
                sources=source(workbook, sheet.title, row, "H"),
                metadata={
                    "source_sheet": sheet.title,
                    "source_row": row,
                    "category": category,
                    "executable": False,
                },
            )
        )
    return documents


def roadmap_documents(workbook: Path, sheet: Any) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for row in range(5, sheet.max_row + 1):
        stage = text(sheet.cell(row, 1).value)
        if not stage:
            continue
        content = join_sections(
            [
                ("阶段", stage),
                ("范围", sheet.cell(row, 2).value),
                ("包含知识域", sheet.cell(row, 3).value),
                ("明确不包含", sheet.cell(row, 4).value),
                ("完成标准", sheet.cell(row, 5).value),
                ("所需用户资料", sheet.cell(row, 6).value),
                ("建议自动化权限", sheet.cell(row, 7).value),
            ]
        )
        documents.append(
            base_document(
                doc_id=document_id("ROADMAP", stage.split()[0]),
                title=f"实施路线：{stage}",
                content=content,
                domain="实施路线与能力边界",
                tags=["实施路线", "能力边界", stage],
                sources=source(workbook, sheet.title, row, "G"),
                metadata={
                    "source_sheet": sheet.title,
                    "source_row": row,
                    "roadmap_stage": stage,
                    "executable": False,
                },
            )
        )
    return documents


def build(workbook_path: Path) -> list[dict[str, Any]]:
    workbook = openpyxl.load_workbook(workbook_path, data_only=True)
    documents = [
        *knowledge_documents(workbook_path, workbook["知识总表"]),
        *field_documents(workbook_path, workbook["必填输入字段"]),
        *rule_spec_documents(workbook_path, workbook["验算规则"]),
        *classification_documents(workbook_path, workbook["知识库分类"]),
        *roadmap_documents(workbook_path, workbook["实施路线"]),
    ]
    ids = [item["doc_id"] for item in documents]
    duplicate_ids = sorted({item for item in ids if ids.count(item) > 1})
    if duplicate_ids:
        raise ValueError(f"Duplicate document IDs: {duplicate_ids}")
    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ES knowledge JSONL from the mechanics workbook")
    parser.add_argument("workbook", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    documents = build(args.workbook)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for document in documents:
            handle.write(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")

    counts: dict[str, int] = {}
    for document in documents:
        sheet = str(document["metadata"]["source_sheet"])
        counts[sheet] = counts.get(sheet, 0) + 1
    print(json.dumps({"documents": len(documents), "by_sheet": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
