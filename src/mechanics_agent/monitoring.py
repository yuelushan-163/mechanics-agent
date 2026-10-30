from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from contextlib import suppress
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable

from mechanics_agent.config import Settings
from mechanics_agent.embeddings import Embedder
from mechanics_agent.knowledge.base import KnowledgeRepository
from mechanics_agent.models import (
    ActiveProbeResponse,
    ModelUsageRecord,
    ModelUsageStatus,
    ModelUsageSummary,
    MonitoringComponent,
    MonitoringSnapshot,
    MonitoringState,
)
from mechanics_agent.planner import Planner


MonitorErrorHandler = Callable[[BaseException, dict[str, object]], None]


class BackendMonitor:
    def __init__(
        self,
        settings: Settings,
        repository: KnowledgeRepository,
        planner: Planner,
        embedder: Embedder,
        *,
        on_error: MonitorErrorHandler | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.planner = planner
        self.embedder = embedder
        self.on_error = on_error
        self._refresh_lock = asyncio.Lock()
        self._snapshot_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._reported_failures: dict[str, str] = {}
        self._snapshot = self._initial_snapshot()

    async def start(self) -> None:
        if not self.settings.monitoring_enabled or self._task is not None:
            return
        self._task = asyncio.create_task(
            self._run_loop(),
            name="mechanics-agent-backend-monitor",
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def get_snapshot(self, *, refresh: bool = False) -> MonitoringSnapshot:
        if refresh:
            await self.refresh()
        async with self._snapshot_lock:
            return self._snapshot.model_copy(deep=True)

    async def refresh(self) -> MonitoringSnapshot:
        async with self._refresh_lock:
            repository_health, repository_error, repository_latency = await self._timed(
                self.repository.health(),
                timeout=self.settings.monitoring_timeout_seconds,
            )
            if repository_error is None:
                self._reported_failures.pop("repository", None)
                repository_component = MonitoringComponent(
                    component="repository",
                    label="Elasticsearch",
                    status=MonitoringState.HEALTHY,
                    detail="Elasticsearch连接正常",
                    latency_ms=repository_latency,
                    metadata=(
                        repository_health
                        if isinstance(repository_health, dict)
                        else {}
                    ),
                )
                usage_summary, usage_error, usage_latency = await self._timed(
                    self.repository.summarize_model_usage(),
                    timeout=self.settings.monitoring_timeout_seconds,
                )
                recent_usage, recent_error, _ = await self._timed(
                    self.repository.list_model_usage(limit=100),
                    timeout=self.settings.monitoring_timeout_seconds,
                )
                if usage_error is None:
                    self._reported_failures.pop("usage-summary", None)
                else:
                    self._report_check_error_once("usage-summary", usage_error)
                if recent_error is None:
                    self._reported_failures.pop("usage-events", None)
                else:
                    self._report_check_error_once("usage-events", recent_error)
            else:
                self._report_check_error_once("repository", repository_error)
                repository_component = MonitoringComponent(
                    component="repository",
                    label="Elasticsearch",
                    status=MonitoringState.UNAVAILABLE,
                    detail=str(repository_error),
                    latency_ms=repository_latency,
                    metadata={"error_type": type(repository_error).__name__},
                )
                usage_summary = None
                usage_error = repository_error
                usage_latency = repository_latency
                recent_usage = []
                recent_error = repository_error

            normalized_summary = (
                usage_summary if isinstance(usage_summary, ModelUsageSummary) else None
            )
            normalized_recent = (
                recent_usage if isinstance(recent_usage, list) else []
            )
            usage_component = self._usage_component(
                normalized_summary,
                usage_error,
                usage_latency,
            )
            planner_component = self._planner_component(
                normalized_recent,
                recent_error,
            )
            embedding_component = self._embedding_component(
                normalized_recent,
                recent_error,
            )
            components = {
                "api": MonitoringComponent(
                    component="api",
                    label="后端API",
                    status=MonitoringState.HEALTHY,
                    detail="FastAPI进程正常",
                ),
                "repository": repository_component,
                "planner": planner_component,
                "embedding": embedding_component,
                "usage": usage_component,
            }
            overall = self._overall_state(components)
            snapshot = MonitoringSnapshot(
                status=overall,
                components=components,
                usage=normalized_summary,
            )
            async with self._snapshot_lock:
                self._snapshot = snapshot
            return snapshot.model_copy(deep=True)

    async def active_probe(self, targets: list[str]) -> ActiveProbeResponse:
        selected = list(dict.fromkeys(targets))
        results: dict[str, dict[str, Any]] = {}
        for target in selected:
            if target == "planner":
                results[target] = await self._probe_one(
                    target,
                    self.planner.test_connection(),
                )
            elif target == "embedding":
                results[target] = await self._probe_one(
                    target,
                    self.embedder.test_connection(),
                )
        snapshot = await self.refresh()
        return ActiveProbeResponse(results=results, snapshot=snapshot)

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.refresh()
            except Exception as exc:
                self._report_error(exc, {"component": "monitoring-loop"})
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.settings.monitoring_interval_seconds,
                )
            except TimeoutError:
                continue

    async def _probe_one(
        self,
        target: str,
        awaitable: Awaitable[dict[str, object]],
    ) -> dict[str, Any]:
        started_at = perf_counter()
        try:
            result = await asyncio.wait_for(
                awaitable,
                timeout=self.settings.request_timeout_seconds,
            )
        except Exception as exc:
            self._report_error(
                exc,
                {"component": target, "operation": "active-probe"},
            )
            return {
                "status": "error",
                "error_type": type(exc).__name__,
                "detail": str(exc),
                "latency_ms": round((perf_counter() - started_at) * 1000, 3),
            }
        return {
            **result,
            "latency_ms": round((perf_counter() - started_at) * 1000, 3),
        }

    async def _timed(
        self,
        awaitable: Awaitable[object],
        *,
        timeout: float,
    ) -> tuple[object | None, BaseException | None, float]:
        started_at = perf_counter()
        try:
            result = await asyncio.wait_for(awaitable, timeout=timeout)
        except Exception as exc:
            return None, exc, round((perf_counter() - started_at) * 1000, 3)
        return result, None, round((perf_counter() - started_at) * 1000, 3)

    def _planner_component(
        self,
        recent_usage: list[ModelUsageRecord],
        usage_error: BaseException | None,
    ) -> MonitoringComponent:
        if self.planner.name == "local-deterministic":
            return MonitoringComponent(
                component="planner",
                label="规划模型",
                status=MonitoringState.NOT_CONFIGURED,
                detail="未配置在线规划模型，当前使用本地确定性规划器",
                metadata={"planner": self.planner.name},
            )
        provider, _, model = self.planner.name.partition(":")
        return self._model_component(
            component="planner",
            label="规划模型",
            provider=provider,
            model=model,
            recent_usage=recent_usage,
            usage_error=usage_error,
        )

    def _embedding_component(
        self,
        recent_usage: list[ModelUsageRecord],
        usage_error: BaseException | None,
    ) -> MonitoringComponent:
        if not self.embedder.enabled:
            return MonitoringComponent(
                component="embedding",
                label="Embedding模型",
                status=MonitoringState.NOT_CONFIGURED,
                detail="未配置Embedding服务，当前使用ES全文检索",
            )
        return self._model_component(
            component="embedding",
            label="Embedding模型",
            provider=self.embedder.provider_name or "unknown",
            model=self.embedder.model_name or "unknown",
            recent_usage=recent_usage,
            usage_error=usage_error,
        )

    @staticmethod
    def _model_component(
        *,
        component: str,
        label: str,
        provider: str,
        model: str,
        recent_usage: list[ModelUsageRecord],
        usage_error: BaseException | None,
    ) -> MonitoringComponent:
        latest = next(
            (
                item
                for item in recent_usage
                if item.provider == provider and item.model == model
            ),
            None,
        )
        if latest is None:
            detail = "已配置，尚无实际调用记录"
            if usage_error:
                detail = f"已配置，但无法读取最近调用：{usage_error}"
            return MonitoringComponent(
                component=component,
                label=label,
                status=MonitoringState.CONFIGURED,
                detail=detail,
                metadata={"provider": provider, "model": model},
            )
        is_success = latest.status == ModelUsageStatus.SUCCESS
        return MonitoringComponent(
            component=component,
            label=label,
            status=(
                MonitoringState.HEALTHY
                if is_success
                else MonitoringState.DEGRADED
            ),
            detail=(
                f"最近调用成功：{latest.operation}"
                if is_success
                else f"最近调用失败：{latest.error_type or latest.operation}"
            ),
            latency_ms=latest.latency_ms,
            metadata={
                "provider": provider,
                "model": model,
                "last_operation": latest.operation,
                "last_request_id": latest.request_id,
                "last_called_at": latest.created_at.isoformat(),
                "last_total_tokens": latest.total_tokens,
                "last_total_cost": latest.total_cost,
                "currency": latest.currency,
            },
        )

    @staticmethod
    def _usage_component(
        summary: ModelUsageSummary | None,
        error: BaseException | None,
        latency_ms: float,
    ) -> MonitoringComponent:
        if summary is None:
            return MonitoringComponent(
                component="usage",
                label="Token与费用账本",
                status=MonitoringState.UNAVAILABLE,
                detail=str(error) if error else "无法读取用量账本",
                latency_ms=latency_ms,
                metadata={"error_type": type(error).__name__ if error else None},
            )
        return MonitoringComponent(
            component="usage",
            label="Token与费用账本",
            status=MonitoringState.HEALTHY,
            detail=(
                f"已记录 {summary.request_count} 次调用，"
                f"累计费用 ¥{summary.total_cost:.9f}"
            ),
            latency_ms=latency_ms,
            metadata={
                "request_count": summary.request_count,
                "total_tokens": summary.total_tokens,
                "total_cost": summary.total_cost,
                "currency": summary.currency,
            },
        )

    @staticmethod
    def _overall_state(
        components: dict[str, MonitoringComponent],
    ) -> MonitoringState:
        states = {item.status for item in components.values()}
        if MonitoringState.UNAVAILABLE in states or MonitoringState.DEGRADED in states:
            return MonitoringState.DEGRADED
        return MonitoringState.HEALTHY

    def _report_error(
        self,
        exc: BaseException,
        details: dict[str, object],
    ) -> None:
        if self.on_error:
            self.on_error(exc, details)

    def _report_check_error_once(
        self,
        component: str,
        exc: BaseException,
    ) -> None:
        signature = f"{type(exc).__name__}:{exc}"
        if self._reported_failures.get(component) == signature:
            return
        self._reported_failures[component] = signature
        self._report_error(
            exc,
            {"component": component, "operation": "passive-health-check"},
        )

    def _initial_snapshot(self) -> MonitoringSnapshot:
        components = {
            "api": MonitoringComponent(
                component="api",
                label="后端API",
                status=MonitoringState.HEALTHY,
                detail="FastAPI进程正常",
            ),
            "repository": MonitoringComponent(
                component="repository",
                label="Elasticsearch",
                status=MonitoringState.UNKNOWN,
                detail="等待后端首次检查",
            ),
            "planner": MonitoringComponent(
                component="planner",
                label="规划模型",
                status=MonitoringState.UNKNOWN,
                detail="等待后端首次检查",
            ),
            "embedding": MonitoringComponent(
                component="embedding",
                label="Embedding模型",
                status=MonitoringState.UNKNOWN,
                detail="等待后端首次检查",
            ),
            "usage": MonitoringComponent(
                component="usage",
                label="Token与费用账本",
                status=MonitoringState.UNKNOWN,
                detail="等待后端首次检查",
            ),
        }
        return MonitoringSnapshot(
            status=MonitoringState.UNKNOWN,
            components=components,
            generated_at=datetime.now(timezone.utc),
        )
