"""FastAPI surface matching the planned incident API."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .models import IncidentRequest
from .runbooks import RUNBOOKS
from .security import sanitize_untrusted_text
from .service import IncidentService


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool
    reviewer: str = Field(min_length=1, max_length=100)
    message: str | None = Field(default=None, max_length=2000)


def create_app(data_dir: str | Path | None = None) -> FastAPI:
    storage = Path(data_dir or os.getenv("TELECOM_AGENT_DATA_DIR", ".runtime"))
    service = IncidentService(storage)
    app = FastAPI(
        title="Telecom Network Incident Diagnosis Agent",
        version="0.1.0",
        description="Synthetic-only, evidence-first incident diagnosis API. It never changes a real device.",
    )
    app.state.service = service

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "data_boundary": "synthetic"}

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
