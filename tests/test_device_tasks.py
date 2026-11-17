from io import BytesIO
import json
import time

import pytest
from fastapi import HTTPException

from telecom_incident_agent.api import DeviceTaskRequest, create_app
from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent import device_tasks
from telecom_incident_agent.adapter import TelecomIncidentRuntimeAdapter
from telecom_incident_agent.shelf_adapter import NoRedirect, ShelfTelemetryAdapter


def test_device_task_survives_restart_and_old_worker_cannot_commit(tmp_path, monkeypatch):
    monkeypatch.setenv("TELECOM_SIMULATOR_PORT", "18765")
    monkeypatch.delenv("TELECOM_SIMULATOR_ALLOW_WRITES", raising=False)
    first = create_app(tmp_path)
    submit = next(route.endpoint for route in first.routes if route.path == "/v1/device-tasks")
    with pytest.raises(HTTPException) as rejected:
        submit(DeviceTaskRequest(scenario="run"))
    assert rejected.value.status_code == 403
    task_id = submit(DeviceTaskRequest())["id"]

    restarted = create_app(tmp_path)
    queue = restarted.state.service.device_tasks
    owner = queue.claim()
    assert owner["id"] == task_id
    assert first.state.service.device_tasks.claim() is None

    monkeypatch.setattr(queue, "lease_seconds", 0)
    assert queue.finish(owner, "completed", {"code": "ok"})
    expired = queue.submit("status", False)
    stale = queue.claim()
    assert stale["id"] == expired["id"]
    assert queue.claim() is None
    assert not queue.finish(stale, "completed", {"code": "late"})
    assert queue.get(expired["id"])["status"] == "outcome_unknown"


def test_shelf_telemetry_uses_timestamp_and_runtime_runbook(tmp_path, monkeypatch):
    monkeypatch.delenv("TELECOM_SIMULATOR_PORT", raising=False)
    monkeypatch.setenv("TELECOM_SHELF_SOURCE_URL", "http://127.0.0.1:18888")
    monkeypatch.setenv("TELECOM_SHELF_DEVICE_ID", "shelf-02")
    monkeypatch.setenv("TELECOM_SHELF_SOURCE_TOKEN", "test-token")
    row = {"deviceID": "shelf-02", "receivedAt": int(time.time() * 1000), "state": "LOW_STOCK"}

    def open_fixture(self, request, timeout):
        assert request.full_url.endswith("/api/shelves/shelf-02/telemetry?limit=1")
        assert request.get_header("X-api-token") == "test-token"
        return BytesIO(json.dumps([row]).encode())

    from urllib.request import OpenerDirector

    monkeypatch.setattr(OpenerDirector, "open", open_fixture)
    monkeypatch.setattr(device_tasks.asyncio, "run", run_non_yielding)
    queue = create_app(tmp_path).state.service.device_tasks
    task = queue.submit("diagnose_shelf", False)
    queue.work_once()
    outcome = queue.get(task["id"])["result"]["result"]
    assert outcome["fault"] == "inventory_alert"
    assert outcome["runbook"]["runbook_id"] == "shelf-inventory-001"
    row["receivedAt"] -= 3600_000
    snapshot = ShelfTelemetryAdapter("http://127.0.0.1:18888", "shelf-02", "test-token").read_snapshot()
    assert snapshot == {"source": "smart_shelf_cloud", "reachable": False, "code": "TELEMETRY_STALE"}
    assert NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com") is None


def test_model_report_is_generated_only_after_retrieval(tmp_path, monkeypatch):
    monkeypatch.setenv("TELECOM_MODEL_BASE_URL", "https://model.invalid/v1")
    monkeypatch.setenv("TELECOM_MODEL_ID", "fixture-model")
    monkeypatch.setenv("TELECOM_MODEL_API_KEY", "fixture-key")

    def fixture_response(self, request, timeout):
        payload = json.loads(request.data)
        evidence = json.loads(payload["messages"][1]["content"])
        assert evidence["runbook"]["runbook_id"] == "sim-interlock-001"
        return BytesIO(json.dumps({"choices": [{"message": {"content": "参照 sim-interlock-001 人工检查联锁。"}}]}).encode())

    from urllib.request import OpenerDirector

    monkeypatch.setattr(OpenerDirector, "open", fixture_response)
    adapter = TelecomIncidentRuntimeAdapter(checkpoint_path=tmp_path / "model.sqlite3")
    result = run_non_yielding(adapter.diagnose_snapshot(
        lambda: {"reachable": True, "state": "E_STOP", "data": {}},
        task_id="model-fixture", may_send=lambda: True, boundary="simulation",
    ))
    assert result.tool_call_count == 3
    assert result.result["model_report"]["status"] == "generated"
