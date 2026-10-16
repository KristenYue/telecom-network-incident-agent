import sys

import pytest
from fastapi.testclient import TestClient

from telecom_incident_agent.api import create_app
from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.service import IncidentService


def test_service_persists_incident_and_trace(tmp_path, optical_incident):
    service = IncidentService(tmp_path)
    created = run_non_yielding(service.create(optical_incident))
    loaded = service.get(created["incident_id"])
    trace = service.trace(created["incident_id"])
    assert loaded["runtime_status"] == "completed"
    assert trace["tool_call_count"] == 9
    assert trace["data_boundary"] == "synthetic"


def test_api_exposes_planned_routes(tmp_path):
    app = create_app(tmp_path)
    routes = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    expected = {
        ("/v1/incidents", "POST"),
        ("/v1/incidents/{incident_id}", "GET"),
        ("/v1/incidents/{incident_id}/trace", "GET"),
        ("/v1/incidents/{incident_id}/reviews", "POST"),
        ("/v1/incidents/{incident_id}/resume", "POST"),
        ("/v1/runbooks/search", "GET"),
        ("/ready", "GET"),
        ("/trace-ui", "GET"),
    }
    assert expected <= routes


@pytest.mark.skipif(sys.platform == "win32", reason="managed Windows asyncio host cannot close TestClient lifespan")
def test_operational_endpoints_expose_readiness_metrics_and_trace_ui(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").json()["status"] == "ready"
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "telecom_http_requests_total" in metrics.text
        trace_ui = client.get("/trace-ui")
        assert trace_ui.status_code == 200
        assert "通信网络故障诊断 Trace" in trace_ui.text
