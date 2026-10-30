from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Any, Callable, Protocol
from uuid import uuid4

from mechanics_agent.config import Settings
from mechanics_agent.models import (
    ModelUsageRecord,
    ModelUsageStatus,
    ModelUsageSummary,
    ModelUsageSummaryRow,
)


_REQUEST_ID: ContextVar[str | None] = ContextVar(
    "mechanics_agent_usage_request_id",
    default=None,
)


def set_usage_request_id(request_id: str) -> Token[str | None]:
    return _REQUEST_ID.set(request_id)


def reset_usage_request_id(token: Token[str | None]) -> None:
    _REQUEST_ID.reset(token)


class ModelUsageStore(Protocol):
    async def record_model_usage(self, record: ModelUsageRecord) -> None: ...


@dataclass(frozen=True, slots=True)
class ModelPrice:
    provider: str
    model: str
    input_per_k_tokens: Decimal
    cached_input_per_k_tokens: Decimal
    output_per_k_tokens: Decimal
    currency: str = "CNY"
    source: str = "configured"

    @property
    def model_key(self) -> str:
        return f"{self.provider}|{self.model}"


class PricingCatalog:
    def __init__(self, prices: list[ModelPrice]) -> None:
        self._prices = {price.model_key: price for price in prices}

    @classmethod
    def from_settings(cls, settings: Settings) -> "PricingCatalog":
        source = "用户提供的硅基流动价格截图（2026-07-31）"
        return cls(
            [
                ModelPrice(
                    provider="siliconflow",
                    model=settings.siliconflow_pricing_model,
                    input_per_k_tokens=Decimal(
                        str(settings.siliconflow_input_price_per_k)
                    ),
                    cached_input_per_k_tokens=Decimal(
                        str(settings.siliconflow_cached_input_price_per_k)
                    ),
                    output_per_k_tokens=Decimal(
                        str(settings.siliconflow_output_price_per_k)
                    ),
                    source=source,
                ),
                ModelPrice(
                    provider="siliconflow",
                    model=settings.embedding_pricing_model,
                    input_per_k_tokens=Decimal(
                        str(settings.embedding_input_price_per_k)
                    ),
                    cached_input_per_k_tokens=Decimal("0"),
                    output_per_k_tokens=Decimal("0"),
                    source=source,
                ),
            ]
        )

    def get(self, provider: str, model: str) -> ModelPrice | None:
        return self._prices.get(f"{provider}|{model}")

    def as_dicts(self) -> list[dict[str, object]]:
        return [
            {
                "provider": price.provider,
                "model": price.model,
                "currency": price.currency,
                "unit_tokens": 1000,
                "input_per_k_tokens": float(price.input_per_k_tokens),
                "cached_input_per_k_tokens": float(
                    price.cached_input_per_k_tokens
                ),
                "output_per_k_tokens": float(price.output_per_k_tokens),
                "source": price.source,
            }
            for price in sorted(
                self._prices.values(),
                key=lambda item: (item.provider, item.model),
            )
        ]


@dataclass(frozen=True, slots=True)
class ParsedTokenUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    total_tokens: int
    usage_reported: bool

    @property
    def uncached_input_tokens(self) -> int:
        return max(self.input_tokens - self.cached_input_tokens, 0)


UsageRecordErrorHandler = Callable[[BaseException, dict[str, object]], None]


class ModelUsageTracker:
    def __init__(
        self,
        store: ModelUsageStore,
        pricing: PricingCatalog,
        *,
        on_record_error: UsageRecordErrorHandler | None = None,
    ) -> None:
        self.store = store
        self.pricing = pricing
        self.on_record_error = on_record_error

    @staticmethod
    def start_timer() -> float:
        return perf_counter()

    async def record_response(
        self,
        *,
        provider: str,
        model: str,
        operation: str,
        response_body: object | None,
        status: ModelUsageStatus,
        started_at: float,
        http_status: int | None = None,
        provider_request_id: str | None = None,
        error_type: str | None = None,
    ) -> ModelUsageRecord:
        usage = parse_token_usage(response_body)
        price = self.pricing.get(provider, model)
        record = build_usage_record(
            provider=provider,
            model=model,
            operation=operation,
            usage=usage,
            price=price,
            status=status,
            request_id=_REQUEST_ID.get(),
            provider_request_id=provider_request_id,
            http_status=http_status,
            latency_ms=max((perf_counter() - started_at) * 1000, 0.0),
            error_type=error_type,
        )
        try:
            await self.store.record_model_usage(record)
        except Exception as exc:
            if self.on_record_error:
                self.on_record_error(
                    exc,
                    {
                        "provider": provider,
                        "model": model,
                        "operation": operation,
                        "usage_id": record.usage_id,
                    },
                )
        return record


def parse_token_usage(response_body: object | None) -> ParsedTokenUsage:
    if not isinstance(response_body, dict):
        return ParsedTokenUsage(0, 0, 0, 0, False)
    raw_usage = response_body.get("usage")
    if not isinstance(raw_usage, dict):
        return ParsedTokenUsage(0, 0, 0, 0, False)

    input_tokens = _first_nonnegative_int(
        raw_usage,
        "prompt_tokens",
        "input_tokens",
    )
    output_tokens = _first_nonnegative_int(
        raw_usage,
        "completion_tokens",
        "output_tokens",
    )
    total_tokens = _first_nonnegative_int(raw_usage, "total_tokens")

    details = raw_usage.get("prompt_tokens_details")
    cached_input_tokens = 0
    if isinstance(details, dict):
        cached_input_tokens = _first_nonnegative_int(
            details,
            "cached_tokens",
            "cache_read_tokens",
        )
    if cached_input_tokens == 0:
        cached_input_tokens = _first_nonnegative_int(
            raw_usage,
            "cached_input_tokens",
            "cache_read_input_tokens",
            "prompt_cache_hit_tokens",
        )

    cache_miss_tokens = _first_nonnegative_int(
        raw_usage,
        "prompt_cache_miss_tokens",
    )
    if input_tokens == 0 and (cached_input_tokens or cache_miss_tokens):
        input_tokens = cached_input_tokens + cache_miss_tokens
    cached_input_tokens = min(cached_input_tokens, input_tokens)
    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens

    usage_reported = any(
        key in raw_usage
        for key in (
            "prompt_tokens",
            "input_tokens",
            "completion_tokens",
            "output_tokens",
            "total_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
        )
    )
    return ParsedTokenUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        usage_reported=usage_reported,
    )


def build_usage_record(
    *,
    provider: str,
    model: str,
    operation: str,
    usage: ParsedTokenUsage,
    price: ModelPrice | None,
    status: ModelUsageStatus,
    request_id: str | None,
    provider_request_id: str | None,
    http_status: int | None,
    latency_ms: float | None,
    error_type: str | None,
) -> ModelUsageRecord:
    input_rate = price.input_per_k_tokens if price else Decimal("0")
    cached_rate = price.cached_input_per_k_tokens if price else Decimal("0")
    output_rate = price.output_per_k_tokens if price else Decimal("0")

    input_cost = _cost(usage.uncached_input_tokens, input_rate)
    cached_input_cost = _cost(usage.cached_input_tokens, cached_rate)
    output_cost = _cost(usage.output_tokens, output_rate)
    total_cost = input_cost + cached_input_cost + output_cost

    return ModelUsageRecord(
        usage_id=str(uuid4()),
        provider=provider,
        model=model,
        model_key=f"{provider}|{model}",
        operation=operation,
        request_id=request_id,
        provider_request_id=provider_request_id,
        status=status,
        http_status=http_status,
        input_tokens=usage.input_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        uncached_input_tokens=usage.uncached_input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        usage_reported=usage.usage_reported,
        pricing_found=price is not None,
        currency=price.currency if price else "CNY",
        input_rate_per_k_tokens=float(input_rate),
        cached_input_rate_per_k_tokens=float(cached_rate),
        output_rate_per_k_tokens=float(output_rate),
        input_cost=float(input_cost),
        cached_input_cost=float(cached_input_cost),
        output_cost=float(output_cost),
        total_cost=float(total_cost),
        latency_ms=round(latency_ms, 3) if latency_ms is not None else None,
        error_type=error_type,
    )


def summarize_usage_records(records: list[ModelUsageRecord]) -> ModelUsageSummary:
    grouped: dict[tuple[str, str], list[ModelUsageRecord]] = {}
    for record in records:
        grouped.setdefault((record.provider, record.model), []).append(record)

    rows = [
        ModelUsageSummaryRow(
            provider=provider,
            model=model,
            request_count=len(items),
            success_count=sum(
                item.status == ModelUsageStatus.SUCCESS for item in items
            ),
            error_count=sum(item.status == ModelUsageStatus.ERROR for item in items),
            usage_missing_count=sum(not item.usage_reported for item in items),
            pricing_missing_count=sum(not item.pricing_found for item in items),
            input_tokens=sum(item.input_tokens for item in items),
            cached_input_tokens=sum(item.cached_input_tokens for item in items),
            uncached_input_tokens=sum(
                item.uncached_input_tokens for item in items
            ),
            output_tokens=sum(item.output_tokens for item in items),
            total_tokens=sum(item.total_tokens for item in items),
            total_cost=_round_cost(sum(item.total_cost for item in items)),
            currency="CNY",
        )
        for (provider, model), items in sorted(grouped.items())
    ]
    return ModelUsageSummary(
        rows=rows,
        request_count=len(records),
        input_tokens=sum(item.input_tokens for item in records),
        cached_input_tokens=sum(item.cached_input_tokens for item in records),
        uncached_input_tokens=sum(item.uncached_input_tokens for item in records),
        output_tokens=sum(item.output_tokens for item in records),
        total_tokens=sum(item.total_tokens for item in records),
        total_cost=_round_cost(sum(item.total_cost for item in records)),
        currency="CNY",
    )


def _cost(tokens: int, price_per_k: Decimal) -> Decimal:
    return (
        Decimal(tokens) * price_per_k / Decimal(1000)
    ).quantize(Decimal("0.000000000001"))


def _round_cost(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.000000000001")))


def _first_nonnegative_int(mapping: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return 0
