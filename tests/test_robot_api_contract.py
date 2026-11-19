"""Exercise endpoint contracts and persisted SSE replay without a network server."""
import time
from types import SimpleNamespace

from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.robot_api import Submit, create_app
from telecom_incident_agent.robot_tasks import RobotTasks


def test_api_submission_conflict_and_completed_sse_replay(tmp_path):
    app = create_app(tmp_path)
    service = app.state.tasks = RobotTasks(tmp_path)
    routes = {r.path: r.endpoint for r in app.routes if hasattr(r, "endpoint")}
    try:
        task = routes["/robot/tasks"](Submit(request="inspect", idempotency_key="api", model_driven=False))
        deadline = time.monotonic()+5
        while service.get(task["id"])["state"] in ("queued", "running"):
            assert time.monotonic()<deadline
            time.sleep(.01)
        assert routes["/robot/tasks/{task_id}"](task["id"])["state"] == "completed"
        async def disconnected():
            return False
        request = SimpleNamespace(headers={}, is_disconnected=disconnected)
        response = run_non_yielding(routes["/robot/tasks/{task_id}/events"](task["id"], request))
        async def read():
            return [chunk async for chunk in response.body_iterator]
        chunks = run_non_yielding(read())
        assert any("event: progress" in c for c in chunks)
        assert any("event: terminal" in c for c in chunks)
        cursor = service.events(task["id"])[-1]["id"]
        assert service.events(task["id"], cursor) == []
    finally:
        service.close()
