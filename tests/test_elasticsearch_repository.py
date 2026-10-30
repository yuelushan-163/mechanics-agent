from __future__ import annotations

import json
import unittest
from dataclasses import replace

import httpx

from mechanics_agent.config import Settings
from mechanics_agent.knowledge.elasticsearch import (
    ElasticsearchKnowledgeRepository,
    ElasticsearchRepositoryError,
)


class ElasticsearchRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_vector_search_uses_filters_without_requiring_lexical_match(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"hits": {"hits": []}})

        settings = replace(
            Settings.from_env(),
            es_url="https://es.test",
            es_vector_dims=3,
        )
        repository = ElasticsearchKnowledgeRepository(
            settings, transport=httpx.MockTransport(handler)
        )
        try:
            hits = await repository.search(
                "等效说法也应命中",
                analysis_type="linear_static",
                query_vector=[0.1, 0.2, 0.3],
            )
        finally:
            await repository.close()

        self.assertEqual([], hits)
        script_score = captured["body"]["query"]["script_score"]
        bool_query = script_score["query"]["bool"]
        self.assertNotIn("must", bool_query)
        self.assertIn("should", bool_query)
        self.assertIn("cosineSimilarity", script_score["script"]["source"])

    async def test_transport_error_is_reported_as_repository_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        settings = replace(Settings.from_env(), es_url="https://es.test")
        repository = ElasticsearchKnowledgeRepository(
            settings,
            transport=httpx.MockTransport(handler),
        )
        try:
            with self.assertRaisesRegex(
                ElasticsearchRepositoryError,
                "checking Elasticsearch health",
            ):
                await repository.health()
        finally:
            await repository.close()

    async def test_usage_summary_is_grouped_by_provider_and_model(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "aggregations": {
                        "by_model": {
                            "buckets": [
                                {
                                    "key": (
                                        "siliconflow|"
                                        "deepseek-ai/DeepSeek-V4-Flash"
                                    ),
                                    "doc_count": 2,
                                    "successes": {"doc_count": 1},
                                    "errors": {"doc_count": 1},
                                    "usage_missing": {"doc_count": 1},
                                    "pricing_missing": {"doc_count": 0},
                                    "input_tokens": {"value": 1500},
                                    "cached_input_tokens": {"value": 500},
                                    "uncached_input_tokens": {"value": 1000},
                                    "output_tokens": {"value": 200},
                                    "total_tokens": {"value": 1700},
                                    "total_cost": {"value": 0.00141},
                                }
                            ]
                        }
                    }
                },
            )

        settings = replace(Settings.from_env(), es_url="https://es.test")
        repository = ElasticsearchKnowledgeRepository(
            settings,
            transport=httpx.MockTransport(handler),
        )
        try:
            summary = await repository.summarize_model_usage(
                provider="siliconflow",
                model="deepseek-ai/DeepSeek-V4-Flash",
            )
        finally:
            await repository.close()

        self.assertTrue(
            str(captured["url"]).endswith(
                "/mechanics-agent-model-usage-v1/_search"
            )
        )
        filters = captured["body"]["query"]["bool"]["filter"]
        self.assertIn({"term": {"provider": "siliconflow"}}, filters)
        self.assertEqual(2, summary.request_count)
        self.assertEqual(1, summary.rows[0].error_count)
        self.assertAlmostEqual(0.00141, summary.total_cost, places=12)


if __name__ == "__main__":
    unittest.main()
