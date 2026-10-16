"""Redis-backed job transport for the deploy topology."""

from __future__ import annotations

import json
from typing import Any, Protocol


QUEUE_KEY = "telecom:incident-jobs:v1"


class IncidentJobQueue(Protocol):
    async def enqueue(self, job: dict[str, Any]) -> None: ...
    async def dequeue(self, *, timeout_seconds: int = 5) -> dict[str, Any] | None: ...
    async def ping(self) -> bool: ...
    async def close(self) -> None: ...


class RedisIncidentJobQueue:
    def __init__(self, url: str, *, queue_key: str = QUEUE_KEY) -> None:
        if not url.strip():
            raise ValueError("Redis URL must not be blank")
        try:
            from redis.asyncio import Redis
        except ImportError as exc:  # pragma: no cover - deploy optional dependency
            raise RuntimeError("Redis jobs require the deploy extra") from exc
        self.client = Redis.from_url(url, decode_responses=True)
        self.queue_key = queue_key

    async def enqueue(self, job: dict[str, Any]) -> None:
        payload = json.dumps(job, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        await self.client.rpush(self.queue_key, payload)

    async def dequeue(self, *, timeout_seconds: int = 5) -> dict[str, Any] | None:
        item = await self.client.blpop(self.queue_key, timeout=timeout_seconds)
        if item is None:
            return None
        _, payload = item
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise ValueError("incident job payload must be an object")
        return value

    async def ping(self) -> bool:
        return bool(await self.client.ping())

    async def close(self) -> None:
        await self.client.aclose()
