import json

import pytest

from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.knowledge import KnowledgeIndex, cosine
from telecom_incident_agent.network_evidence import (
    CapturedNetworkTools, NetworkLLMPlanner, as_incident,
)
from telecom_incident_agent.service import IncidentService


def snapshot(state="Idle"):
    return {"source": "frr_vtysh", "device_id": "lab-r1", "captured_at": "2026-11-19T00:00:00Z",
            "interfaces": {"eth0": {"status": "up"}},
            "bgp": {"ipv4Unicast": {"peers": {"10.70.0.12": {"state": state}}}}}


def test_revision_filter_prevents_obsolete_document_citation():
    docs = [{"document_id": "a", "title": "BGP", "version": version,
             "device_family": family, "source": "project://a", "text": text}
            for version, family, text in [("1", "r1", "BGP 旧版不可用于新版"),
                                          ("2", "r1", "BGP 新版检查邻居"),
                                          ("2", "r2", "BGP 另一个设备系列")]]
    index = KnowledgeIndex(docs)
    result = index.search("BGP 邻居", version="2", device_family="r1")
    assert len(result["results"]) == 1
    assert result["results"][0]["version"] == "2"
    assert result["results"][0]["device_family"] == "r1"
    assert len(result["results"][0]["sha256"]) == 64
    assert index.search("BGP", version="missing")["no_answer"]


def test_dense_unavailable_is_explicit_and_sparse_fallback_is_visible():
    index = KnowledgeIndex.from_runbooks()
    assert index.search("BGP", mode="dense")["no_answer"]
    result = index.search("BGP 邻居", mode="hybrid")
    assert result["dense_status"] == "not_configured"
    assert result["results"][0]["document_id"] == "rb-bgp-001"
    with pytest.raises(ValueError):
        cosine([1], [1, 2])


def test_cjk_query_and_unseen_terms_do_not_force_answer():
    index = KnowledgeIndex.from_runbooks()
    assert index.search("光功率", mode="bm25")["results"][0]["document_id"] == "rb-optical-001"
    assert index.search("zzzznotobserved", mode="bm25")["no_answer"]


def test_captured_adapter_does_not_invent_optical_or_path_measurements():
    incident = as_incident(snapshot())
    tools = CapturedNetworkTools(incident)
    result = run_non_yielding(tools.get_interface_status("lab-r1", "eth0"))
    assert result["source"] == "frr_vtysh" and result["synthetic"] is False
    assert "rx_power_dbm" not in result
    with pytest.raises(ValueError, match="not observed"):
        run_non_yielding(tools.get_interface_status("lab-r1", "eth99"))
    with pytest.raises(ValueError, match="no active path probe"):
        run_non_yielding(tools.run_path_probe("lab-r1", "example.com"))


def test_captured_network_uses_existing_runtime_and_persists_trace(tmp_path):
    service = IncidentService(tmp_path)
    record = run_non_yielding(service.create(as_incident(snapshot())))
    assert record["runtime_status"] == "completed"
    result = record["result"]["result"]
    assert result["planner_mode"] == "deterministic_baseline"
    assert result["diagnosis"]["root_causes"][0]["fault_type"] == "bgp_neighbor_down"
    assert service.trace(record["incident_id"])["data_boundary"] == "captured_software_network"
    assert service.get(record["incident_id"])["result"] == record["result"]


def test_no_alarm_is_not_proof_of_full_network_health(tmp_path):
    record = run_non_yielding(IncidentService(tmp_path).create(as_incident(snapshot("Established"))))
    assert record["runtime_status"] == "completed"
    assert record["result"]["result"]["diagnosis"]["root_causes"] == []


def test_model_cannot_forge_citations_or_invoke_changes():
    class Client:
        telemetry = []
        action = {"kind": "tool", "tool_name": "restart_router", "arguments": {}}
        def decide(self, **_):
            return self.action
    client = Client()
    planner = NetworkLLMPlanner(client)
    request = as_incident(snapshot()).model_dump_json()
    with pytest.raises(ValueError, match="unavailable"):
        run_non_yielding(planner.decide(request=request, observations=(), step=0))
    observations = tuple({"kind": "tool_result", "tool_name": name, "status": "succeeded", "output": output}
                         for name, output in [("get_device_status", {}), ("get_routing_neighbors", {}),
                                              ("search_runbook", {"results": [{"chunk_id": "known"}]})])
    client.action = {"kind": "finish", "summary": "报告", "citations": ["forged"]}
    with pytest.raises(ValueError, match="unverified"):
        run_non_yielding(planner.decide(request=request, observations=observations, step=3))
    client.action["citations"] = ["known"]
    result = run_non_yielding(planner.decide(request=request, observations=observations, step=3))
    assert result.result["changes_executed"] is False
