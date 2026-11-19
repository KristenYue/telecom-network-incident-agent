"""Minimal robot task REST + SSE service; run as a single local process."""
import asyncio
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .robot_skills import SKILLS
from .robot_tasks import RobotTasks


class Submit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=128)
    model_driven: bool = True


def create_app(root=None, *, transport=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.tasks = RobotTasks(root or os.getenv("ROBOT_DATA_DIR", ".runtime/robot"), transport=transport)
        try:
            yield
        finally:
            app.state.tasks.close()
    app = FastAPI(title="Robot Skill Task API", lifespan=lifespan)

    def tasks():
        return app.state.tasks

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": "task not found"})

    @app.get("/robots/workcell/skills")
    def skills():
        return {"skills": SKILLS, "data_boundary": tasks().transport.boundary}

    @app.get("/robots/workcell/status")
    def status():
        return tasks().transport.status()

    @app.post("/robot/tasks", status_code=202)
    def submit(body: Submit):
        if body.model_driven:
            from .industrial_llm import IndustrialModelClient
            try:
                IndustrialModelClient.from_environment()
            except ValueError:
                raise HTTPException(503, "model credentials are not configured")
        try:
            return tasks().submit(body.request, body.idempotency_key, model=body.model_driven)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        except OverflowError as exc:
            raise HTTPException(429, str(exc))

    @app.get("/robot/tasks/{task_id}")
    def get(task_id: str):
        return tasks().get(task_id)

    @app.post("/robot/tasks/{task_id}/cancel")
    def cancel(task_id: str):
        return tasks().cancel(task_id)

    @app.get("/robot/tasks/{task_id}/events")
    async def events(task_id: str, request: Request, after: int = 0):
        tasks().get(task_id)
        try:
            cursor = max(after, int(request.headers.get("Last-Event-ID", "0")), 0)
        except ValueError:
            raise HTTPException(400, "invalid event cursor")
        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                batch = tasks().events(task_id, cursor)
                for item in batch:
                    cursor = item["id"]
                    yield f"id: {cursor}\nevent: {item['event']}\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"
                # Bounded read batches; events are read from DB, no per-subscriber queue.
                if tasks().get(task_id)["state"] not in ("queued", "running") and not batch:
                    return
                if not batch:
                    yield ": heartbeat\n\n"
                    await asyncio.sleep(.25)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
    return app


def main():
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=8011)
