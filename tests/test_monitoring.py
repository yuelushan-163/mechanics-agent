from __future__ import annotations

import unittest
from dataclasses import replace

from mechanics_agent.config import Settings
from mechanics_agent.embeddings import DisabledEmbedder
from mechanics_agent.knowledge.memory import InMemoryKnowledgeRepository
from mechanics_agent.monitoring import BackendMonitor
from mechanics_agent.planner import LocalPlanner


class CountingPlanner(LocalPlanner):
    def __init__(self) -> None:
        self.test_calls = 0

    async def test_connection(self) -> dict[str, object]:
        self.test_calls += 1
        return await super().test_connection()


class CountingEmbedder(DisabledEmbedder):
    def __init__(self) -> None:
        self.test_calls = 0

    async def test_connection(self) -> dict[str, object]:
        self.test_calls += 1
        return await super().test_connection()


class BackendMonitoringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.repository = InMemoryKnowledgeRepository()
        self.planner = CountingPlanner()
        self.embedder = CountingEmbedder()
        self.monitor = BackendMonitor(
            replace(
                Settings.from_env(),
                monitoring_enabled=False,
                monitoring_timeout_seconds=1,
            ),
            self.repository,
            self.planner,
            self.embedder,
        )

    async def test_passive_refresh_never_calls_paid_model_probes(self) -> None:
        snapshot = await self.monitor.refresh()

        self.assertEqual("healthy", snapshot.status)
        self.assertEqual("healthy", snapshot.components["repository"].status)
        self.assertEqual("not_configured", snapshot.components["planner"].status)
        self.assertEqual("not_configured", snapshot.components["embedding"].status)
        self.assertEqual(0, self.planner.test_calls)
        self.assertEqual(0, self.embedder.test_calls)

    async def test_active_probe_runs_only_requested_backend_target(self) -> None:
        result = await self.monitor.active_probe(["planner"])

        self.assertIn("planner", result.results)
        self.assertNotIn("embedding", result.results)
        self.assertEqual(1, self.planner.test_calls)
        self.assertEqual(0, self.embedder.test_calls)


if __name__ == "__main__":
    unittest.main()
