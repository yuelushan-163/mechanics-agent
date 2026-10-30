from __future__ import annotations

import json
import unittest
from dataclasses import replace

import httpx

from mechanics_agent.config import Settings
from mechanics_agent.models import VerificationStage
from mechanics_agent.planner import KimiPlanner
from mechanics_agent.seed import load_jsonl_documents
from tests.helpers import ROOT, load_case


class KimiPlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_kimi_plan_is_validated_and_rule_ids_are_server_controlled(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "case_id": "wrong-id",
                                        "summary": "测试计划",
                                        "assumptions": [],
                                        "missing_inputs": [],
                                        "cad_actions": ["建立模型"],
                                        "fea_actions": ["提交作业"],
                                        "applicable_rule_ids": ["HALLUCINATED"],
                                        "risk_flags": [],
                                        "approval_required": ["工程师审核"],
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                },
            )

        settings = replace(
            Settings.from_env(),
            kimi_api_key="test-secret",
            kimi_base_url="https://kimi.test/v1",
            kimi_model="kimi-k2.6",
        )
        planner = KimiPlanner(settings, transport=httpx.MockTransport(handler))
        documents = load_jsonl_documents(ROOT / "data" / "seed_knowledge.jsonl")
        rules = [
            (document.doc_id, document.rule)
            for document in documents
            if document.rule is not None
            and document.rule.stage in {VerificationStage.PRE, VerificationStage.POST}
        ]
        try:
            plan = await planner.plan(load_case(), [], rules)
        finally:
            await planner.close()

        self.assertEqual("beam-demo-001", plan.case_id)
        self.assertNotIn("HALLUCINATED", plan.applicable_rule_ids)
        self.assertEqual(
            {rule.rule_id for _, rule in rules},
            set(plan.applicable_rule_ids),
        )
        request_body = captured["body"]
        self.assertEqual({"type": "json_object"}, request_body["response_format"])
        self.assertEqual({"type": "enabled"}, request_body["thinking"])


if __name__ == "__main__":
    unittest.main()

