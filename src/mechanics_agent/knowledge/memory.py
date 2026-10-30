from __future__ import annotations

from datetime import datetime
from typing import Any

from mechanics_agent.models import (
    AuditRecord,
    DocumentType,
    KnowledgeDocument,
    ModelUsageRecord,
    ModelUsageSummary,
    ReviewStatus,
    SearchHit,
    VerificationRule,
    VerificationStage,
)
from mechanics_agent.usage import summarize_usage_records


class InMemoryKnowledgeRepository:
    def __init__(self) -> None:
        self.documents: dict[str, KnowledgeDocument] = {}
        self.runs: list[AuditRecord] = []
        self.model_usage: list[ModelUsageRecord] = []

    @property
    def knowledge_index_name(self) -> str:
        return "memory"

    async def ensure_indices(self) -> None:
        return None

    async def upsert_documents(self, documents: list[KnowledgeDocument]) -> int:
        for document in documents:
            self.documents[document.doc_id] = document
        return len(documents)

    async def search(
        self,
        query: str,
        *,
        analysis_type: str | None = None,
        domain: str | None = None,
        document_types: list[DocumentType] | None = None,
        query_vector: list[float] | None = None,
        top_k: int = 8,
    ) -> list[SearchHit]:
        del query_vector
        terms = {part.casefold() for part in query.split() if part.strip()}
        hits: list[SearchHit] = []
        allowed_types = set(document_types or [])
        for document in self.documents.values():
            if document.status != ReviewStatus.APPROVED:
                continue
            if allowed_types and document.doc_type not in allowed_types:
                continue
            if domain and document.domain != domain:
                continue
            if analysis_type and not _supports_analysis(document.analysis_types, analysis_type):
                continue
            haystack = " ".join(
                [
                    document.title,
                    document.content,
                    document.domain,
                    *document.analysis_types,
                    *document.tags,
                ]
            ).casefold()
            overlap = sum(1 for term in terms if term in haystack)
            score = float(overlap) + (0.1 if not terms else 0.0)
            if score > 0:
                hits.append(SearchHit(score=score, document=document))
        hits.sort(key=lambda item: (-item.score, item.document.doc_id))
        return hits[:top_k]

    async def get_rules(
        self, stage: VerificationStage, analysis_type: str
    ) -> list[tuple[str, VerificationRule]]:
        rules: list[tuple[str, VerificationRule]] = []
        for document in self.documents.values():
            rule = document.rule
            if (
                document.status == ReviewStatus.APPROVED
                and document.doc_type == DocumentType.VERIFICATION_RULE
                and rule is not None
                and rule.enabled
                and rule.stage == stage
                and _supports_analysis(rule.analysis_types, analysis_type)
            ):
                rules.append((document.doc_id, rule))
        rules.sort(key=lambda item: item[1].rule_id)
        return rules

    async def record_run(self, record: AuditRecord) -> None:
        self.runs.append(record)

    async def record_model_usage(self, record: ModelUsageRecord) -> None:
        self.model_usage.append(record)

    async def list_model_usage(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        operation: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        limit: int = 200,
    ) -> list[ModelUsageRecord]:
        records = [
            item
            for item in self.model_usage
            if (provider is None or item.provider == provider)
            and (model is None or item.model == model)
            and (operation is None or item.operation == operation)
            and (from_time is None or item.created_at >= from_time)
            and (to_time is None or item.created_at <= to_time)
        ]
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records[:limit]

    async def summarize_model_usage(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        operation: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> ModelUsageSummary:
        records = await self.list_model_usage(
            provider=provider,
            model=model,
            operation=operation,
            from_time=from_time,
            to_time=to_time,
            limit=max(len(self.model_usage), 1),
        )
        return summarize_usage_records(records)

    async def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "backend": "memory",
            "documents": len(self.documents),
            "runs": len(self.runs),
            "model_usage_events": len(self.model_usage),
        }

    async def close(self) -> None:
        return None


def _supports_analysis(supported: list[str], requested: str) -> bool:
    return "*" in supported or requested in supported
