from __future__ import annotations

import json
import unittest
from dataclasses import replace

import httpx

from mechanics_agent.config import Settings
from mechanics_agent.embeddings import OpenAICompatibleEmbedder
from mechanics_agent.knowledge.memory import InMemoryKnowledgeRepository
from mechanics_agent.models import ModelUsageStatus
from mechanics_agent.planner import SiliconFlowPlanner
from mechanics_agent.usage import (
    ModelUsageTracker,
    ParsedTokenUsage,
    PricingCatalog,
    build_usage_record,
    parse_token_usage,
    reset_usage_request_id,
    set_usage_request_id,
)
from tests.helpers import load_case


def _valid_plan_response() -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "case_id": "ignored",
                            "summary": "测试计划",
                            "assumptions": [],
                            "missing_inputs": [],
                            "cad_actions": [],
                            "fea_actions": [],
                            "applicable_rule_ids": [],
                            "risk_flags": [],
                            "approval_required": [],
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ],
        "usage": {
            "prompt_tokens": 1500,
            "completion_tokens": 200,
            "total_tokens": 1700,
            "prompt_tokens_details": {"cached_tokens": 500},
        },
    }


class ModelUsageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = Settings.from_env()
        self.repository = InMemoryKnowledgeRepository()
        self.tracker = ModelUsageTracker(
            self.repository,
            PricingCatalog.from_settings(self.settings),
        )

    def test_cached_tokens_are_not_charged_again_as_regular_input(self) -> None:
        usage = parse_token_usage(_valid_plan_response())
        price = PricingCatalog.from_settings(self.settings).get(
            "siliconflow",
            "deepseek-ai/DeepSeek-V4-Flash",
        )
        record = build_usage_record(
            provider="siliconflow",
            model="deepseek-ai/DeepSeek-V4-Flash",
            operation="plan",
            usage=usage,
            price=price,
            status=ModelUsageStatus.SUCCESS,
            request_id="req-001",
            provider_request_id="provider-001",
            http_status=200,
            latency_ms=10,
            error_type=None,
        )

        self.assertEqual(1500, record.input_tokens)
        self.assertEqual(500, record.cached_input_tokens)
        self.assertEqual(1000, record.uncached_input_tokens)
        self.assertAlmostEqual(0.001, record.input_cost, places=12)
        self.assertAlmostEqual(0.00001, record.cached_input_cost, places=12)
        self.assertAlmostEqual(0.0004, record.output_cost, places=12)
        self.assertAlmostEqual(0.00141, record.total_cost, places=12)

    def test_embedding_price_uses_input_tokens_only(self) -> None:
        price = PricingCatalog.from_settings(self.settings).get(
            "siliconflow",
            "Qwen/Qwen3-Embedding-0.6B",
        )
        record = build_usage_record(
            provider="siliconflow",
            model="Qwen/Qwen3-Embedding-0.6B",
            operation="embedding:search",
            usage=ParsedTokenUsage(2000, 0, 0, 2000, True),
            price=price,
            status=ModelUsageStatus.SUCCESS,
            request_id=None,
            provider_request_id=None,
            http_status=200,
            latency_ms=5,
            error_type=None,
        )
        self.assertAlmostEqual(0.00014, record.total_cost, places=12)

    def test_unknown_model_records_tokens_without_inventing_a_price(self) -> None:
        record = build_usage_record(
            provider="siliconflow",
            model="unknown/model",
            operation="plan",
            usage=ParsedTokenUsage(100, 0, 20, 120, True),
            price=None,
            status=ModelUsageStatus.SUCCESS,
            request_id=None,
            provider_request_id=None,
            http_status=200,
            latency_ms=5,
            error_type=None,
        )
        self.assertFalse(record.pricing_found)
        self.assertEqual(120, record.total_tokens)
        self.assertEqual(0, record.total_cost)

    async def test_planner_records_provider_usage_and_request_id(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"x-siliconcloud-trace-id": "sf-usage-001"},
                json=_valid_plan_response(),
            )

        settings = replace(
            self.settings,
            siliconflow_api_key="test-secret",
            siliconflow_model="deepseek-ai/DeepSeek-V4-Flash",
        )
        planner = SiliconFlowPlanner(
            settings,
            usage_tracker=self.tracker,
            transport=httpx.MockTransport(handler),
        )
        request_token = set_usage_request_id("api-request-001")
        try:
            await planner.plan(load_case(), [], [])
        finally:
            reset_usage_request_id(request_token)
            await planner.close()

        self.assertEqual(1, len(self.repository.model_usage))
        record = self.repository.model_usage[0]
        self.assertEqual("api-request-001", record.request_id)
        self.assertEqual("sf-usage-001", record.provider_request_id)
        self.assertEqual("plan", record.operation)
        self.assertAlmostEqual(0.00141, record.total_cost, places=12)

    async def test_embedding_client_records_qwen_usage(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            self.assertEqual("Qwen/Qwen3-Embedding-0.6B", body["model"])
            self.assertEqual(3, body["dimensions"])
            return httpx.Response(
                200,
                json={
                    "data": [{"embedding": [0.1, 0.2, 0.3]}],
                    "usage": {"prompt_tokens": 2000, "total_tokens": 2000},
                },
            )

        settings = replace(
            self.settings,
            embedding_base_url="https://api.siliconflow.test/v1",
            embedding_api_key="test-secret",
            embedding_provider="siliconflow",
            embedding_model="Qwen/Qwen3-Embedding-0.6B",
            embedding_dims=3,
            embedding_send_dimensions=True,
            es_vector_dims=3,
        )
        embedder = OpenAICompatibleEmbedder(
            settings,
            usage_tracker=self.tracker,
            transport=httpx.MockTransport(handler),
        )
        try:
            vector = await embedder.embed(
                "网格收敛",
                operation="embedding:search",
            )
        finally:
            await embedder.close()

        self.assertEqual([0.1, 0.2, 0.3], vector)
        record = self.repository.model_usage[0]
        self.assertEqual("Qwen/Qwen3-Embedding-0.6B", record.model)
        self.assertEqual("embedding:search", record.operation)
        self.assertAlmostEqual(0.00014, record.total_cost, places=12)


if __name__ == "__main__":
    unittest.main()
