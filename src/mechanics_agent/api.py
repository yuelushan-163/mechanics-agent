from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from time import perf_counter
import traceback
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from mechanics_agent.config import Settings
from mechanics_agent.case_catalog import get_case_template, list_case_templates
from mechanics_agent.debug_logs import DebugLogStore, redact_text, redact_value
from mechanics_agent.embeddings import Embedder, EmbeddingError, build_embedder
from mechanics_agent.knowledge.base import KnowledgeRepository
from mechanics_agent.knowledge.elasticsearch import (
    ElasticsearchKnowledgeRepository,
    ElasticsearchRepositoryError,
)
from mechanics_agent.models import (
    ActiveProbeRequest,
    ActiveProbeResponse,
    ApprovalCreate,
    ApprovalDecision,
    ApprovalDecisionUpdate,
    ApprovalRecord,
    ClientErrorLogCreate,
    CaseTemplate,
    IngestResponse,
    KnowledgeDocument,
    KnowledgeSearchRequest,
    ModelUsageRecord,
    ModelUsageSummary,
    MonitoringSnapshot,
    PersistedErrorLog,
    PlanRequest,
    PlanResponse,
    ProjectCreate,
    ProjectRecord,
    SearchHit,
    TaskCreate,
    TaskRecord,
    TaskStatus,
    TaskStatusUpdate,
    UserCreate,
    UserRecord,
    VerificationRequest,
    VerificationSummary,
)
from mechanics_agent.monitoring import BackendMonitor
from mechanics_agent.operations import (
    OperationsConflictError,
    OperationsNotFoundError,
    OperationsRepository,
    OperationsRepositoryError,
    build_operations_repository,
)
from mechanics_agent.planner import Planner, PlannerError, build_planner
from mechanics_agent.service import MechanicsAgentService
from mechanics_agent.usage import (
    ModelUsageTracker,
    PricingCatalog,
    reset_usage_request_id,
    set_usage_request_id,
)


FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


def create_app(
    settings: Settings | None = None,
    *,
    repository: KnowledgeRepository | None = None,
    planner: Planner | None = None,
    embedder: Embedder | None = None,
    log_store: DebugLogStore | None = None,
    operations_repository: OperationsRepository | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_log_store = log_store or DebugLogStore()
    resolved_repository = repository or ElasticsearchKnowledgeRepository(resolved_settings)
    resolved_operations = operations_repository or build_operations_repository(
        resolved_settings
    )

    async def persist_operational_error(entry: dict[str, object]) -> None:
        if str(entry.get("level", "")).upper() in {"ERROR", "WARNING"}:
            await resolved_operations.record_error_log(entry)

    resolved_log_store.set_on_add(persist_operational_error)
    usage_tracker = ModelUsageTracker(
        resolved_repository,
        PricingCatalog.from_settings(resolved_settings),
        on_record_error=lambda exc, details: resolved_log_store.add_exception(
            exc,
            request_id=None,
            method="MODEL_USAGE",
            path="usage-persistence",
            status_code=None,
            details=details,
        ),
    )
    resolved_planner = planner or build_planner(
        resolved_settings,
        usage_tracker=usage_tracker,
    )
    resolved_embedder = embedder or build_embedder(
        resolved_settings,
        usage_tracker=usage_tracker,
    )
    service = MechanicsAgentService(
        resolved_repository,
        resolved_planner,
        resolved_embedder,
        usage_tracker=usage_tracker,
    )
    monitor = BackendMonitor(
        resolved_settings,
        resolved_repository,
        resolved_planner,
        resolved_embedder,
        on_error=lambda exc, details: resolved_log_store.add_exception(
            exc,
            request_id=None,
            method="MONITOR",
            path="backend-monitoring",
            status_code=None,
            details=details,
        ),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.service = service
        try:
            await asyncio.wait_for(
                resolved_operations.initialize(),
                timeout=resolved_settings.startup_timeout_seconds,
            )
        except Exception as exc:
            app.state.operations_error = str(exc)
            resolved_log_store.add_exception(
                exc,
                request_id=None,
                method="STARTUP",
                path="mongodb-operations",
                details={"component": "mongodb"},
            )
        else:
            app.state.operations_error = None
        try:
            await asyncio.wait_for(
                service.initialize(),
                timeout=resolved_settings.startup_timeout_seconds,
            )
        except Exception as exc:
            app.state.startup_error = str(exc)
            resolved_log_store.add_exception(
                exc,
                request_id=None,
                method="STARTUP",
                path="application-lifespan",
                details={"component": "service-initialization"},
            )
        else:
            app.state.startup_error = None
            resolved_log_store.add(
                level="INFO",
                message="服务初始化完成",
                method="STARTUP",
                path="application-lifespan",
            )
        await monitor.start()
        try:
            yield
        finally:
            await monitor.stop()
            try:
                await service.close()
            except Exception as exc:
                resolved_log_store.add_exception(
                    exc,
                    request_id=None,
                    method="SHUTDOWN",
                    path="application-lifespan",
                    details={"component": "service-close"},
                )
            try:
                await resolved_operations.close()
            except Exception as exc:
                resolved_log_store.add_exception(
                    exc,
                    request_id=None,
                    method="SHUTDOWN",
                    path="mongodb-operations",
                    details={"component": "mongodb"},
                )

    app = FastAPI(
        title="Mechanics Agent API",
        version="0.3.0",
        description=(
            "LLM-assisted mechanics knowledge retrieval and deterministic verification service"
        ),
        lifespan=lifespan,
    )
    app.state.service = service
    app.state.monitor = monitor
    app.state.debug_logs = resolved_log_store
    app.state.operations = resolved_operations
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")

    @app.middleware("http")
    async def request_diagnostics(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid4().hex[:12]
        request.state.request_id = request_id
        usage_context_token = set_usage_request_id(request_id)
        started_at = perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (perf_counter() - started_at) * 1000
            resolved_log_store.add_exception(
                exc,
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "服务端发生未处理异常",
                    "request_id": request_id,
                    "exception_type": type(exc).__name__,
                },
                headers={"x-request-id": request_id},
            )
        finally:
            reset_usage_request_id(usage_context_token)

        duration_ms = (perf_counter() - started_at) * 1000
        response.headers["x-request-id"] = request_id
        if (
            response.status_code >= 400
            and not getattr(request.state, "error_logged", False)
            and not request.url.path.startswith("/v1/debug/logs")
        ):
            resolved_log_store.add(
                level="ERROR" if response.status_code >= 500 else "WARNING",
                message=f"HTTP {response.status_code}",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
        return response

    @app.exception_handler(ElasticsearchRepositoryError)
    async def elasticsearch_error_handler(
        request: Request, exc: ElasticsearchRepositoryError
    ) -> JSONResponse:
        _record_handled_error(
            request,
            resolved_log_store,
            exc,
            status_code=503,
            component="elasticsearch",
        )
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc), "request_id": request.state.request_id},
        )

    @app.exception_handler(PlannerError)
    async def planner_error_handler(request: Request, exc: PlannerError) -> JSONResponse:
        _record_handled_error(
            request,
            resolved_log_store,
            exc,
            status_code=502,
            component="planner",
        )
        return JSONResponse(
            status_code=502,
            content={"detail": str(exc), "request_id": request.state.request_id},
        )

    @app.exception_handler(EmbeddingError)
    async def embedding_error_handler(
        request: Request, exc: EmbeddingError
    ) -> JSONResponse:
        _record_handled_error(
            request,
            resolved_log_store,
            exc,
            status_code=502,
            component="embedding",
        )
        return JSONResponse(
            status_code=502,
            content={"detail": str(exc), "request_id": request.state.request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request.state.error_logged = True
        resolved_log_store.add(
            level="WARNING",
            message="请求数据校验失败",
            request_id=request.state.request_id,
            method=request.method,
            path=request.url.path,
            status_code=422,
            details={"errors": exc.errors()},
        )
        return JSONResponse(
            status_code=422,
            content={
                "detail": exc.errors(),
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(OperationsNotFoundError)
    async def operations_not_found_handler(
        request: Request, exc: OperationsNotFoundError
    ) -> JSONResponse:
        _record_handled_error(
            request,
            resolved_log_store,
            exc,
            status_code=404,
            component="mongodb",
        )
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "request_id": request.state.request_id},
        )

    @app.exception_handler(OperationsConflictError)
    async def operations_conflict_handler(
        request: Request, exc: OperationsConflictError
    ) -> JSONResponse:
        _record_handled_error(
            request,
            resolved_log_store,
            exc,
            status_code=409,
            component="mongodb",
        )
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "request_id": request.state.request_id},
        )

    @app.exception_handler(OperationsRepositoryError)
    async def operations_error_handler(
        request: Request, exc: OperationsRepositoryError
    ) -> JSONResponse:
        _record_handled_error(
            request,
            resolved_log_store,
            exc,
            status_code=503,
            component="mongodb",
        )
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc), "request_id": request.state.request_id},
        )

    @app.get("/", include_in_schema=False)
    async def frontend() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/cases", include_in_schema=False)
    @app.get("/cases/", include_in_schema=False)
    async def cases_frontend() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "cases.html")

    @app.get("/analysis/new", include_in_schema=False)
    @app.get("/analysis/new/", include_in_schema=False)
    async def new_analysis_frontend() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "analysis-new.html")

    @app.get("/analysis/result", include_in_schema=False)
    @app.get("/analysis/result/", include_in_schema=False)
    async def analysis_result_frontend() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "analysis-result.html")

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/", include_in_schema=False)
    async def admin_frontend() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "admin" / "index.html")

    @app.get("/health", response_model=MonitoringSnapshot)
    async def health(
        backend_monitor: Annotated[BackendMonitor, Depends(_get_monitor)],
    ) -> MonitoringSnapshot:
        return await backend_monitor.get_snapshot()

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/monitoring/status", response_model=MonitoringSnapshot)
    async def monitoring_status(
        backend_monitor: Annotated[BackendMonitor, Depends(_get_monitor)],
        refresh: bool = False,
    ) -> MonitoringSnapshot:
        return await backend_monitor.get_snapshot(refresh=refresh)

    @app.post("/v1/monitoring/probe", response_model=ActiveProbeResponse)
    async def active_monitoring_probe(
        probe_request: ActiveProbeRequest,
        backend_monitor: Annotated[BackendMonitor, Depends(_get_monitor)],
    ) -> ActiveProbeResponse:
        return await backend_monitor.active_probe(probe_request.targets)

    @app.get("/v1/operations/health")
    async def operations_health(
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
    ) -> dict[str, object]:
        return await operations.health()

    @app.post("/v1/users", response_model=UserRecord, status_code=201)
    async def create_user(
        payload: UserCreate,
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
    ) -> UserRecord:
        return await operations.create_user(payload)

    @app.get("/v1/users", response_model=list[UserRecord])
    async def list_users(
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[UserRecord]:
        return await operations.list_users(limit=limit)

    @app.get("/v1/users/{user_id}", response_model=UserRecord)
    async def get_user(
        user_id: str,
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
    ) -> UserRecord:
        return await operations.get_user(user_id)

    @app.post("/v1/projects", response_model=ProjectRecord, status_code=201)
    async def create_project(
        payload: ProjectCreate,
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
    ) -> ProjectRecord:
        return await operations.create_project(payload)

    @app.get("/v1/projects", response_model=list[ProjectRecord])
    async def list_projects(
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
        owner_user_id: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[ProjectRecord]:
        return await operations.list_projects(
            owner_user_id=owner_user_id,
            limit=limit,
        )

    @app.get("/v1/projects/{project_id}", response_model=ProjectRecord)
    async def get_project(
        project_id: str,
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
    ) -> ProjectRecord:
        return await operations.get_project(project_id)

    @app.post("/v1/tasks", response_model=TaskRecord, status_code=201)
    async def create_task(
        payload: TaskCreate,
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
    ) -> TaskRecord:
        return await operations.create_task(payload)

    @app.get("/v1/tasks", response_model=list[TaskRecord])
    async def list_tasks(
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
        project_id: str | None = None,
        status: TaskStatus | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
    ) -> list[TaskRecord]:
        return await operations.list_tasks(
            project_id=project_id,
            status=status,
            limit=limit,
        )

    @app.get("/v1/tasks/{task_id}", response_model=TaskRecord)
    async def get_task(
        task_id: str,
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
    ) -> TaskRecord:
        return await operations.get_task(task_id)

    @app.patch("/v1/tasks/{task_id}/status", response_model=TaskRecord)
    async def update_task_status(
        task_id: str,
        payload: TaskStatusUpdate,
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
    ) -> TaskRecord:
        return await operations.update_task_status(task_id, payload)

    @app.post("/v1/approvals", response_model=ApprovalRecord, status_code=201)
    async def create_approval(
        payload: ApprovalCreate,
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
    ) -> ApprovalRecord:
        return await operations.create_approval(payload)

    @app.get("/v1/approvals", response_model=list[ApprovalRecord])
    async def list_approvals(
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
        project_id: str | None = None,
        task_id: str | None = None,
        decision: ApprovalDecision | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
    ) -> list[ApprovalRecord]:
        return await operations.list_approvals(
            project_id=project_id,
            task_id=task_id,
            decision=decision,
            limit=limit,
        )

    @app.patch(
        "/v1/approvals/{approval_id}/decision",
        response_model=ApprovalRecord,
    )
    async def decide_approval(
        approval_id: str,
        payload: ApprovalDecisionUpdate,
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
    ) -> ApprovalRecord:
        return await operations.decide_approval(approval_id, payload)

    @app.get("/v1/operations/error-logs", response_model=list[PersistedErrorLog])
    async def list_persisted_error_logs(
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
        level: Annotated[str | None, Query(pattern="^(ERROR|WARNING)$")] = None,
        request_id: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
    ) -> list[PersistedErrorLog]:
        return await operations.list_error_logs(
            level=level,
            request_id=request_id,
            limit=limit,
        )

    @app.post(
        "/v1/operations/error-logs/client",
        response_model=PersistedErrorLog,
        status_code=201,
    )
    async def persist_client_error_log(
        payload: ClientErrorLogCreate,
        operations: Annotated[OperationsRepository, Depends(_get_operations)],
    ) -> PersistedErrorLog:
        return await operations.record_error_log(
            {
                **payload.model_dump(mode="python"),
                "source": "client",
                "message": redact_text(payload.message),
                "details": redact_value(payload.details),
                "traceback": redact_text(payload.traceback) if payload.traceback else None,
            }
        )

    @app.post("/v1/knowledge/documents", response_model=IngestResponse)
    async def ingest_documents(
        documents: list[KnowledgeDocument],
        agent_service: Annotated[MechanicsAgentService, Depends(_get_service)],
    ) -> IngestResponse:
        return await agent_service.ingest(documents)

    @app.post("/v1/knowledge/search", response_model=list[SearchHit])
    async def search_knowledge(
        search_request: KnowledgeSearchRequest,
        agent_service: Annotated[MechanicsAgentService, Depends(_get_service)],
    ) -> list[SearchHit]:
        return await agent_service.search(search_request)

    @app.post("/v1/cases/plan", response_model=PlanResponse)
    async def plan_case(
        plan_request: PlanRequest,
        agent_service: Annotated[MechanicsAgentService, Depends(_get_service)],
    ) -> PlanResponse:
        return await agent_service.plan(plan_request)

    @app.get("/v1/cases/templates", response_model=list[CaseTemplate])
    async def case_templates() -> list[CaseTemplate]:
        """List reviewed drafts without invoking an LLM or solver."""

        return list_case_templates()

    @app.get("/v1/cases/templates/{template_id}", response_model=CaseTemplate)
    async def case_template(template_id: str) -> CaseTemplate:
        """Return one immutable acceptance-case draft."""

        template = get_case_template(template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="测试案例模板不存在")
        return template

    @app.post("/v1/cases/verify", response_model=VerificationSummary)
    async def verify_case(
        verification_request: VerificationRequest,
        agent_service: Annotated[MechanicsAgentService, Depends(_get_service)],
    ) -> VerificationSummary:
        return await agent_service.verify(verification_request)

    @app.get("/v1/debug/logs")
    async def get_debug_logs(
        after: Annotated[int, Query(ge=0)] = 0,
        level: Annotated[str | None, Query(pattern="^(INFO|WARNING|ERROR)$")] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
    ) -> dict[str, object]:
        return {
            "entries": resolved_log_store.list(after=after, level=level, limit=limit),
            "latest_sequence": resolved_log_store.latest_sequence,
        }

    @app.delete("/v1/debug/logs")
    async def clear_debug_logs() -> dict[str, int]:
        return {"cleared": resolved_log_store.clear()}

    @app.post("/v1/debug/planner/test")
    async def test_planner(
        agent_service: Annotated[MechanicsAgentService, Depends(_get_service)],
    ) -> dict[str, object]:
        return await agent_service.test_planner()

    @app.get("/v1/usage/events", response_model=list[ModelUsageRecord])
    async def list_model_usage(
        agent_service: Annotated[MechanicsAgentService, Depends(_get_service)],
        provider: str | None = None,
        model: str | None = None,
        operation: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
    ) -> list[ModelUsageRecord]:
        return await agent_service.list_model_usage(
            provider=provider,
            model=model,
            operation=operation,
            from_time=from_time,
            to_time=to_time,
            limit=limit,
        )

    @app.get("/v1/usage/summary", response_model=ModelUsageSummary)
    async def summarize_model_usage(
        agent_service: Annotated[MechanicsAgentService, Depends(_get_service)],
        provider: str | None = None,
        model: str | None = None,
        operation: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> ModelUsageSummary:
        return await agent_service.summarize_model_usage(
            provider=provider,
            model=model,
            operation=operation,
            from_time=from_time,
            to_time=to_time,
        )

    @app.get("/v1/usage/pricing")
    async def get_model_pricing(
        agent_service: Annotated[MechanicsAgentService, Depends(_get_service)],
    ) -> dict[str, object]:
        return {
            "currency": "CNY",
            "unit_tokens": 1000,
            "models": agent_service.pricing(),
        }

    return app


def _get_service(request: Request) -> MechanicsAgentService:
    return request.app.state.service


def _get_monitor(request: Request) -> BackendMonitor:
    return request.app.state.monitor


def _get_operations(request: Request) -> OperationsRepository:
    return request.app.state.operations


def _record_handled_error(
    request: Request,
    log_store: DebugLogStore,
    exc: BaseException,
    *,
    status_code: int,
    component: str,
) -> None:
    request.state.error_logged = True
    log_store.add(
        level="ERROR",
        message=f"{type(exc).__name__}: {exc}",
        request_id=request.state.request_id,
        method=request.method,
        path=request.url.path,
        status_code=status_code,
        details={"component": component, "exception_type": type(exc).__name__},
        traceback_text="".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ),
    )


app = create_app()
