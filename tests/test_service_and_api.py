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
    }
    assert expected <= routes
