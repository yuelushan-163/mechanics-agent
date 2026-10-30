from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from mechanics_agent.api import create_app
from mechanics_agent.config import Settings
from mechanics_agent.embeddings import DisabledEmbedder
from mechanics_agent.knowledge.memory import InMemoryKnowledgeRepository
from mechanics_agent.models import ModelUsageStatus
from mechanics_agent.planner import LocalPlanner
from mechanics_agent.seed import load_jsonl_documents
from mechanics_agent.usage import (
    ParsedTokenUsage,
    PricingCatalog,
    build_usage_record,
)
from tests.helpers import ROOT, load_case


class FailingHealthRepository(InMemoryKnowledgeRepository):
    async def health(self) -> dict[str, object]:
        raise RuntimeError("Elasticsearch password=top-secret is unavailable")


class FailingStartupRepository(InMemoryKnowledgeRepository):
    async def ensure_indices(self) -> None:
        raise RuntimeError("index initialization failed")


class ApiContractTests(unittest.TestCase):
    @staticmethod
    def build_app(
        repository: InMemoryKnowledgeRepository | None = None,
    ):
        return create_app(
            repository=repository or InMemoryKnowledgeRepository(),
            planner=LocalPlanner(),
            embedder=DisabledEmbedder(),
        )

    def test_plan_endpoint_returns_precheck_and_plan(self) -> None:
        repository = InMemoryKnowledgeRepository()
        for document in load_jsonl_documents(ROOT / "data" / "seed_knowledge.jsonl"):
            repository.documents[document.doc_id] = document
        app = self.build_app(repository)
        with TestClient(app) as client:
            response = client.post(
                "/v1/cases/plan",
                json={"case": load_case().model_dump(mode="json"), "top_k": 4},
            )
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual("pass", body["precheck"]["overall"])
        self.assertEqual("beam-demo-001", body["plan"]["case_id"])
        self.assertEqual("local-deterministic", body["planner"])

    def test_user_and_admin_frontends_and_assets_are_served(self) -> None:
        with TestClient(self.build_app()) as client:
            user_page = client.get("/")
            cases_page = client.get("/cases")
            new_analysis_page = client.get("/analysis/new")
            result_page = client.get("/analysis/result")
            admin_page = client.get("/admin")
            admin_page_with_slash = client.get("/admin/")
            user_script = client.get("/assets/user.js")
            admin_script = client.get("/assets/app.js")
        self.assertEqual(200, user_page.status_code)
        self.assertIn("text/html", user_page.headers["content-type"])
        self.assertIn('data-app="user-workbench"', user_page.text)
        self.assertIn("有限元仿真工作台", user_page.text)
        self.assertNotIn('href="/admin"', user_page.text)
        self.assertNotIn("开发管理台", user_script.text)
        self.assertEqual(200, cases_page.status_code)
        self.assertIn('data-page="cases"', cases_page.text)
        self.assertEqual(200, new_analysis_page.status_code)
        self.assertIn('data-page="analysis-new"', new_analysis_page.text)
        self.assertIn('id="caseForm"', new_analysis_page.text)
        self.assertEqual(200, result_page.status_code)
        self.assertIn('data-page="analysis-result"', result_page.text)
        self.assertEqual(200, admin_page.status_code)
        self.assertIn('data-app="developer-console"', admin_page.text)
        self.assertIn("Mechanics Agent 开发管理台", admin_page.text)
        self.assertEqual(200, admin_page_with_slash.status_code)
        self.assertNotEqual(user_page.text, admin_page.text)
        self.assertEqual(200, user_script.status_code)
        self.assertIn("/v1/cases/plan", user_script.text)
        self.assertEqual(200, admin_script.status_code)
        self.assertIn("pollServerLogs", admin_script.text)

    def test_frontend_routes_are_not_exposed_as_api_operations(self) -> None:
        with TestClient(self.build_app()) as client:
            paths = client.get("/openapi.json").json()["paths"]
        self.assertNotIn("/", paths)
        self.assertNotIn("/admin", paths)
        self.assertNotIn("/admin/", paths)
        self.assertNotIn("/cases", paths)
        self.assertNotIn("/analysis/new", paths)
        self.assertNotIn("/analysis/result", paths)
        self.assertIn("/health", paths)
        self.assertIn("/v1/cases/plan", paths)

    def test_planner_connection_test_does_not_require_repository_health(self) -> None:
        app = self.build_app(FailingHealthRepository())
        with TestClient(app) as client:
            response = client.post("/v1/debug/planner/test")
        self.assertEqual(200, response.status_code)
        self.assertEqual("local-deterministic", response.json()["planner"])

    def test_validation_failure_is_visible_in_debug_logs(self) -> None:
        with TestClient(self.build_app()) as client:
            response = client.post(
                "/v1/knowledge/search",
                json={},
                headers={"X-Request-ID": "validation-test"},
            )
            logs = client.get("/v1/debug/logs").json()["entries"]
        self.assertEqual(422, response.status_code)
        self.assertEqual("validation-test", response.json()["request_id"])
        entry = next(item for item in logs if item["request_id"] == "validation-test")
        self.assertEqual("WARNING", entry["level"])
        self.assertEqual(422, entry["status_code"])
        self.assertTrue(entry["details"]["errors"])

    def test_backend_monitor_reports_repository_failure_without_hiding_api(self) -> None:
        app = self.build_app(FailingHealthRepository())
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/v1/monitoring/status?refresh=true",
                headers={"X-Request-ID": "health-failure"},
            )
            logs = client.get("/v1/debug/logs").json()["entries"]
        self.assertEqual(200, response.status_code)
        self.assertEqual("degraded", response.json()["status"])
        self.assertEqual(
            "unavailable",
            response.json()["components"]["repository"]["status"],
        )
        entry = next(item for item in logs if item["method"] == "MONITOR")
        self.assertEqual("ERROR", entry["level"])
        self.assertIn("RuntimeError", entry["traceback"])
        self.assertNotIn("top-secret", str(entry))

    def test_startup_failure_keeps_admin_frontend_available(self) -> None:
        app = self.build_app(FailingStartupRepository())
        with TestClient(app, raise_server_exceptions=False) as client:
            user_page = client.get("/")
            admin_page = client.get("/admin")
            logs = client.get("/v1/debug/logs").json()["entries"]
        self.assertEqual(200, user_page.status_code)
        self.assertEqual(200, admin_page.status_code)
        self.assertIn("开发管理台", admin_page.text)
        entry = next(item for item in logs if item["method"] == "STARTUP")
        self.assertEqual("ERROR", entry["level"])
        self.assertIn("index initialization failed", entry["message"])

    def test_usage_summary_and_pricing_endpoints(self) -> None:
        repository = InMemoryKnowledgeRepository()
        settings = Settings.from_env()
        price = PricingCatalog.from_settings(settings).get(
            "siliconflow",
            "Qwen/Qwen3-Embedding-0.6B",
        )
        repository.model_usage.append(
            build_usage_record(
                provider="siliconflow",
                model="Qwen/Qwen3-Embedding-0.6B",
                operation="embedding:search",
                usage=ParsedTokenUsage(2000, 0, 0, 2000, True),
                price=price,
                status=ModelUsageStatus.SUCCESS,
                request_id="usage-api-test",
                provider_request_id=None,
                http_status=200,
                latency_ms=10,
                error_type=None,
            )
        )
        with TestClient(self.build_app(repository)) as client:
            summary = client.get("/v1/usage/summary")
            events = client.get("/v1/usage/events?operation=embedding:search")
            pricing = client.get("/v1/usage/pricing")

        self.assertEqual(200, summary.status_code)
        self.assertEqual(2000, summary.json()["total_tokens"])
        self.assertAlmostEqual(0.00014, summary.json()["total_cost"], places=12)
        self.assertEqual(1, len(events.json()))
        self.assertEqual(2, len(pricing.json()["models"]))


if __name__ == "__main__":
    unittest.main()
