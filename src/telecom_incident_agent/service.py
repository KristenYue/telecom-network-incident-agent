"""Application service coordinating API records and the shared Runtime."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from agent_runtime_platform.contracts import RunResult

from .adapter import TelecomIncidentRuntimeAdapter
from .models import IncidentRequest
from .repository import IncidentRepository


class IncidentService:
    def __init__(self, data_dir: str | Path) -> None:
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.repository = IncidentRepository(root / "incidents.sqlite3")
        self.checkpoint_path = root / "runtime.sqlite3"

    @staticmethod
    def _serialize(result: RunResult) -> dict:
        return result.model_dump(mode="json")

    async def create(self, request: IncidentRequest) -> dict:
        incident_id = f"INC-{uuid4().hex[:12].upper()}"
        adapter = TelecomIncidentRuntimeAdapter(checkpoint_path=self.checkpoint_path)
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
        request = IncidentRequest.model_validate(record["request"])
        adapter = TelecomIncidentRuntimeAdapter(checkpoint_path=self.checkpoint_path)
        result = await adapter.resume(request, record["run_id"], approved=review["approved"], review_message=f"{review['reviewer']}: {review['message'] or ''}".strip())
        self.repository.save(incident_id, request, self._serialize(result))
        return self.repository.get(incident_id)

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
