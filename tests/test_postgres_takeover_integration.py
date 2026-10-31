"""Real PostgreSQL lease takeover check, executed by the dedicated CI job."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest

from agent_runtime_platform.backends import StaleLeaseWriteError
from agent_runtime_platform.postgres import PostgresRuntimeBackend


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_DSN = os.getenv("TELECOM_POSTGRES_INTEGRATION_DSN")


async def _apply_runtime_schema(dsn: str) -> None:
    psycopg = pytest.importorskip("psycopg")
    schema = (ROOT / "deploy" / "postgres" / "init.sql").read_text(encoding="utf-8")
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
