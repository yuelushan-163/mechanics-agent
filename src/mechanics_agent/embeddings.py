from __future__ import annotations

from typing import Protocol

import httpx

from mechanics_agent.config import Settings
from mechanics_agent.models import ModelUsageStatus
from mechanics_agent.usage import ModelUsageTracker


class EmbeddingError(RuntimeError):
    pass


class Embedder(Protocol):
    @property
    def enabled(self) -> bool: ...

    @property
    def provider_name(self) -> str | None: ...

    @property
    def model_name(self) -> str | None: ...

    async def embed(
        self,
        text: str,
        *,
        operation: str = "embedding",
    ) -> list[float] | None: ...

    async def test_connection(self) -> dict[str, object]: ...

    async def close(self) -> None: ...


class DisabledEmbedder:
    @property
    def enabled(self) -> bool:
        return False

    @property
    def provider_name(self) -> str | None:
        return None

    @property
    def model_name(self) -> str | None:
        return None

    async def embed(
        self,
        text: str,
        *,
        operation: str = "embedding",
    ) -> list[float] | None:
        del text, operation
        return None

    async def test_connection(self) -> dict[str, object]:
        return {
            "status": "not_configured",
            "message": "Embedding服务未配置，当前使用ES全文检索",
        }

    async def close(self) -> None:
        return None


class OpenAICompatibleEmbedder:
    def __init__(
        self,
        settings: Settings,
        *,
        usage_tracker: ModelUsageTracker | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not settings.embedding_base_url or not settings.embedding_model:
            raise ValueError("embedding base URL and model are required")
        self.settings = settings
        self.usage_tracker = usage_tracker
        headers = {"Content-Type": "application/json"}
        if settings.embedding_api_key:
            headers["Authorization"] = f"Bearer {settings.embedding_api_key}"
        self.client = httpx.AsyncClient(
            base_url=settings.embedding_base_url,
            headers=headers,
            timeout=settings.request_timeout_seconds,
            transport=transport,
        )

    @property
    def enabled(self) -> bool:
        return True

    @property
    def provider_name(self) -> str | None:
        return self.settings.embedding_provider

    @property
    def model_name(self) -> str | None:
        return self.settings.embedding_model

    async def embed(
        self,
        text: str,
        *,
        operation: str = "embedding",
    ) -> list[float]:
        started_at = ModelUsageTracker.start_timer()
        request_body: dict[str, object] = {
            "model": self.settings.embedding_model,
            "input": text,
        }
        if self.settings.embedding_send_dimensions:
            request_body["dimensions"] = self.settings.embedding_dims
        try:
            response = await self.client.post(
                "/embeddings",
                json=request_body,
            )
        except httpx.HTTPError as exc:
            if self.usage_tracker:
                await self.usage_tracker.record_response(
                    provider=self.settings.embedding_provider,
                    model=self.settings.embedding_model,
                    operation=operation,
                    response_body=None,
                    status=ModelUsageStatus.ERROR,
                    started_at=started_at,
                    error_type=type(exc).__name__,
                )
            raise EmbeddingError(f"Embedding connection failed: {exc}") from exc
        provider_request_id = (
            response.headers.get("x-siliconcloud-trace-id")
            or response.headers.get("x-request-id")
        )
        try:
            body: object | None = response.json()
        except ValueError:
            body = None
        if response.status_code != 200:
            if self.usage_tracker:
                await self.usage_tracker.record_response(
                    provider=self.settings.embedding_provider,
                    model=self.settings.embedding_model,
                    operation=operation,
                    response_body=body,
                    status=ModelUsageStatus.ERROR,
                    started_at=started_at,
                    http_status=response.status_code,
                    provider_request_id=provider_request_id,
                    error_type=f"HTTP_{response.status_code}",
                )
            raise EmbeddingError(
                f"Embedding endpoint returned HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )
        try:
            if not isinstance(body, dict):
                raise TypeError("response is not a JSON object")
            vector = [float(value) for value in body["data"][0]["embedding"]]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            if self.usage_tracker:
                await self.usage_tracker.record_response(
                    provider=self.settings.embedding_provider,
                    model=self.settings.embedding_model,
                    operation=operation,
                    response_body=body,
                    status=ModelUsageStatus.ERROR,
                    started_at=started_at,
                    http_status=response.status_code,
                    provider_request_id=provider_request_id,
                    error_type="InvalidEmbeddingResponse",
                )
            raise EmbeddingError("Embedding endpoint returned an invalid response") from exc
        if len(vector) != self.settings.embedding_dims:
            if self.usage_tracker:
                await self.usage_tracker.record_response(
                    provider=self.settings.embedding_provider,
                    model=self.settings.embedding_model,
                    operation=operation,
                    response_body=body,
                    status=ModelUsageStatus.ERROR,
                    started_at=started_at,
                    http_status=response.status_code,
                    provider_request_id=provider_request_id,
                    error_type="EmbeddingDimensionMismatch",
                )
            raise EmbeddingError(
                f"Embedding dimension {len(vector)} does not match "
                f"EMBEDDING_DIMS={self.settings.embedding_dims}"
            )
        if self.usage_tracker:
            await self.usage_tracker.record_response(
                provider=self.settings.embedding_provider,
                model=self.settings.embedding_model,
                operation=operation,
                response_body=body,
                status=ModelUsageStatus.SUCCESS,
                started_at=started_at,
                http_status=response.status_code,
                provider_request_id=provider_request_id,
            )
        return vector

    async def test_connection(self) -> dict[str, object]:
        vector = await self.embed(
            "有限元知识库连接测试",
            operation="embedding:connection_test",
        )
        return {
            "status": "ok",
            "provider": self.provider_name,
            "model": self.model_name,
            "dimensions": len(vector),
        }

    async def close(self) -> None:
        await self.client.aclose()


def build_embedder(
    settings: Settings,
    *,
    usage_tracker: ModelUsageTracker | None = None,
) -> Embedder:
    if settings.embedding_base_url and settings.embedding_model:
        if settings.embedding_dims != settings.es_vector_dims:
            raise ValueError("EMBEDDING_DIMS must equal ES_VECTOR_DIMS")
        return OpenAICompatibleEmbedder(
            settings,
            usage_tracker=usage_tracker,
        )
    return DisabledEmbedder()
