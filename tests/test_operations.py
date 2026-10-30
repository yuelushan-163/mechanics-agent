from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from mechanics_agent.api import create_app
from mechanics_agent.embeddings import DisabledEmbedder
from mechanics_agent.knowledge.memory import InMemoryKnowledgeRepository
from mechanics_agent.operations import InMemoryOperationsRepository
from mechanics_agent.planner import LocalPlanner


class OperationsApiTests(unittest.TestCase):
    @staticmethod
    def build_app(operations: InMemoryOperationsRepository):
        return create_app(
            repository=InMemoryKnowledgeRepository(),
            planner=LocalPlanner(),
            embedder=DisabledEmbedder(),
            operations_repository=operations,
        )

    def test_user_project_task_and_approval_workflow(self) -> None:
        operations = InMemoryOperationsRepository()
        with TestClient(self.build_app(operations)) as client:
            owner = client.post(
                "/v1/users",
                json={
                    "name": "张工程师",
                    "email": "engineer@example.test",
                    "role": "engineer",
                },
            )
            reviewer = client.post(
                "/v1/users",
                json={"name": "李审核员", "role": "reviewer"},
            )
            self.assertEqual(201, owner.status_code, owner.text)
            self.assertEqual(201, reviewer.status_code, reviewer.text)

            project = client.post(
                "/v1/projects",
                json={
                    "name": "支架线性静力验证",
                    "owner_user_id": owner.json()["user_id"],
                    "description": "首个黄金案例",
                },
            )
            self.assertEqual(201, project.status_code, project.text)

            task = client.post(
                "/v1/tasks",
                json={
                    "project_id": project.json()["project_id"],
                    "title": "确认载荷与约束",
                    "task_type": "planning",
                    "assigned_user_id": owner.json()["user_id"],
                },
            )
            self.assertEqual(201, task.status_code, task.text)
            self.assertEqual("pending", task.json()["status"])

            updated = client.patch(
                f"/v1/tasks/{task.json()['task_id']}/status",
                json={
                    "status": "waiting_approval",
                    "progress": 0.6,
                    "changed_by": owner.json()["user_id"],
                    "comment": "载荷面与支承孔已标记",
                },
            )
            self.assertEqual(200, updated.status_code, updated.text)
            self.assertEqual(2, len(updated.json()["status_history"]))

            approval = client.post(
                "/v1/approvals",
                json={
                    "project_id": project.json()["project_id"],
                    "task_id": task.json()["task_id"],
                    "subject": "批准载荷与边界条件",
                    "requested_by": owner.json()["user_id"],
                    "reviewer_user_id": reviewer.json()["user_id"],
                    "payload": {"load": "5000 N", "support": "two bolt holes"},
                },
            )
            self.assertEqual(201, approval.status_code, approval.text)

            decision = client.patch(
                f"/v1/approvals/{approval.json()['approval_id']}/decision",
                json={
                    "decision": "approved",
                    "decided_by": reviewer.json()["user_id"],
                    "comment": "与图纸一致",
                },
            )
            self.assertEqual(200, decision.status_code, decision.text)
            self.assertEqual("approved", decision.json()["decision"])

            duplicate_decision = client.patch(
                f"/v1/approvals/{approval.json()['approval_id']}/decision",
                json={
                    "decision": "rejected",
                    "decided_by": reviewer.json()["user_id"],
                },
            )
            self.assertEqual(409, duplicate_decision.status_code)

            self.assertEqual(2, len(client.get("/v1/users").json()))
            self.assertEqual(1, len(client.get("/v1/projects").json()))
            self.assertEqual(1, len(client.get("/v1/tasks").json()))
            self.assertEqual(1, len(client.get("/v1/approvals").json()))

    def test_validation_error_is_persisted_without_secret_text(self) -> None:
        operations = InMemoryOperationsRepository()
        with TestClient(self.build_app(operations)) as client:
            response = client.post(
                "/v1/projects",
                json={"name": "missing owner"},
                headers={"X-Request-ID": "mongo-error-test"},
            )
            self.assertEqual(422, response.status_code)
            persisted = client.get(
                "/v1/operations/error-logs?request_id=mongo-error-test"
            )
        self.assertEqual(200, persisted.status_code, persisted.text)
        self.assertEqual(1, len(persisted.json()))
        self.assertEqual("WARNING", persisted.json()[0]["level"])
        self.assertNotIn("password", str(persisted.json()).lower())

    def test_client_error_is_redacted_and_persisted(self) -> None:
        operations = InMemoryOperationsRepository()
        with TestClient(self.build_app(operations)) as client:
            response = client.post(
                "/v1/operations/error-logs/client",
                json={
                    "level": "ERROR",
                    "message": "Authorization: Bearer browser-secret-token",
                    "request_id": "client-error-test",
                    "path": "/v1/cases/plan",
                    "details": {"api_key": "client-key"},
                },
            )
            persisted = client.get(
                "/v1/operations/error-logs?request_id=client-error-test"
            )
        self.assertEqual(201, response.status_code, response.text)
        self.assertEqual(1, len(persisted.json()))
        text = str(persisted.json())
        self.assertNotIn("browser-secret-token", text)
        self.assertNotIn("client-key", text)
        self.assertIn("[REDACTED]", text)


if __name__ == "__main__":
    unittest.main()
