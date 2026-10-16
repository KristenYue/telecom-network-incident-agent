"""Application service coordinating API records and the shared Runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_runtime_platform.contracts import RunResult

from .adapter import TelecomIncidentRuntimeAdapter
from .jobs import IncidentJobQueue, RedisIncidentJobQueue
from .models import IncidentRequest
from .repository import (
    IncidentRepository,
    IncidentRepositoryProtocol,
    PostgresIncidentRepository,
)


class IncidentService:
    def __init__(
        self,
        data_dir: str | Path,
        *,
        database_url: str | None = None,
        queue_url: str | None = None,
        repository: IncidentRepositoryProtocol | None = None,
        queue: IncidentJobQueue | None = None,
    ) -> None:
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.database_url = database_url
        self.repository = repository or (
            PostgresIncidentRepository(database_url)
            if database_url
            else IncidentRepository(root / "incidents.sqlite3")
        )
        self.queue = queue or (RedisIncidentJobQueue(queue_url) if queue_url else None)
        self.checkpoint_path = root / "runtime.sqlite3"

    @staticmethod
    def _serialize(result: RunResult) -> dict:
        return result.model_dump(mode="json")

    async def create(self, request: IncidentRequest) -> dict:
        incident_id = f"INC-{uuid4().hex[:12].upper()}"
        if self.queue is not None:
            self.repository.create_pending(incident_id, request)
            try:
                await self.queue.enqueue({"kind": "diagnose", "incident_id": incident_id})
            except Exception:
                self.repository.update_status(incident_id, "enqueue_failed")
                raise
            return self.repository.get(incident_id)
        return await self._diagnose(incident_id, request)

    async def _diagnose(self, incident_id: str, request: IncidentRequest) -> dict:
        adapter = TelecomIncidentRuntimeAdapter(
            checkpoint_path=self.checkpoint_path,
            database_url=self.database_url,
        )
        result = await adapter.diagnose(request, task_id=incident_id)
        serialized = self._serialize(result)
        self.repository.save(incident_id, request, serialized)
        return self.repository.get(incident_id)

    def get(self, incident_id: str) -> dict:
        return self.repository.get(incident_id)

    def review(self, incident_id: str, *, approved: bool, reviewer: str, message: str | None) -> dict:
        review_id = self.repository.add_review(incident_id, approved=approved, reviewer=reviewer, message=message)
        return {"review_id": review_id, "incident_id": incident_id, "approved": approved, "reviewer": reviewer, "message": message}

    async def resume(self, incident_id: str) -> dict:
        record = self.repository.get(incident_id)
        review = self.repository.latest_review(incident_id)
        if self.queue is not None:
            self.repository.update_status(incident_id, "queued_resume")
            try:
                await self.queue.enqueue({"kind": "resume", "incident_id": incident_id})
            except Exception:
                self.repository.update_status(incident_id, "enqueue_failed")
                raise
            return self.repository.get(incident_id)
        return await self._resume_record(record, review)

    async def _resume_record(self, record: dict[str, Any], review: dict[str, Any]) -> dict:
        incident_id = record["incident_id"]
        request = IncidentRequest.model_validate(record["request"])
        adapter = TelecomIncidentRuntimeAdapter(
            checkpoint_path=self.checkpoint_path,
            database_url=self.database_url,
        )
        result = await adapter.resume(request, record["run_id"], approved=review["approved"], review_message=f"{review['reviewer']}: {review['message'] or ''}".strip())
        self.repository.save(incident_id, request, self._serialize(result))
        return self.repository.get(incident_id)

    async def process_job(self, job: dict[str, Any]) -> dict:
        incident_id = str(job.get("incident_id", ""))
        kind = job.get("kind")
        record = self.repository.get(incident_id)
        try:
            if kind == "diagnose":
                self.repository.update_status(incident_id, "running")
                request = IncidentRequest.model_validate(record["request"])
                return await self._diagnose(incident_id, request)
            if kind == "resume":
                self.repository.update_status(incident_id, "resuming")
                review = self.repository.latest_review(incident_id)
                return await self._resume_record(record, review)
            raise ValueError(f"unsupported incident job kind: {kind}")
        except Exception:
            self.repository.update_status(incident_id, "worker_failed")
            raise

    async def ready(self) -> dict[str, bool]:
        checks = {"repository": self.repository.ping()}
        if self.queue is not None:
            checks["queue"] = await self.queue.ping()
        return checks

    def trace(self, incident_id: str) -> dict:
        record = self.repository.get(incident_id)
        result = record["result"] or {}
        return {
            "incident_id": incident_id,
            "run_id": record["run_id"],
            "runtime_status": record["runtime_status"],
            "steps": result.get("steps", []),
            "errors": result.get("errors", []),
            "pending_action": result.get("pending_action"),
            "tool_call_count": result.get("tool_call_count", 0),
            "domain_result": result.get("result"),
            "data_boundary": "synthetic",
        }
