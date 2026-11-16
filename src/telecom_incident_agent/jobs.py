"""Acknowledged Redis Stream transport for incident jobs."""

from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4


STREAM_KEY = "telecom:incident-jobs:v2"
CONSUMER_GROUP = "telecom-runtime-workers:v2"
DEAD_LETTER_KEY = "telecom:incident-jobs:v2:dead-letter"


@dataclass(frozen=True)
class ClaimedJob:
    message_id: str
    payload: dict[str, Any]
    deliveries: int


class IncidentJobQueue(Protocol):
    async def enqueue(self, job: dict[str, Any]) -> str: ...
    async def dequeue(self, *, timeout_seconds: int = 5) -> ClaimedJob | None: ...
    async def ack(self, claimed: ClaimedJob) -> None: ...
    async def fail(self, claimed: ClaimedJob, error: str) -> None: ...
    async def ping(self) -> bool: ...
    async def close(self) -> None: ...


class RedisIncidentJobQueue:
    """Redis Streams queue with acknowledgement, reclaim and dead-letter flow.

    Jobs remain in the consumer group's pending-entry list until ``ack``. If a
    worker disappears, another consumer reclaims the entry after the visibility
    timeout. Entries exceeding ``max_deliveries`` are moved to a dead-letter
    stream together with their last recorded error.
    """

    def __init__(
        self,
        url: str,
        *,
        stream_key: str = STREAM_KEY,
        group: str = CONSUMER_GROUP,
        dead_letter_key: str = DEAD_LETTER_KEY,
        error_hash_key: str | None = None,
        consumer_id: str | None = None,
        visibility_timeout_seconds: float = 30.0,
        max_deliveries: int = 3,
        client: Any | None = None,
    ) -> None:
        if not url.strip():
            raise ValueError("Redis URL must not be blank")
        if visibility_timeout_seconds < 0:
            raise ValueError("visibility timeout must be non-negative")
        if max_deliveries < 1:
            raise ValueError("max deliveries must be positive")
        if client is None:
            try:
                from redis.asyncio import Redis
            except ImportError as exc:  # pragma: no cover - deploy optional dependency
                raise RuntimeError("Redis jobs require the deploy extra") from exc
            client = Redis.from_url(url, decode_responses=True)
        self.client = client
        self.stream_key = stream_key
        self.group = group
        self.dead_letter_key = dead_letter_key
        self.error_hash_key = error_hash_key or f"{stream_key}:last-error"
        self.consumer_id = consumer_id or (
            f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"
        )
        self.visibility_timeout_ms = int(visibility_timeout_seconds * 1000)
        self.max_deliveries = max_deliveries
        self._group_ready = False

    async def _ensure_group(self) -> None:
        if self._group_ready:
            return
        try:
            await self.client.xgroup_create(
                self.stream_key, self.group, id="0-0", mkstream=True
            )
        except Exception as error:
            if "BUSYGROUP" not in str(error):
                raise
        self._group_ready = True

    async def enqueue(self, job: dict[str, Any]) -> str:
        if not isinstance(job, dict):
            raise TypeError("incident job must be an object")
        payload = json.dumps(job, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        message_id = await self.client.xadd(self.stream_key, {"payload": payload})
        return str(message_id)

    async def dequeue(self, *, timeout_seconds: int = 5) -> ClaimedJob | None:
        await self._ensure_group()
        reclaimed = await self._reclaim_one()
        if reclaimed is not None:
            return reclaimed
        response = await self.client.xreadgroup(
            self.group,
            self.consumer_id,
            {self.stream_key: ">"},
            count=1,
            block=max(0, int(timeout_seconds * 1000)),
        )
        messages = self._stream_messages(response)
        if not messages:
            return None
        message_id, fields = messages[0]
        return await self._decode_or_dead_letter(str(message_id), fields, deliveries=1)

    async def _reclaim_one(self) -> ClaimedJob | None:
        response = await self.client.xautoclaim(
            self.stream_key,
            self.group,
            self.consumer_id,
            min_idle_time=self.visibility_timeout_ms,
            start_id="0-0",
            # Claim one message per dequeue call. Claiming a batch and returning
            # only its first item would strand the rest under this consumer
            # until the visibility timeout expires again.
            count=1,
        )
        messages = response[1] if response and len(response) > 1 else []
        for message_id, fields in messages:
            message_id = str(message_id)
            deliveries = await self._delivery_count(message_id)
            if deliveries > self.max_deliveries:
                await self._dead_letter(message_id, fields, deliveries, "delivery_limit_exceeded")
                continue
            claimed = await self._decode_or_dead_letter(message_id, fields, deliveries)
            if claimed is not None:
                return claimed
        return None

    async def _delivery_count(self, message_id: str) -> int:
        rows = await self.client.xpending_range(
            self.stream_key,
            self.group,
            min=message_id,
            max=message_id,
            count=1,
        )
        if not rows:
            return 1
        row = rows[0]
        if isinstance(row, dict):
            return int(row.get("times_delivered", row.get("delivery_count", 1)))
        return int(row[3]) if len(row) > 3 else 1

    async def _decode_or_dead_letter(
        self, message_id: str, fields: dict[str, Any], deliveries: int
    ) -> ClaimedJob | None:
        raw = fields.get("payload")
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            await self._dead_letter(message_id, fields, deliveries, "invalid_json")
            return None
        if not isinstance(value, dict):
            await self._dead_letter(message_id, fields, deliveries, "payload_not_object")
            return None
        return ClaimedJob(message_id, value, deliveries)

    async def ack(self, claimed: ClaimedJob) -> None:
        await self.client.xack(self.stream_key, self.group, claimed.message_id)
        await self.client.xdel(self.stream_key, claimed.message_id)
        await self.client.hdel(self.error_hash_key, claimed.message_id)

    async def fail(self, claimed: ClaimedJob, error: str) -> None:
        await self.client.hset(self.error_hash_key, claimed.message_id, error[:1000])

    async def _dead_letter(
        self,
        message_id: str,
        fields: dict[str, Any],
        deliveries: int,
        fallback_error: str,
    ) -> None:
        last_error = await self.client.hget(self.error_hash_key, message_id)
        await self.client.xadd(
            self.dead_letter_key,
            {
                "source_message_id": message_id,
                "payload": str(fields.get("payload", "")),
                "deliveries": str(deliveries),
                "last_error": str(last_error or fallback_error),
                "failed_at_ms": str(int(time.time() * 1000)),
            },
        )
        await self.client.xack(self.stream_key, self.group, message_id)
        await self.client.xdel(self.stream_key, message_id)
        await self.client.hdel(self.error_hash_key, message_id)

    @staticmethod
    def _stream_messages(response: Any) -> list[tuple[Any, dict[str, Any]]]:
        if not response:
            return []
        return list(response[0][1])

    async def ping(self) -> bool:
        return bool(await self.client.ping())

    async def close(self) -> None:
        await self.client.aclose()
