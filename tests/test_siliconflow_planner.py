from __future__ import annotations

import json
import unittest
from dataclasses import replace

import httpx

from mechanics_agent.config import Settings
from mechanics_agent.planner import (
    PlannerError,
    SiliconFlowPlanner,
    build_planner,
)
from tests.helpers import load_case


def _plan_response() -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "case_id": "model-must-not-control-this",
                            "summary": "DeepSeek测试计划",
                            "assumptions": [],
                            "missing_inputs": [],
                            "cad_actions": ["建立参数化模型"],
                            "fea_actions": ["创建静力分析步"],
                            "applicable_rule_ids": ["MODEL-INVENTED-RULE"],
                            "risk_flags": [],
                            "approval_required": ["工程师审核"],
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }


class SiliconFlowPlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_deepseek_flash_uses_siliconflow_chat_contract(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["authorization"] = request.headers["Authorization"]
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json=_plan_response())

        settings = replace(
            Settings.from_env(),
            planner_mode="siliconflow",
            siliconflow_api_key="test-secret",
            siliconflow_base_url="https://api.siliconflow.test/v1",
            siliconflow_model="deepseek-ai/DeepSeek-V4-Flash",
            siliconflow_enable_thinking=None,
        )
        planner = SiliconFlowPlanner(
            settings,
            transport=httpx.MockTransport(handler),
        )
        try:
            plan = await planner.plan(load_case(), [], [])
        finally:
            await planner.close()

        self.assertEqual(
            "https://api.siliconflow.test/v1/chat/completions",
            captured["url"],
        )
        self.assertEqual("Bearer test-secret", captured["authorization"])
        body = captured["body"]
        self.assertEqual("deepseek-ai/DeepSeek-V4-Flash", body["model"])
        self.assertEqual({"type": "json_object"}, body["response_format"])
        self.assertNotIn("enable_thinking", body)
        self.assertEqual("beam-demo-001", plan.case_id)
        self.assertEqual([], plan.applicable_rule_ids)
        self.assertEqual(
            "siliconflow:deepseek-ai/DeepSeek-V4-Flash",
            planner.name,
        )

    async def test_optional_thinking_flag_is_forwarded_only_when_configured(
        self,
    ) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json=_plan_response())

        settings = replace(
            Settings.from_env(),
            siliconflow_api_key="test-secret",
            siliconflow_enable_thinking=True,
        )
        planner = SiliconFlowPlanner(
            settings,
            transport=httpx.MockTransport(handler),
        )
        try:
            await planner.plan(load_case(), [], [])
        finally:
            await planner.close()

        self.assertIs(True, captured["body"]["enable_thinking"])

    async def test_single_approval_flag_is_repaired_and_keeps_safety_review(
        self,
    ) -> None:
        response = _plan_response()
        model_payload = json.loads(
            response["choices"][0]["message"]["content"]
        )
        model_payload["approval_required"] = "是"
        response["choices"][0]["message"]["content"] = json.dumps(
            model_payload,
            ensure_ascii=False,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response)

        settings = replace(
            Settings.from_env(),
            siliconflow_api_key="test-secret",
        )
        planner = SiliconFlowPlanner(
            settings,
            transport=httpx.MockTransport(handler),
        )
        try:
            plan = await planner.plan(load_case(), [], [])
        finally:
            await planner.close()

        self.assertIn("模型标记该计划需要工程师审核", plan.approval_required)
        self.assertIn("正式设计结论由工程师审核", plan.approval_required)

    async def test_required_token_inside_approval_list_is_humanized(self) -> None:
        response = _plan_response()
        model_payload = json.loads(
            response["choices"][0]["message"]["content"]
        )
        model_payload["approval_required"] = ["required"]
        response["choices"][0]["message"]["content"] = json.dumps(
            model_payload,
            ensure_ascii=False,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response)

        settings = replace(
            Settings.from_env(),
            siliconflow_api_key="test-secret",
        )
        planner = SiliconFlowPlanner(
            settings,
            transport=httpx.MockTransport(handler),
        )
        try:
            plan = await planner.plan(load_case(), [], [])
        finally:
            await planner.close()

        self.assertNotIn("required", plan.approval_required)
        self.assertIn("模型标记该计划需要工程师审核", plan.approval_required)

    async def test_connection_check_returns_provider_trace_id(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                headers={"x-siliconcloud-trace-id": "sf-trace-001"},
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"status":"ok","message":"规划模型连接成功"}'
                                )
                            }
                        }
                    ]
                },
            )

        settings = replace(
            Settings.from_env(),
            siliconflow_api_key="test-secret",
            siliconflow_model="deepseek-ai/DeepSeek-V4-Flash",
        )
        planner = SiliconFlowPlanner(
            settings,
            transport=httpx.MockTransport(handler),
        )
        try:
            result = await planner.test_connection()
        finally:
            await planner.close()

        body = captured["body"]
        self.assertEqual(256, body["max_tokens"])
        self.assertEqual({"type": "json_object"}, body["response_format"])
        self.assertEqual("sf-trace-001", result["provider_trace_id"])
        self.assertEqual(
            "siliconflow:deepseek-ai/DeepSeek-V4-Flash",
            result["planner"],
        )

    async def test_transport_failure_is_reported_as_planner_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        settings = replace(
            Settings.from_env(),
            siliconflow_api_key="test-secret",
        )
        planner = SiliconFlowPlanner(
            settings,
            transport=httpx.MockTransport(handler),
        )
        try:
            with self.assertRaisesRegex(
                PlannerError,
                "SiliconFlow connection failed",
            ):
                await planner.plan(load_case(), [], [])
        finally:
            await planner.close()

    async def test_builder_selects_siliconflow_mode(self) -> None:
        settings = replace(
            Settings.from_env(),
            planner_mode="siliconflow",
            siliconflow_api_key="test-secret",
        )
        planner = build_planner(settings)
        try:
            self.assertIsInstance(planner, SiliconFlowPlanner)
        finally:
            await planner.close()


if __name__ == "__main__":
    unittest.main()
