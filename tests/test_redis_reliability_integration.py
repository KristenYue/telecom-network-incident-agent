"""Real Redis pending/reclaim/dead-letter flow for the dedicated CI service."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from telecom_incident_agent.jobs import RedisIncidentJobQueue


REDIS_URL = os.getenv("TELECOM_REDIS_INTEGRATION_URL")


@pytest.mark.skipif(not REDIS_URL, reason="requires a real Redis service")
def test_pending_job_is_reclaimed_and_delivery_limit_routes_to_dead_letter():
    async def exercise() -> None:
        assert REDIS_URL is not None
        suffix = uuid4().hex
        stream = f"test:telecom:jobs:{suffix}"
        group = f"test-workers-{suffix}"
        dead = f"{stream}:dead-letter"
        first = RedisIncidentJobQueue(
            REDIS_URL,
            stream_key=stream,
            group=group,
            dead_letter_key=dead,
            consumer_id="worker-a",
            visibility_timeout_seconds=0,
            max_deliveries=2,
        )
        second = RedisIncidentJobQueue(
            REDIS_URL,
            stream_key=stream,
            group=group,
            dead_letter_key=dead,
            consumer_id="worker-b",
            visibility_timeout_seconds=0,
            max_deliveries=2,
        )
        try:
            await first.enqueue({"kind": "diagnose", "incident_id": "INC-RECLAIM"})
            attempt_one = await first.dequeue(timeout_seconds=1)
            assert attempt_one is not None and attempt_one.deliveries == 1
            await first.fail(attempt_one, "worker-a crashed")

            attempt_two = await second.dequeue(timeout_seconds=1)
            assert attempt_two is not None
            assert attempt_two.message_id == attempt_one.message_id
            assert attempt_two.deliveries == 2
            await second.fail(attempt_two, "worker-b failed")

            assert await first.dequeue(timeout_seconds=0) is None
            assert await first.client.xlen(dead) == 1
            assert (await first.client.xpending(stream, group))["pending"] == 0
        finally:
            await first.client.delete(stream, dead, first.error_hash_key)
            await first.close()
            await second.close()

    asyncio.run(exercise())
