from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


def _optional_bool_env(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    app_host: str
    app_port: int
    es_url: str
    es_index_prefix: str
    es_api_key: str | None
    es_username: str | None
    es_password: str | None
    es_verify_certs: bool
    es_vector_dims: int
    es_request_timeout_seconds: float
    mongo_url: str | None
    mongo_database: str
    mongo_username: str | None
    mongo_password: str | None
    mongo_request_timeout_seconds: float
    planner_mode: str
    kimi_api_key: str | None
    kimi_base_url: str
    kimi_model: str
    kimi_thinking_enabled: bool
    kimi_max_tokens: int
    siliconflow_api_key: str | None
    siliconflow_base_url: str
    siliconflow_model: str
    siliconflow_enable_thinking: bool | None
    siliconflow_max_tokens: int
    embedding_base_url: str | None
    embedding_api_key: str | None
    embedding_provider: str
    embedding_model: str | None
    embedding_dims: int
    embedding_send_dimensions: bool
    siliconflow_pricing_model: str
    siliconflow_cached_input_price_per_k: float
    siliconflow_input_price_per_k: float
    siliconflow_output_price_per_k: float
    embedding_pricing_model: str
    embedding_input_price_per_k: float
    monitoring_enabled: bool
    monitoring_interval_seconds: float
    monitoring_timeout_seconds: float
    startup_timeout_seconds: float
    request_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        planner_mode = os.getenv("PLANNER_MODE", "auto").strip().lower()
        if planner_mode not in {"auto", "kimi", "siliconflow", "local"}:
            raise ValueError(
                "PLANNER_MODE must be one of: auto, kimi, siliconflow, local"
            )
        return cls(
            app_host=os.getenv("APP_HOST", "127.0.0.1"),
            app_port=_int_env("APP_PORT", 8000),
            es_url=os.getenv("ES_URL", "http://127.0.0.1:9200").rstrip("/"),
            es_index_prefix=os.getenv("ES_INDEX_PREFIX", "mechanics-agent"),
            es_api_key=os.getenv("ES_API_KEY") or None,
            es_username=os.getenv("ES_USERNAME") or None,
            es_password=os.getenv("ES_PASSWORD") or None,
            es_verify_certs=_bool_env("ES_VERIFY_CERTS", True),
            es_vector_dims=_int_env("ES_VECTOR_DIMS", 1024),
            es_request_timeout_seconds=_float_env(
                "ES_REQUEST_TIMEOUT_SECONDS",
                5.0,
            ),
            mongo_url=(os.getenv("MONGO_URL") or "").rstrip("/") or None,
            mongo_database=os.getenv("MONGO_APP_DATABASE", "mechanics_agent"),
            mongo_username=os.getenv("MONGO_APP_USERNAME") or None,
            mongo_password=os.getenv("MONGO_APP_PASSWORD") or None,
            mongo_request_timeout_seconds=_float_env(
                "MONGO_REQUEST_TIMEOUT_SECONDS",
                5.0,
            ),
            planner_mode=planner_mode,
            kimi_api_key=os.getenv("MOONSHOT_API_KEY") or None,
            kimi_base_url=os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1").rstrip(
                "/"
            ),
            kimi_model=os.getenv("KIMI_MODEL", "kimi-k2.6"),
            kimi_thinking_enabled=_bool_env("KIMI_THINKING_ENABLED", True),
            kimi_max_tokens=_int_env("KIMI_MAX_TOKENS", 16000),
            siliconflow_api_key=os.getenv("SILICONFLOW_API_KEY") or None,
            siliconflow_base_url=os.getenv(
                "SILICONFLOW_BASE_URL",
                "https://api.siliconflow.cn/v1",
            ).rstrip("/"),
            siliconflow_model=os.getenv(
                "SILICONFLOW_MODEL",
                "deepseek-ai/DeepSeek-V4-Flash",
            ),
            siliconflow_enable_thinking=_optional_bool_env(
                "SILICONFLOW_ENABLE_THINKING"
            ),
            siliconflow_max_tokens=_int_env("SILICONFLOW_MAX_TOKENS", 8192),
            embedding_base_url=(os.getenv("EMBEDDING_BASE_URL") or "").rstrip("/") or None,
            embedding_api_key=os.getenv("EMBEDDING_API_KEY") or None,
            embedding_provider=os.getenv(
                "EMBEDDING_PROVIDER",
                "siliconflow",
            ).strip().lower(),
            embedding_model=os.getenv("EMBEDDING_MODEL") or None,
            embedding_dims=_int_env("EMBEDDING_DIMS", 1024),
            embedding_send_dimensions=_bool_env(
                "EMBEDDING_SEND_DIMENSIONS",
                False,
            ),
            siliconflow_pricing_model=os.getenv(
                "SILICONFLOW_PRICING_MODEL",
                "deepseek-ai/DeepSeek-V4-Flash",
            ),
            siliconflow_cached_input_price_per_k=_float_env(
                "SILICONFLOW_CACHED_INPUT_PRICE_PER_K",
                0.000020,
            ),
            siliconflow_input_price_per_k=_float_env(
                "SILICONFLOW_INPUT_PRICE_PER_K",
                0.001000,
            ),
            siliconflow_output_price_per_k=_float_env(
                "SILICONFLOW_OUTPUT_PRICE_PER_K",
                0.002000,
            ),
            embedding_pricing_model=os.getenv(
                "EMBEDDING_PRICING_MODEL",
                "Qwen/Qwen3-Embedding-0.6B",
            ),
            embedding_input_price_per_k=_float_env(
                "EMBEDDING_INPUT_PRICE_PER_K",
                0.000070,
            ),
            monitoring_enabled=_bool_env("MONITORING_ENABLED", True),
            monitoring_interval_seconds=_float_env(
                "MONITORING_INTERVAL_SECONDS",
                30.0,
            ),
            monitoring_timeout_seconds=_float_env(
                "MONITORING_TIMEOUT_SECONDS",
                5.0,
            ),
            startup_timeout_seconds=_float_env(
                "STARTUP_TIMEOUT_SECONDS",
                10.0,
            ),
            request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "120")),
        )

    @property
    def knowledge_index(self) -> str:
        return f"{self.es_index_prefix}-knowledge-v1"

    @property
    def runs_index(self) -> str:
        return f"{self.es_index_prefix}-runs-v1"

    @property
    def usage_index(self) -> str:
        return f"{self.es_index_prefix}-model-usage-v1"
