"""Dedicated Redis consumer that executes Runtime jobs against PostgreSQL."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from prometheus_client import Counter, Gauge, Histogram, start_http_server

from .jobs import ClaimedJob, RedisIncidentJobQueue
from .service import IncidentService


LOG = logging.getLogger("telecom_incident_agent.worker")
JOBS = Counter("telecom_worker_jobs_total", "Worker jobs", ["kind", "outcome"])
JOB_LATENCY = Histogram("telecom_worker_job_duration_seconds", "Worker job duration", ["kind"])
WORKER_UP = Gauge("telecom_worker_up", "Whether the incident worker loop is active")
PENDING_RETRIES = Counter(
    "telecom_worker_retries_total", "Jobs left pending for stream reclaim", ["kind"]
)


async def process_claimed_job(service: IncidentService, claimed: ClaimedJob) -> bool:
    """Process one claimed Stream entry and settle it explicitly."""

    if service.queue is None:
        raise RuntimeError("job queue is required")
    kind = str(claimed.payload.get("kind", "unknown"))
    with JOB_LATENCY.labels(kind).time():
        try:
            await service.process_job(claimed.payload)
        except Exception as error:
            await service.queue.fail(claimed, f"{type(error).__name__}: {error}")
            JOBS.labels(kind, "failed").inc()
            PENDING_RETRIES.labels(kind).inc()
            LOG.exception(
                "incident job failed and remains pending for reclaim",
                extra={
                    "incident_id": claimed.payload.get("incident_id"),
                    "message_id": claimed.message_id,
                    "deliveries": claimed.deliveries,
                },
            )
            return False
        await service.queue.ack(claimed)
        JOBS.labels(kind, "completed").inc()
        return True


async def run_worker(service: IncidentService) -> None:
    if service.queue is None:
        raise RuntimeError("TELECOM_REDIS_URL is required for the Runtime Worker")
    WORKER_UP.set(1)
    try:
        while True:
            claimed = await service.queue.dequeue(timeout_seconds=5)
            if claimed is None:
                continue
            await process_claimed_job(service, claimed)
    finally:
        WORKER_UP.set(0)
        await service.queue.close()


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    database_url = os.environ.get("TELECOM_DATABASE_URL")
    queue_url = os.environ.get("TELECOM_REDIS_URL")
    if not database_url or not queue_url:
        raise SystemExit("TELECOM_DATABASE_URL and TELECOM_REDIS_URL are required")
    metrics_port = int(os.getenv("TELECOM_WORKER_METRICS_PORT", "9000"))
    start_http_server(metrics_port)
    queue = RedisIncidentJobQueue(
        queue_url,
        visibility_timeout_seconds=float(
            os.getenv("TELECOM_JOB_VISIBILITY_TIMEOUT_SECONDS", "30")
        ),
        max_deliveries=int(os.getenv("TELECOM_JOB_MAX_DELIVERIES", "3")),
    )
    service = IncidentService(
        Path(os.getenv("TELECOM_AGENT_DATA_DIR", "/data")),
        database_url=database_url,
        queue=queue,
    )
    asyncio.run(run_worker(service))


if __name__ == "__main__":
    main()
