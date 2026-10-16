"""Telecom domain adapter for the existing durable Agent Runtime."""

from __future__ import annotations

import json
import asyncio
import sys
from pathlib import Path
from uuid import UUID

from agent_runtime_platform.checkpoint import SQLiteCheckpointStore
from agent_runtime_platform.backends import LeaseGrant, StaleLeaseWriteError
from agent_runtime_platform.contracts import RunResult
from agent_runtime_platform.runtime import (
    AgentRuntime,
    RuntimeLeaseBusy,
    _ACTIVE_LEASE,
)

from .diagnosis import TelecomPlanner
from .models import IncidentRequest
from .tools import SyntheticTelecomTools


class _DirectSQLiteBackend:
    """Synchronous SQLite calls behind async methods for the Windows sandbox only."""

    def __init__(self, store: SQLiteCheckpointStore) -> None:
        self.store = store

    async def save_checkpoint(self, run_id, step_no, state, *, lease_grant):
        digest = self.store.save_fenced(
            run_id, step_no, state,
            owner_id=lease_grant.owner_id,
            fencing_token=lease_grant.fencing_token,
        )
        if digest is None:
            raise StaleLeaseWriteError(f"stale checkpoint write rejected: {run_id}")
        return digest

    async def load_latest(self, run_id):
        return self.store.load_latest(run_id)

    async def acquire_lease(self, run_id, owner_id, *, ttl_seconds):
        raw = self.store.acquire_lease_grant(
            run_id, owner_id, ttl_seconds=ttl_seconds
        )
        return None if raw is None else LeaseGrant(*raw)

    async def renew_lease(self, run_id, owner_id, *, ttl_seconds, fencing_token):
        return self.store.renew_lease(
            run_id, owner_id, ttl_seconds=ttl_seconds,
            fencing_token=fencing_token,
        )

    async def release_lease(self, run_id, owner_id, *, fencing_token):
        return self.store.release_lease(
            run_id, owner_id, fencing_token=fencing_token
        )

    async def save_tool_trace(self, idempotency_key, trace, *, run_id, lease_grant):
        saved = self.store.save_tool_trace_fenced(
            idempotency_key, trace, run_id=run_id,
            owner_id=lease_grant.owner_id,
            fencing_token=lease_grant.fencing_token,
        )
        if not saved:
            raise StaleLeaseWriteError(f"stale tool trace write rejected: {run_id}")

    async def load_tool_trace(self, idempotency_key):
        return self.store.load_tool_trace(idempotency_key)


class _WindowsSyntheticRuntime(AgentRuntime):
    """Compatibility path for sub-second offline fixtures on this Windows host.

    The shared Runtime heartbeat relies on asyncio timer waits which do not
    complete in the current sandbox.  This class preserves lease acquisition,
    fencing-aware writes, and lease release, but omits heartbeat renewal.  It is
    never selected on Linux and must not be used as production recovery proof.
    """

    async def _with_lease(self, run_id: str, operation):
        lease_grant = await self.backend.acquire_lease(
            run_id, self.owner_id, ttl_seconds=self.lease_ttl_seconds
        )
        if lease_grant is None:
            raise RuntimeLeaseBusy(f"run lease is held by another worker: {run_id}")
        lease_lost = asyncio.Event()
        context_token = _ACTIVE_LEASE.set(lease_grant)
        try:
            return await operation(lease_lost, lease_grant)
        finally:
            try:
                await self.backend.release_lease(
                    run_id,
                    self.owner_id,
                    fencing_token=lease_grant.fencing_token,
                )
            finally:
                _ACTIVE_LEASE.reset(context_token)

    async def _execute_batch(
        self,
        requests,
        *,
        run_id,
        step_no,
        human_confirmed,
        lease_grant,
    ):
        # asyncio.gather also yields through the broken Windows sandbox loop.
        # Sequential execution is limited to deterministic, sub-millisecond
        # local fixtures; Linux continues to exercise the real async batch.
        traces = []
        for index, call in enumerate(requests):
            traces.append(
                await self._execute_one(
                    call,
                    idempotency_key=f"{run_id}:{step_no}:{index}",
                    run_id=run_id,
                    step_no=step_no,
                    tool_index=index,
                    human_confirmed=human_confirmed,
                    lease_grant=lease_grant,
                )
            )
        return traces


class TelecomIncidentRuntimeAdapter:
    """Bind telecom contracts and deterministic tools without copying Runtime code."""

    def __init__(
        self,
        *,
        checkpoint_path: str | Path,
        max_tool_calls: int = 10,
        max_steps: int = 8,
        tool_timeout_seconds: float = 0.2,
        owner_id: str | None = None,
    ) -> None:
        self.checkpoint_path = Path(checkpoint_path)
        self.max_tool_calls = max_tool_calls
        self.max_steps = max_steps
        self.tool_timeout_seconds = tool_timeout_seconds
        self.owner_id = owner_id

    def _runtime(self, incident: IncidentRequest) -> AgentRuntime:
        tools = SyntheticTelecomTools(incident, timeout_seconds=self.tool_timeout_seconds)
        runtime_class = _WindowsSyntheticRuntime if sys.platform == "win32" else AgentRuntime
        kwargs = {
            "planner": TelecomPlanner(),
            "tools": tools.registry(),
            "max_tool_calls": self.max_tool_calls,
            "max_steps": self.max_steps,
            "owner_id": self.owner_id,
        }
        store = SQLiteCheckpointStore(self.checkpoint_path)
        if sys.platform == "win32":
            kwargs["backend"] = _DirectSQLiteBackend(store)
        else:
            kwargs["checkpoints"] = store
        return runtime_class(
            **kwargs,
        )

    async def diagnose(self, request: IncidentRequest | dict, *, task_id: str | None = None) -> RunResult:
        incident = IncidentRequest.model_validate(request)
        payload = json.dumps(incident.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        return await self._runtime(incident).run(task_id=task_id or incident.case_id, request=payload)

    async def resume(self, incident: IncidentRequest | dict, run_id: UUID | str, *, approved: bool, review_message: str | None = None) -> RunResult:
        validated = IncidentRequest.model_validate(incident)
        return await self._runtime(validated).resume(run_id, approved=approved, review_message=review_message)

    async def recover(self, incident: IncidentRequest | dict, run_id: UUID | str) -> RunResult:
        validated = IncidentRequest.model_validate(incident)
        return await self._runtime(validated).recover(run_id)

    async def get(self, incident: IncidentRequest | dict, run_id: UUID | str) -> RunResult:
        validated = IncidentRequest.model_validate(incident)
        return await self._runtime(validated).get(run_id)
