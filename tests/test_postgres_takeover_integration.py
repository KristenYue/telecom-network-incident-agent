"""Real PostgreSQL lease takeover check, executed by the dedicated CI job."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest

from agent_runtime_platform.backends import StaleLeaseWriteError
from agent_runtime_platform.postgres import PostgresRuntimeBackend
from telecom_incident_agent.device_tasks import DeviceTasks
from telecom_incident_agent.repository import PostgresIncidentRepository


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_DSN = os.getenv("TELECOM_POSTGRES_INTEGRATION_DSN")


@pytest.mark.skipif(not POSTGRES_DSN, reason="requires a real PostgreSQL service")
def test_postgres_task_outbox_and_device_queue_transactions(optical_incident):
    psycopg = pytest.importorskip("psycopg")
    schema = "device_test_" + uuid4().hex
    with psycopg.connect(POSTGRES_DSN, autocommit=True) as admin:
        admin.execute(psycopg.sql.SQL("CREATE SCHEMA {}").format(psycopg.sql.Identifier(schema)))
        try:
            dsn = psycopg.conninfo.make_conninfo(POSTGRES_DSN, options=f"-c search_path={schema}")
            repository = PostgresIncidentRepository(dsn)
            repository.create_pending("INC-OUTBOX", optical_incident, dispatch=True)
            mirrored = PostgresIncidentRepository(dsn)
            assert mirrored.get("INC-OUTBOX")["runtime_status"] == "queued"
            [event] = mirrored.pending_dispatches()
            assert event["incident_id"] == "INC-OUTBOX"
            mirrored.finish_dispatch(event["event_id"])
            assert repository.pending_dispatches() == []

            queue = DeviceTasks(repository._connect, postgres=True, port=18765, writes=False)
            task = queue.submit("status", False)
            worker = DeviceTasks(mirrored._connect, postgres=True, port=18765, writes=False)
            worker.lease_seconds = 0
            claim = worker.claim()
            assert claim["id"] == task["id"]
            assert queue.claim() is None
            assert not worker.finish(claim, "completed", {"stale": True})
            assert queue.get(task["id"])["status"] == "outcome_unknown"
        finally:
            admin.execute(psycopg.sql.SQL("DROP SCHEMA {} CASCADE").format(psycopg.sql.Identifier(schema)))


async def _apply_runtime_schema(dsn: str) -> None:
    psycopg = pytest.importorskip("psycopg")
    schema = (ROOT / "deploy" / "postgres" / "init.sql").read_text(encoding="utf-8")
    # This fixture contains simple DDL, but its header comment also contains a
    # semicolon. Remove line comments before splitting statements so prose is
    # never sent to PostgreSQL as SQL.
    schema = "\n".join(
        line for line in schema.splitlines() if not line.lstrip().startswith("--")
    )
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        for statement in schema.split(";"):
            if statement.strip():
                await connection.execute(statement)
        await connection.commit()


@pytest.mark.skipif(not POSTGRES_DSN, reason="requires TELECOM_POSTGRES_INTEGRATION_DSN and a real PostgreSQL service")
def test_postgres_expired_lease_can_be_taken_over_and_stale_writer_is_fenced():
    async def exercise() -> None:
        assert POSTGRES_DSN is not None
        await _apply_runtime_schema(POSTGRES_DSN)
        run_id = str(uuid4())
        worker_a = PostgresRuntimeBackend(POSTGRES_DSN)
        worker_b = PostgresRuntimeBackend(POSTGRES_DSN)
        first = await worker_a.acquire_lease(run_id, "worker-a", ttl_seconds=0.05)
        assert first is not None and first.fencing_token == 1
        assert await worker_b.acquire_lease(run_id, "worker-b", ttl_seconds=0.05) is None
        await asyncio.sleep(0.12)
        second = await worker_b.acquire_lease(run_id, "worker-b", ttl_seconds=1)
        assert second is not None and second.fencing_token == 2
        with pytest.raises(StaleLeaseWriteError, match="stale checkpoint"):
            await worker_a.save_checkpoint(run_id, 0, {"owner": "worker-a"}, lease_grant=first)
        state = {"owner": "worker-b", "status": "taken_over"}
        await worker_b.save_checkpoint(run_id, 0, state, lease_grant=second)
        assert await worker_b.load_latest(run_id) == state
        assert await worker_b.release_lease(run_id, "worker-b", fencing_token=second.fencing_token) is True
    asyncio.run(exercise())
