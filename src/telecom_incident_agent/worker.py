"""Dedicated Redis consumer that executes Runtime jobs against PostgreSQL."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from prometheus_client import Counter, Gauge, Histogram, start_http_server

from .service import IncidentService


LOG = logging.getLogger("telecom_incident_agent.worker")
JOBS = Counter("telecom_worker_jobs_total", "Worker jobs", ["kind", "outcome"])
JOB_LATENCY = Histogram("telecom_worker_job_duration_seconds", "Worker job duration", ["kind"])
WORKER_UP = Gauge("telecom_worker_up", "Whether the incident worker loop is active")


async def run_worker(service: IncidentService) -> None:
    if service.queue is None:
        raise RuntimeError("TELECOM_REDIS_URL is required for the Runtime Worker")
    WORKER_UP.set(1)
    try:
        while True:
            job = await service.queue.dequeue(timeout_seconds=5)
            if job is None:
                continue
            kind = str(job.get("kind", "unknown"))
            with JOB_LATENCY.labels(kind).time():
                try:
                    await service.process_job(job)
                except Exception:
                    JOBS.labels(kind, "failed").inc()
                    LOG.exception("incident job failed", extra={"incident_id": job.get("incident_id")})
                else:
                    JOBS.labels(kind, "completed").inc()
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
    service = IncidentService(
        Path(os.getenv("TELECOM_AGENT_DATA_DIR", "/data")),
        database_url=database_url,
        queue_url=queue_url,
    )
    asyncio.run(run_worker(service))


if __name__ == "__main__":
    main()
