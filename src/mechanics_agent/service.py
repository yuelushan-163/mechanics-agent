from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from mechanics_agent.embeddings import Embedder
from mechanics_agent.knowledge.base import KnowledgeRepository
from mechanics_agent.models import (
    AuditRecord,
    DocumentType,
    IngestResponse,
    KnowledgeDocument,
    KnowledgeSearchRequest,
    ModelUsageRecord,
    ModelUsageSummary,
    PlanRequest,
    PlanResponse,
    SearchHit,
    VerificationRequest,
    VerificationStage,
    VerificationSummary,
)
from mechanics_agent.planner import Planner
from mechanics_agent.rules import VerificationEngine
from mechanics_agent.usage import ModelUsageTracker


class MechanicsAgentService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        planner: Planner,
        embedder: Embedder,
        verification_engine: VerificationEngine | None = None,
        usage_tracker: ModelUsageTracker | None = None,
    ) -> None:
        self.repository = repository
        self.planner = planner
        self.embedder = embedder
        self.verification_engine = verification_engine or VerificationEngine()
        self.usage_tracker = usage_tracker

    async def initialize(self) -> None:
        await self.repository.ensure_indices()

    async def ingest(self, documents: list[KnowledgeDocument]) -> IngestResponse:
        prepared: list[KnowledgeDocument] = []
        for document in documents:
            if document.embedding is None and self.embedder.enabled:
                embedding = await self.embedder.embed(
                    f"{document.title}\n{document.content}\n标签：{' '.join(document.tags)}",
                    operation="embedding:ingest",
                )
                document = document.model_copy(update={"embedding": embedding})
            prepared.append(document)
        indexed = await self.repository.upsert_documents(prepared)
        return IngestResponse(
            indexed=indexed,
            index_name=self.repository.knowledge_index_name,
        )

    async def search(self, request: KnowledgeSearchRequest) -> list[SearchHit]:
        vector = request.query_vector
        if vector is None and self.embedder.enabled:
            vector = await self.embedder.embed(
                request.query,
                operation="embedding:search",
            )
        return await self.repository.search(
            request.query,
            analysis_type=request.analysis_type,
            domain=request.domain,
            document_types=request.document_types,
            query_vector=vector,
            top_k=request.top_k,
        )

    async def plan(self, request: PlanRequest) -> PlanResponse:
        query = self._case_query(request)
        vector = request.query_vector
        if vector is None and self.embedder.enabled:
            vector = await self.embedder.embed(
                query,
                operation="embedding:plan",
            )
        hits = await self.repository.search(
            query,
            analysis_type=request.case.analysis_type,
            document_types=[
                DocumentType.KNOWLEDGE,
                DocumentType.MATERIAL,
                DocumentType.BENCHMARK,
                DocumentType.SOLVER_ERROR,
            ],
            query_vector=vector,
            top_k=request.top_k,
        )
        pre_rules = await self.repository.get_rules(
            VerificationStage.PRE, request.case.analysis_type
        )
        post_rules = await self.repository.get_rules(
            VerificationStage.POST, request.case.analysis_type
        )
        all_rules = [*pre_rules, *post_rules]
        precheck = self.verification_engine.evaluate(
            request.case,
            VerificationStage.PRE,
            evidence={},
            rules=pre_rules,
        )
        plan = await self.planner.plan(request.case, hits, all_rules)
        response = PlanResponse(
            plan=plan,
            precheck=precheck,
            knowledge_hits=hits,
            planner=self.planner.name,
        )
        await self.repository.record_run(
            AuditRecord(
                run_id=str(uuid4()),
                case_id=request.case.case_id,
                event_type="plan",
                overall=precheck.overall,
                payload=response.model_dump(mode="json"),
            )
        )
        return response

    async def verify(self, request: VerificationRequest) -> VerificationSummary:
        rules = await self.repository.get_rules(request.stage, request.case.analysis_type)
        summary = self.verification_engine.evaluate(
            request.case, request.stage, request.evidence, rules
        )
        await self.repository.record_run(
            AuditRecord(
                run_id=str(uuid4()),
                case_id=request.case.case_id,
                event_type=f"verify:{request.stage.value}",
                overall=summary.overall,
                payload={
                    "request": request.model_dump(mode="json"),
                    "summary": summary.model_dump(mode="json"),
                },
            )
        )
        return summary

    async def health(self) -> dict[str, object]:
        backend = await self.repository.health()
        return {
            "status": "ok",
            "repository": backend,
            "planner": self.planner.name,
            "embeddings_enabled": self.embedder.enabled,
            "usage_tracking": {
                "enabled": self.usage_tracker is not None,
                "priced_models": len(self.pricing()),
            },
        }

    async def test_planner(self) -> dict[str, object]:
        return await self.planner.test_connection()

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
        return await self.repository.list_model_usage(
            provider=provider,
            model=model,
            operation=operation,
            from_time=from_time,
            to_time=to_time,
            limit=limit,
        )

    async def summarize_model_usage(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        operation: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> ModelUsageSummary:
        return await self.repository.summarize_model_usage(
            provider=provider,
            model=model,
            operation=operation,
            from_time=from_time,
            to_time=to_time,
        )

    def pricing(self) -> list[dict[str, object]]:
        if not self.usage_tracker:
            return []
        return self.usage_tracker.pricing.as_dicts()

    async def close(self) -> None:
        await self.repository.close()
        await self.planner.close()
        await self.embedder.close()

    @staticmethod
    def _case_query(request: PlanRequest) -> str:
        case = request.case
        parts = [
            case.title,
            case.description or "",
            case.analysis_type,
            case.geometry_type or "",
            case.material.name if case.material else "",
            " ".join(item.load_type for item in case.loads),
            " ".join(item.boundary_type for item in case.boundary_conditions),
            " ".join(item.name for item in case.contacts),
            " ".join(item.procedure for item in case.analysis_steps),
            " ".join(item.name for item in case.benchmarks),
            case.idealization.model_dimension
            if case.idealization and case.idealization.model_dimension
            else "",
            case.idealization.symmetry
            if case.idealization and case.idealization.symmetry
            else "",
            " ".join(case.required_confirmations),
            " ".join(case.objectives),
        ]
        return " ".join(part for part in parts if part).strip()
