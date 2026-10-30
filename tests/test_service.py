from __future__ import annotations

import unittest

from mechanics_agent.embeddings import DisabledEmbedder
from mechanics_agent.knowledge.memory import InMemoryKnowledgeRepository
from mechanics_agent.models import (
    OverallStatus,
    PlanRequest,
    VerificationRequest,
    VerificationStage,
)
from mechanics_agent.planner import LocalPlanner
from mechanics_agent.seed import load_jsonl_documents
from mechanics_agent.service import MechanicsAgentService
from tests.helpers import ROOT, load_case


class MechanicsAgentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.repository = InMemoryKnowledgeRepository()
        self.service = MechanicsAgentService(
            self.repository,
            LocalPlanner(),
            DisabledEmbedder(),
        )
        await self.service.initialize()
        await self.service.ingest(
            load_jsonl_documents(ROOT / "data" / "seed_knowledge.jsonl")
        )

    async def asyncTearDown(self) -> None:
        await self.service.close()

    async def test_plan_retrieves_knowledge_runs_precheck_and_audits(self) -> None:
        response = await self.service.plan(PlanRequest(case=load_case(), top_k=4))
        self.assertEqual(OverallStatus.PASS, response.precheck.overall)
        self.assertEqual("local-deterministic", response.planner)
        self.assertGreaterEqual(len(response.knowledge_hits), 1)
        self.assertIn("PRE-UNIT-001", response.plan.applicable_rule_ids)
        self.assertIn("POST-EQ-001", response.plan.applicable_rule_ids)
        self.assertEqual(1, len(self.repository.runs))
        self.assertEqual("plan", self.repository.runs[0].event_type)

    async def test_verify_records_audit_evidence(self) -> None:
        request = VerificationRequest(
            case=load_case(),
            stage=VerificationStage.POST,
            evidence={
                "job_status": "COMPLETED",
                "external_force": [0, -10000, 0],
                "reaction_force": [0, 10000, 0],
                "mesh_metric_coarse": 1.0,
                "mesh_metric_fine": 1.0,
                "max_displacement": 1.0,
                "max_equivalent_stress": 100,
                "high_risk_warnings": [],
            },
        )
        summary = await self.service.verify(request)
        self.assertEqual(OverallStatus.PASS, summary.overall)
        self.assertEqual("verify:post", self.repository.runs[-1].event_type)


if __name__ == "__main__":
    unittest.main()

