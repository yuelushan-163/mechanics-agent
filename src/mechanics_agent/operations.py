from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, Protocol

from mechanics_agent.config import Settings
from mechanics_agent.models import (
    ApprovalCreate,
    ApprovalDecision,
    ApprovalDecisionUpdate,
    ApprovalRecord,
    PersistedErrorLog,
    ProjectCreate,
    ProjectRecord,
    TaskCreate,
    TaskRecord,
    TaskStatus,
    TaskStatusEvent,
    TaskStatusUpdate,
    UserCreate,
    UserRecord,
)


class OperationsRepositoryError(RuntimeError):
    pass


class OperationsNotFoundError(OperationsRepositoryError):
    pass


class OperationsConflictError(OperationsRepositoryError):
    pass


class OperationsRepository(Protocol):
    async def initialize(self) -> None: ...
    async def health(self) -> dict[str, object]: ...
    async def close(self) -> None: ...

    async def create_user(self, payload: UserCreate) -> UserRecord: ...
    async def list_users(self, limit: int = 100) -> list[UserRecord]: ...
    async def get_user(self, user_id: str) -> UserRecord: ...

    async def create_project(self, payload: ProjectCreate) -> ProjectRecord: ...
    async def list_projects(
        self, *, owner_user_id: str | None = None, limit: int = 100
    ) -> list[ProjectRecord]: ...
    async def get_project(self, project_id: str) -> ProjectRecord: ...

    async def create_task(self, payload: TaskCreate) -> TaskRecord: ...
    async def list_tasks(
        self,
        *,
        project_id: str | None = None,
        status: TaskStatus | None = None,
        limit: int = 200,
    ) -> list[TaskRecord]: ...
    async def get_task(self, task_id: str) -> TaskRecord: ...
    async def update_task_status(
        self, task_id: str, payload: TaskStatusUpdate
    ) -> TaskRecord: ...

    async def create_approval(self, payload: ApprovalCreate) -> ApprovalRecord: ...
    async def list_approvals(
        self,
        *,
        project_id: str | None = None,
        task_id: str | None = None,
        decision: ApprovalDecision | None = None,
        limit: int = 200,
    ) -> list[ApprovalRecord]: ...
    async def decide_approval(
        self, approval_id: str, payload: ApprovalDecisionUpdate
    ) -> ApprovalRecord: ...

    async def record_error_log(self, entry: dict[str, Any]) -> PersistedErrorLog: ...
    async def list_error_logs(
        self,
        *,
        level: str | None = None,
        request_id: str | None = None,
        limit: int = 200,
    ) -> list[PersistedErrorLog]: ...


class InMemoryOperationsRepository:
    def __init__(self) -> None:
        self.users: dict[str, UserRecord] = {}
        self.projects: dict[str, ProjectRecord] = {}
        self.tasks: dict[str, TaskRecord] = {}
        self.approvals: dict[str, ApprovalRecord] = {}
        self.error_logs: list[PersistedErrorLog] = []

    async def initialize(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        return {
            "status": "ok",
            "backend": "memory",
            "collections": 5,
        }

    async def close(self) -> None:
        return None

    async def create_user(self, payload: UserCreate) -> UserRecord:
        if payload.email and any(item.email == payload.email for item in self.users.values()):
            raise OperationsConflictError("用户邮箱已存在")
        record = UserRecord(**payload.model_dump(mode="python"))
        self.users[record.user_id] = record
        return record

    async def list_users(self, limit: int = 100) -> list[UserRecord]:
        return list(self.users.values())[-limit:]

    async def get_user(self, user_id: str) -> UserRecord:
        return self._required(self.users, user_id, "用户")

    async def create_project(self, payload: ProjectCreate) -> ProjectRecord:
        await self.get_user(payload.owner_user_id)
        record = ProjectRecord(**payload.model_dump(mode="python"))
        self.projects[record.project_id] = record
        return record

    async def list_projects(
        self, *, owner_user_id: str | None = None, limit: int = 100
    ) -> list[ProjectRecord]:
        values = self.projects.values()
        if owner_user_id:
            values = [item for item in values if item.owner_user_id == owner_user_id]
        return list(values)[-limit:]

    async def get_project(self, project_id: str) -> ProjectRecord:
        return self._required(self.projects, project_id, "项目")

    async def create_task(self, payload: TaskCreate) -> TaskRecord:
        await self.get_project(payload.project_id)
        if payload.assigned_user_id:
            await self.get_user(payload.assigned_user_id)
        initial_event = TaskStatusEvent(status=TaskStatus.PENDING)
        record = TaskRecord(
            **payload.model_dump(mode="python"),
            status_history=[initial_event],
        )
        self.tasks[record.task_id] = record
        return record

    async def list_tasks(
        self,
        *,
        project_id: str | None = None,
        status: TaskStatus | None = None,
        limit: int = 200,
    ) -> list[TaskRecord]:
        values: Iterable[TaskRecord] = self.tasks.values()
        if project_id:
            values = [item for item in values if item.project_id == project_id]
        if status:
            values = [item for item in values if item.status == status]
        return list(values)[-limit:]

    async def get_task(self, task_id: str) -> TaskRecord:
        return self._required(self.tasks, task_id, "任务")

    async def update_task_status(
        self, task_id: str, payload: TaskStatusUpdate
    ) -> TaskRecord:
        current = await self.get_task(task_id)
        event = TaskStatusEvent(
            status=payload.status,
            changed_by=payload.changed_by,
            comment=payload.comment,
        )
        progress = payload.progress
        if progress is None:
            progress = 1.0 if payload.status == TaskStatus.COMPLETED else current.progress
        updated = current.model_copy(
            update={
                "status": payload.status,
                "progress": progress,
                "status_history": [*current.status_history, event],
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.tasks[task_id] = updated
        return updated

    async def create_approval(self, payload: ApprovalCreate) -> ApprovalRecord:
        await self.get_project(payload.project_id)
        task = await self.get_task(payload.task_id)
        if task.project_id != payload.project_id:
            raise OperationsConflictError("审批任务不属于指定项目")
        await self.get_user(payload.requested_by)
        if payload.reviewer_user_id:
            await self.get_user(payload.reviewer_user_id)
        record = ApprovalRecord(**payload.model_dump(mode="python"))
        self.approvals[record.approval_id] = record
        return record

    async def list_approvals(
        self,
        *,
        project_id: str | None = None,
        task_id: str | None = None,
        decision: ApprovalDecision | None = None,
        limit: int = 200,
    ) -> list[ApprovalRecord]:
        values: Iterable[ApprovalRecord] = self.approvals.values()
        if project_id:
            values = [item for item in values if item.project_id == project_id]
        if task_id:
            values = [item for item in values if item.task_id == task_id]
        if decision:
            values = [item for item in values if item.decision == decision]
        return list(values)[-limit:]

    async def decide_approval(
        self, approval_id: str, payload: ApprovalDecisionUpdate
    ) -> ApprovalRecord:
        current = self._required(self.approvals, approval_id, "审批")
        if current.decision != ApprovalDecision.PENDING:
            raise OperationsConflictError("审批已经作出决定，不能覆盖")
        await self.get_user(payload.decided_by)
        now = datetime.now(timezone.utc)
        updated = current.model_copy(
            update={
                "decision": payload.decision,
                "decided_by": payload.decided_by,
                "decision_comment": payload.comment,
                "decided_at": now,
                "updated_at": now,
            }
        )
        self.approvals[approval_id] = updated
        return updated

    async def record_error_log(self, entry: dict[str, Any]) -> PersistedErrorLog:
        record = PersistedErrorLog.model_validate(entry)
        self.error_logs.append(record)
        return record

    async def list_error_logs(
        self,
        *,
        level: str | None = None,
        request_id: str | None = None,
        limit: int = 200,
    ) -> list[PersistedErrorLog]:
        values: Iterable[PersistedErrorLog] = self.error_logs
        if level:
            values = [item for item in values if item.level == level.upper()]
        if request_id:
            values = [item for item in values if item.request_id == request_id]
        return list(values)[-limit:]

    @staticmethod
    def _required(records: dict[str, Any], record_id: str, label: str):
        try:
            return records[record_id]
        except KeyError as exc:
            raise OperationsNotFoundError(f"{label}不存在：{record_id}") from exc


class MongoOperationsRepository:
    def __init__(self, settings: Settings) -> None:
        if not settings.mongo_url:
            raise ValueError("MONGO_URL is required")
        from motor.motor_asyncio import AsyncIOMotorClient

        self.settings = settings
        self.client = AsyncIOMotorClient(
            settings.mongo_url,
            username=settings.mongo_username,
            password=settings.mongo_password,
            authSource=settings.mongo_database,
            serverSelectionTimeoutMS=int(settings.mongo_request_timeout_seconds * 1000),
            connectTimeoutMS=int(settings.mongo_request_timeout_seconds * 1000),
            socketTimeoutMS=int(settings.mongo_request_timeout_seconds * 1000),
            uuidRepresentation="standard",
        )
        self.database = self.client[settings.mongo_database]

    async def initialize(self) -> None:
        await self.database.command("ping")
        await self.database.users.create_index("user_id", unique=True)
        await self.database.users.create_index("email", unique=True, sparse=True)
        await self.database.projects.create_index("project_id", unique=True)
        await self.database.projects.create_index([("owner_user_id", 1), ("updated_at", -1)])
        await self.database.tasks.create_index("task_id", unique=True)
        await self.database.tasks.create_index([("project_id", 1), ("status", 1)])
        await self.database.approvals.create_index("approval_id", unique=True)
        await self.database.approvals.create_index([("task_id", 1), ("decision", 1)])
        await self.database.error_logs.create_index([("timestamp", -1)])
        await self.database.error_logs.create_index("request_id")
        await self.database.error_logs.create_index([("level", 1), ("timestamp", -1)])

    async def health(self) -> dict[str, object]:
        await self.database.command("ping")
        return {
            "status": "ok",
            "backend": "mongodb",
            "database": self.settings.mongo_database,
            "collections": 5,
        }

    async def close(self) -> None:
        self.client.close()

    async def create_user(self, payload: UserCreate) -> UserRecord:
        from pymongo.errors import DuplicateKeyError

        record = UserRecord(**payload.model_dump(mode="python"))
        try:
            await self.database.users.insert_one(record.model_dump(mode="python"))
        except DuplicateKeyError as exc:
            raise OperationsConflictError("用户ID或邮箱已存在") from exc
        return record

    async def list_users(self, limit: int = 100) -> list[UserRecord]:
        docs = await self.database.users.find({}).sort("created_at", -1).limit(limit).to_list()
        return [UserRecord.model_validate(_without_mongo_id(item)) for item in docs]

    async def get_user(self, user_id: str) -> UserRecord:
        return UserRecord.model_validate(
            await self._find_required("users", {"user_id": user_id}, "用户", user_id)
        )

    async def create_project(self, payload: ProjectCreate) -> ProjectRecord:
        await self.get_user(payload.owner_user_id)
        record = ProjectRecord(**payload.model_dump(mode="python"))
        await self.database.projects.insert_one(record.model_dump(mode="python"))
        return record

    async def list_projects(
        self, *, owner_user_id: str | None = None, limit: int = 100
    ) -> list[ProjectRecord]:
        query = {"owner_user_id": owner_user_id} if owner_user_id else {}
        docs = await self.database.projects.find(query).sort("updated_at", -1).limit(limit).to_list()
        return [ProjectRecord.model_validate(_without_mongo_id(item)) for item in docs]

    async def get_project(self, project_id: str) -> ProjectRecord:
        return ProjectRecord.model_validate(
            await self._find_required(
                "projects", {"project_id": project_id}, "项目", project_id
            )
        )

    async def create_task(self, payload: TaskCreate) -> TaskRecord:
        await self.get_project(payload.project_id)
        if payload.assigned_user_id:
            await self.get_user(payload.assigned_user_id)
        record = TaskRecord(
            **payload.model_dump(mode="python"),
            status_history=[TaskStatusEvent(status=TaskStatus.PENDING)],
        )
        await self.database.tasks.insert_one(record.model_dump(mode="python"))
        return record

    async def list_tasks(
        self,
        *,
        project_id: str | None = None,
        status: TaskStatus | None = None,
        limit: int = 200,
    ) -> list[TaskRecord]:
        query: dict[str, Any] = {}
        if project_id:
            query["project_id"] = project_id
        if status:
            query["status"] = status.value
        docs = await self.database.tasks.find(query).sort("updated_at", -1).limit(limit).to_list()
        return [TaskRecord.model_validate(_without_mongo_id(item)) for item in docs]

    async def get_task(self, task_id: str) -> TaskRecord:
        return TaskRecord.model_validate(
            await self._find_required("tasks", {"task_id": task_id}, "任务", task_id)
        )

    async def update_task_status(
        self, task_id: str, payload: TaskStatusUpdate
    ) -> TaskRecord:
        current = await self.get_task(task_id)
        event = TaskStatusEvent(
            status=payload.status,
            changed_by=payload.changed_by,
            comment=payload.comment,
        )
        progress = payload.progress
        if progress is None:
            progress = 1.0 if payload.status == TaskStatus.COMPLETED else current.progress
        now = datetime.now(timezone.utc)
        result = await self.database.tasks.find_one_and_update(
            {"task_id": task_id},
            {
                "$set": {
                    "status": payload.status.value,
                    "progress": progress,
                    "updated_at": now,
                },
                "$push": {"status_history": event.model_dump(mode="python")},
            },
            return_document=True,
        )
        return TaskRecord.model_validate(_without_mongo_id(result))

    async def create_approval(self, payload: ApprovalCreate) -> ApprovalRecord:
        await self.get_project(payload.project_id)
        task = await self.get_task(payload.task_id)
        if task.project_id != payload.project_id:
            raise OperationsConflictError("审批任务不属于指定项目")
        await self.get_user(payload.requested_by)
        if payload.reviewer_user_id:
            await self.get_user(payload.reviewer_user_id)
        record = ApprovalRecord(**payload.model_dump(mode="python"))
        await self.database.approvals.insert_one(record.model_dump(mode="python"))
        return record

    async def list_approvals(
        self,
        *,
        project_id: str | None = None,
        task_id: str | None = None,
        decision: ApprovalDecision | None = None,
        limit: int = 200,
    ) -> list[ApprovalRecord]:
        query: dict[str, Any] = {}
        if project_id:
            query["project_id"] = project_id
        if task_id:
            query["task_id"] = task_id
        if decision:
            query["decision"] = decision.value
        docs = (
            await self.database.approvals.find(query)
            .sort("updated_at", -1)
            .limit(limit)
            .to_list()
        )
        return [ApprovalRecord.model_validate(_without_mongo_id(item)) for item in docs]

    async def decide_approval(
        self, approval_id: str, payload: ApprovalDecisionUpdate
    ) -> ApprovalRecord:
        await self.get_user(payload.decided_by)
        now = datetime.now(timezone.utc)
        result = await self.database.approvals.find_one_and_update(
            {
                "approval_id": approval_id,
                "decision": ApprovalDecision.PENDING.value,
            },
            {
                "$set": {
                    "decision": payload.decision.value,
                    "decided_by": payload.decided_by,
                    "decision_comment": payload.comment,
                    "decided_at": now,
                    "updated_at": now,
                }
            },
            return_document=True,
        )
        if result is None:
            exists = await self.database.approvals.find_one({"approval_id": approval_id})
            if exists is None:
                raise OperationsNotFoundError(f"审批不存在：{approval_id}")
            raise OperationsConflictError("审批已经作出决定，不能覆盖")
        return ApprovalRecord.model_validate(_without_mongo_id(result))

    async def record_error_log(self, entry: dict[str, Any]) -> PersistedErrorLog:
        record = PersistedErrorLog.model_validate(entry)
        await self.database.error_logs.insert_one(record.model_dump(mode="python"))
        return record

    async def list_error_logs(
        self,
        *,
        level: str | None = None,
        request_id: str | None = None,
        limit: int = 200,
    ) -> list[PersistedErrorLog]:
        query: dict[str, Any] = {}
        if level:
            query["level"] = level.upper()
        if request_id:
            query["request_id"] = request_id
        docs = await self.database.error_logs.find(query).sort("timestamp", -1).limit(limit).to_list()
        docs.reverse()
        return [PersistedErrorLog.model_validate(_without_mongo_id(item)) for item in docs]

    async def _find_required(
        self,
        collection_name: str,
        query: dict[str, Any],
        label: str,
        record_id: str,
    ) -> dict[str, Any]:
        item = await self.database[collection_name].find_one(query)
        if item is None:
            raise OperationsNotFoundError(f"{label}不存在：{record_id}")
        return _without_mongo_id(item)


def build_operations_repository(settings: Settings) -> OperationsRepository:
    if settings.mongo_url:
        return MongoOperationsRepository(settings)
    return InMemoryOperationsRepository()


def _without_mongo_id(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "_id"}
