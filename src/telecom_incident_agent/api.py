"""FastAPI surface matching the planned incident API."""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, ConfigDict, Field

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


def create_app(data_dir: str | Path | None = None) -> FastAPI:
    storage = Path(data_dir or os.getenv("TELECOM_AGENT_DATA_DIR", ".runtime"))
    service = IncidentService(
        storage,
        database_url=os.getenv("TELECOM_DATABASE_URL"),
        queue_url=os.getenv("TELECOM_REDIS_URL"),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if service.queue is not None:
            await service.queue.close()

    app = FastAPI(
        title="Telecom Network Incident Diagnosis Agent",
        version="0.2.0",
        description="Synthetic-only, evidence-first incident diagnosis API. It never changes a real device.",
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
