from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from mechanics_agent.models import (
    AuditRecord,
    DocumentType,
    KnowledgeDocument,
    ModelUsageRecord,
    ModelUsageSummary,
    SearchHit,
    VerificationRule,
    VerificationStage,
)


class KnowledgeRepository(Protocol):
    @property
    def knowledge_index_name(self) -> str: ...

    async def ensure_indices(self) -> None: ...

    async def upsert_documents(self, documents: list[KnowledgeDocument]) -> int: ...

    async def search(
        self,
        query: str,
        *,
        analysis_type: str | None = None,
        domain: str | None = None,
        document_types: list[DocumentType] | None = None,
        query_vector: list[float] | None = None,
        top_k: int = 8,
    ) -> list[SearchHit]: ...

    async def get_rules(
        self, stage: VerificationStage, analysis_type: str
    ) -> list[tuple[str, VerificationRule]]: ...

    async def record_run(self, record: AuditRecord) -> None: ...

    async def record_model_usage(self, record: ModelUsageRecord) -> None: ...

    async def list_model_usage(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        operation: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        limit: int = 200,
    ) -> list[ModelUsageRecord]: ...

    async def summarize_model_usage(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        operation: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> ModelUsageSummary: ...

    async def health(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...
