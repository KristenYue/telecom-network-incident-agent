import json
from pathlib import Path

from agent_runtime_platform.postgres import PostgresRuntimeBackend

from telecom_incident_agent.adapter import TelecomIncidentRuntimeAdapter
from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.service import IncidentService
from telecom_incident_agent.trace_ui import TRACE_UI_HTML


ROOT = Path(__file__).resolve().parents[1]


class FakeQueue:
    def __init__(self):
        self.jobs = []
        self.closed = False

    async def enqueue(self, job):
        self.jobs.append(job)

    async def dequeue(self, *, timeout_seconds=5):
        return self.jobs.pop(0) if self.jobs else None

    async def ping(self):
        return True

    async def close(self):
        self.closed = True


def test_queued_api_and_worker_paths_share_repository(tmp_path, optical_incident):
    queue = FakeQueue()
    service = IncidentService(tmp_path, queue=queue)

    queued = run_non_yielding(service.create(optical_incident))
    assert queued["runtime_status"] == "queued"
    assert queued["run_id"] is None
    assert queue.jobs == [{"kind": "diagnose", "incident_id": queued["incident_id"]}]

    completed = run_non_yielding(service.process_job(queue.jobs.pop(0)))
    assert completed["runtime_status"] == "completed"
    assert completed["run_id"]


def test_queued_review_and_resume_never_executes_a_real_change(tmp_path, optical_incident):
    queue = FakeQueue()
    service = IncidentService(tmp_path, queue=queue)
    high_risk = optical_incident.model_copy(update={"requested_actions": ["replace_optic"]})

    queued = run_non_yielding(service.create(high_risk))
    paused = run_non_yielding(service.process_job(queue.jobs.pop(0)))
    assert paused["runtime_status"] == "waiting_review"

    service.review(paused["incident_id"], approved=True, reviewer="operator-01", message="draft only")
    resuming = run_non_yielding(service.resume(paused["incident_id"]))
    assert resuming["runtime_status"] == "queued_resume"
    completed = run_non_yielding(service.process_job(queue.jobs.pop(0)))
    assert completed["runtime_status"] == "completed"
    approval = next(
        call["output"]
        for step in completed["result"]["steps"]
        for call in step["tool_calls"]
        if call["tool_name"] == "request_change_approval"
    )
    assert approval["execution_performed"] is False


def test_postgres_runtime_backend_is_selected_without_connecting(tmp_path, optical_incident):
    adapter = TelecomIncidentRuntimeAdapter(
        checkpoint_path=tmp_path / "unused.sqlite3",
        database_url="postgresql://example.invalid/telecom",
    )
    runtime = adapter._runtime(optical_incident)
    assert isinstance(runtime.backend, PostgresRuntimeBackend)


def test_compose_declares_and_wires_six_services():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    for service in (
        "incident-api", "runtime-worker", "postgres", "redis", "prometheus", "grafana"
    ):
        assert f"  {service}:" in compose
    assert "TELECOM_DATABASE_URL" in compose
    assert "TELECOM_REDIS_URL" in compose
    assert "/ready" in compose


def test_deploy_assets_and_trace_ui_are_parseable():
    sql = (ROOT / "deploy/postgres/init.sql").read_text(encoding="utf-8")
    assert "runtime_checkpoints" in sql
    assert "telecom_incidents" in sql
    dashboard = json.loads(
        (ROOT / "deploy/grafana/dashboards/telecom-agent.json").read_text(encoding="utf-8")
    )
    assert dashboard["uid"] == "telecom-incident-agent"
    assert "encodeURIComponent(id)" in TRACE_UI_HTML
    assert "innerHTML=data" not in TRACE_UI_HTML
