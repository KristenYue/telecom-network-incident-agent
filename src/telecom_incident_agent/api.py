"""FastAPI surface matching the planned incident API."""

from __future__ import annotations

import os
import asyncio
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import IncidentRequest
from .runbooks import RUNBOOKS
from .security import sanitize_untrusted_text
from .service import IncidentService
from .trace_ui import TRACE_UI_HTML


HTTP_REQUESTS = Counter(
    "telecom_http_requests_total", "Incident API requests", ["method", "path", "status"]
)
HTTP_LATENCY = Histogram(
    "telecom_http_request_duration_seconds", "Incident API request latency", ["method", "path"]
)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool
    reviewer: str = Field(min_length=1, max_length=100)
    message: str | None = Field(default=None, max_length=2000)


class DeviceTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal["status", "diagnose", "agent", "run", "interlock", "diagnose_shelf"] = "status"
    request: str | None = Field(default=None, min_length=1, max_length=2000)
    allow_sim_write: bool = False

    @model_validator(mode="after")
    def validate_agent_request(self) -> "DeviceTaskRequest":
        if self.scenario == "agent" and (self.request is None or not self.request.strip()):
            raise ValueError("agent scenario requires request")
        if self.scenario != "agent" and self.request is not None:
            raise ValueError("request is supported only by the agent scenario")
        return self


def create_app(data_dir: str | Path | None = None) -> FastAPI:
    storage = Path(data_dir or os.getenv("TELECOM_AGENT_DATA_DIR", ".runtime"))
    service = IncidentService(
        storage,
        database_url=os.getenv("TELECOM_DATABASE_URL"),
        queue_url=os.getenv("TELECOM_REDIS_URL"),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        local_worker = (
            asyncio.create_task(service.device_tasks.run_local_worker())
            if service.device_tasks is not None and service.queue is None else None
        )
        try:
            yield
        finally:
            if local_worker is not None:
                local_worker.cancel()
                with suppress(asyncio.CancelledError):
                    await local_worker
            if service.queue is not None:
                await service.queue.close()

    app = FastAPI(
        title="Industrial AI Agent",
        version="0.4.0",
        description=(
            "Model-driven industrial equipment diagnosis plus evidence-first telecom incident analysis. "
            "It never changes a real production device."
        ),
        lifespan=lifespan,
    )
    app.state.service = service

    @app.middleware("http")
    async def observe_http(request: Request, call_next):
        started = time.perf_counter()
        status = 500
        route_path = request.url.path
        try:
            response = await call_next(request)
            status = response.status_code
            route = request.scope.get("route")
            route_path = getattr(route, "path", route_path)
            return response
        finally:
            HTTP_REQUESTS.labels(request.method, route_path, str(status)).inc()
            HTTP_LATENCY.labels(request.method, route_path).observe(time.perf_counter() - started)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "data_boundary": "synthetic"}

    @app.get("/ready")
    async def ready() -> dict:
        try:
            checks = await service.ready()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"dependency check failed: {type(exc).__name__}") from exc
        if not all(checks.values()):
            raise HTTPException(status_code=503, detail=checks)
        return {"status": "ready", "checks": checks}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/trace-ui", response_class=HTMLResponse, include_in_schema=False)
    async def trace_ui() -> str:
        return TRACE_UI_HTML

    @app.post("/v1/incidents", status_code=201)
    async def create_incident(request: IncidentRequest) -> dict:
        return await service.create(request)

    @app.get("/v1/knowledge/search")
    def search_knowledge(query: str = Query(min_length=1, max_length=2000),
                         device_family: str | None = None, version: str | None = None,
                         mode: Literal["bm25", "dense", "hybrid"] = "hybrid") -> dict:
        from .knowledge import default_index
        try:
            return default_index().search(query, device_family=device_family, version=version, mode=mode)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/v1/network-diagnoses", status_code=201)
    async def diagnose_network(model_driven: bool = False) -> dict:
        from .network_evidence import NetworkCollector, as_incident
        # No user-controlled URL or CLI is accepted. Collection failures never
        # fall back to synthetic observations.
        try:
            snapshot = NetworkCollector.from_environment().capture()
            incident = as_incident(snapshot)
            if model_driven:
                if not all(os.getenv(k) for k in ("TELECOM_MODEL_BASE_URL", "TELECOM_MODEL_ID", "TELECOM_MODEL_API_KEY")):
                    raise HTTPException(503, "model planner is not configured")
                incident = incident.model_copy(update={"dataset_version": "network-capture-model-v1"})
        except (KeyError, OSError, ValueError) as exc:
            raise HTTPException(503, "network evidence unavailable: " + type(exc).__name__) from exc
        return await service.create(incident)

    @app.post("/v1/device-tasks", status_code=202)
    def submit_device_task(request: DeviceTaskRequest) -> dict:
        if service.device_tasks is None:
            raise HTTPException(status_code=503, detail="simulator integration is disabled")
        try:
            return service.device_tasks.submit(request.scenario, request.allow_sim_write, request.request)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/v1/device-tasks/{task_id}")
    def get_device_task(task_id: str) -> dict:
        if service.device_tasks is None:
            raise HTTPException(status_code=503, detail="simulator integration is disabled")
        try:
            return service.device_tasks.get(task_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="device task not found") from exc

    @app.get("/v1/incidents/{incident_id}")
    async def get_incident(incident_id: str) -> dict:
        try:
            return service.get(incident_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/incidents/{incident_id}/trace")
    async def get_trace(incident_id: str) -> dict:
        try:
            return service.trace(incident_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/incidents/{incident_id}/reviews", status_code=201)
    async def create_review(incident_id: str, request: ReviewRequest) -> dict:
        try:
            return service.review(incident_id, approved=request.approved, reviewer=request.reviewer, message=request.message)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/incidents/{incident_id}/resume")
    async def resume_incident(incident_id: str) -> dict:
        try:
            return await service.resume(incident_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/runbooks/search")
    async def search_runbooks(query: str = Query(min_length=1, max_length=1000), fault_type: str | None = None) -> dict:
        safe_query, flags = sanitize_untrusted_text(query)
        words = safe_query.lower().replace("_", " ").split()
        results = []
        for runbook in RUNBOOKS:
            if fault_type and runbook["fault_type"] != fault_type:
                continue
            haystack = " ".join([runbook["title"], runbook["fault_type"], *runbook["keywords"]]).lower()
            if fault_type or any(word in haystack for word in words):
                results.append(runbook)
        return {"query": safe_query, "results": results[:5], "security_flags": flags, "data_boundary": "synthetic"}

    return app


app = create_app()


def main() -> None:
    import uvicorn
    uvicorn.run("telecom_incident_agent.api:app", host="0.0.0.0", port=8000)
