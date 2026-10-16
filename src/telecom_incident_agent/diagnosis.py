"""Evidence-first deterministic baseline and provider-neutral Runtime planner."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from agent_runtime_platform.contracts import PlannerAction

from .models import (
    DiagnosisResult,
    Evidence,
    IncidentRequest,
    RemediationStep,
    RiskLevel,
    RootCauseCandidate,
)
from .security import sanitize_logs
from .taxonomy import FAULT_POLICIES, HIGH_RISK_ACTIONS


ALARM_TO_FAULT = {
    "link_down": "interface_down",
    "interface_down": "interface_down",
    "rx_power_low": "optical_power_abnormal",
    "optical_power_low": "optical_power_abnormal",
    "ber_high": "high_ber",
    "crc_errors": "high_ber",
    "packet_loss_high": "packet_loss",
    "latency_high": "latency_jitter",
    "jitter_high": "latency_jitter",
    "utilization_high": "high_utilization",
    "bgp_down": "bgp_neighbor_down",
    "bgp_neighbor_down": "bgp_neighbor_down",
    "ospf_down": "ospf_adjacency",
    "ospf_adjacency": "ospf_adjacency",
    "route_flap": "route_flap",
    "dns_timeout": "upstream_dependency",
    "upstream_failure": "upstream_dependency",
    "cpu_high": "device_resource",
    "memory_high": "device_resource",
    "upstream_node_down": "alarm_storm_root",
}


def _fault_hint(incident: IncidentRequest) -> str | None:
    for alarm in incident.alarms:
        if alarm.alarm_type in ALARM_TO_FAULT:
            return ALARM_TO_FAULT[alarm.alarm_type]
    for metric in incident.metrics:
        if metric.metric == "rx_power_dbm" and metric.value < -22:
            return "optical_power_abnormal"
        if metric.metric == "ber" and metric.value > 1e-6:
            return "high_ber"
        if metric.metric == "packet_loss_percent" and metric.value > 2:
            return "packet_loss"
        if metric.metric in {"latency_ms", "jitter_ms"} and metric.value > (100 if metric.metric == "latency_ms" else 30):
            return "latency_jitter"
        if metric.metric == "utilization_percent" and metric.value > 90:
            return "high_utilization"
        if metric.metric in {"cpu_percent", "memory_percent"} and metric.value > 90:
            return "device_resource"
    return None


def _evidence(source_type: str, source_id: str, summary: str) -> Evidence:
    return Evidence(
        evidence_id=f"{source_type}:{source_id}",
        source_type=source_type,
        source_id=source_id,
        summary=summary,
    )


def build_diagnosis(
    incident: IncidentRequest,
    observations: tuple[dict[str, Any], ...],
) -> DiagnosisResult:
    """Rank root causes only from incident signals and successful tool evidence."""

    scores: dict[str, float] = defaultdict(float)
    evidence: dict[str, list[Evidence]] = defaultdict(list)
    _, security_flags = sanitize_logs(incident.logs)

    for alarm in incident.alarms:
        fault = ALARM_TO_FAULT.get(alarm.alarm_type)
        if fault:
            scores[fault] += 2.0 if alarm.severity in {"major", "critical"} else 1.2
            evidence[fault].append(_evidence("alarm", alarm.alarm_id, f"{alarm.device_id} reported {alarm.alarm_type} ({alarm.severity})"))

    metric_rules = {
        "rx_power_dbm": (lambda value: value < -22, "optical_power_abnormal"),
        "ber": (lambda value: value > 1e-6, "high_ber"),
        "packet_loss_percent": (lambda value: value > 2, "packet_loss"),
        "latency_ms": (lambda value: value > 100, "latency_jitter"),
        "jitter_ms": (lambda value: value > 30, "latency_jitter"),
        "utilization_percent": (lambda value: value > 90, "high_utilization"),
        "cpu_percent": (lambda value: value > 90, "device_resource"),
        "memory_percent": (lambda value: value > 90, "device_resource"),
        "route_changes_per_minute": (lambda value: value > 20, "route_flap"),
    }
    for index, sample in enumerate(incident.metrics):
        rule = metric_rules.get(sample.metric)
        if rule and rule[0](sample.value):
            fault = rule[1]
            scores[fault] += 1.8
            evidence[fault].append(_evidence("metric", f"{sample.target}:{sample.metric}:{index}", f"{sample.metric}={sample.value}{sample.unit}"))

    by_tool = {
        item.get("tool_name"): item.get("output")
        for item in observations
        if item.get("kind") == "tool_result" and item.get("status") == "succeeded" and isinstance(item.get("output"), dict)
    }
    interface = by_tool.get("get_interface_status", {})
    if interface.get("oper_status") == "down" and interface.get("admin_status") == "up":
        # A physical/operational down explains downstream loss; preserve the
        # causal signal above the symptom instead of ranking packet loss first.
        scores["interface_down"] += 3.0
        evidence["interface_down"].append(_evidence("tool", "get_interface_status", "oper_status=down while admin_status=up"))
    if interface.get("rx_power_dbm", 0) < -22:
        scores["optical_power_abnormal"] += 1.7
        evidence["optical_power_abnormal"].append(_evidence("tool", "get_interface_status:rx_power", f"rx_power_dbm={interface['rx_power_dbm']}"))
    if interface.get("ber", 0) > 1e-6:
        scores["high_ber"] += 1.7
        evidence["high_ber"].append(_evidence("tool", "get_interface_status:ber", f"ber={interface['ber']}"))
    if interface.get("packet_loss_percent", 0) > 2:
        scores["packet_loss"] += 1.4
        evidence["packet_loss"].append(_evidence("tool", "get_interface_status:loss", f"packet_loss_percent={interface['packet_loss_percent']}"))
    if interface.get("utilization_percent", 0) > 90:
        scores["high_utilization"] += 1.7
        evidence["high_utilization"].append(_evidence("tool", "get_interface_status:utilization", f"utilization_percent={interface['utilization_percent']}"))

    device = by_tool.get("get_device_status", {})
    if device.get("cpu_percent", 0) > 90 or device.get("memory_percent", 0) > 90:
        scores["device_resource"] += 1.5
        evidence["device_resource"].append(_evidence("tool", "get_device_status", f"cpu={device.get('cpu_percent')} memory={device.get('memory_percent')}"))

    routing_outputs = [item.get("output", {}) for item in observations if item.get("tool_name") == "get_routing_neighbors" and item.get("status") == "succeeded"]
    for output in routing_outputs:
        states = {neighbor.get("state") for neighbor in output.get("neighbors", [])}
        if output.get("protocol") == "bgp" and states - {"established"}:
            scores["bgp_neighbor_down"] += 1.7
            evidence["bgp_neighbor_down"].append(_evidence("tool", "get_routing_neighbors:bgp", f"states={sorted(states)}"))
        if output.get("protocol") == "ospf" and states - {"full"}:
            scores["ospf_adjacency"] += 1.7
            evidence["ospf_adjacency"].append(_evidence("tool", "get_routing_neighbors:ospf", f"states={sorted(states)}"))

    path = by_tool.get("run_path_probe", {})
    if path.get("packet_loss_percent", 0) > 2:
        scores["packet_loss"] += 1.2
        evidence["packet_loss"].append(_evidence("tool", "run_path_probe:loss", f"probe loss={path['packet_loss_percent']}%"))
    if path.get("latency_ms", 0) > 100 or path.get("jitter_ms", 0) > 30:
        scores["latency_jitter"] += 1.2
        evidence["latency_jitter"].append(_evidence("tool", "run_path_probe:latency", f"latency={path.get('latency_ms')}ms jitter={path.get('jitter_ms')}ms"))
    if path and not path.get("reachable", True) and any(a.alarm_type in {"dns_timeout", "upstream_failure"} for a in incident.alarms):
        scores["upstream_dependency"] += 1.4
        evidence["upstream_dependency"].append(_evidence("tool", "run_path_probe:reachability", "dependency target was not reachable"))

    related = by_tool.get("list_related_alarms", {})
    devices = {alarm.device_id for alarm in incident.alarms}
    if related.get("count", 0) >= 4 and len(devices) >= 3:
        # Shared-time multi-device correlation is stronger root evidence than
        # any one downstream loss measurement.
        scores["alarm_storm_root"] += 3.5
        evidence["alarm_storm_root"].append(_evidence("tool", "list_related_alarms", f"{related['count']} alarms across {len(devices)} devices"))

    ranked: list[RootCauseCandidate] = []
    for fault, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:3]:
        items = list({item.evidence_id: item for item in evidence[fault]}.values())
        if not items:
            continue
        confidence = min(0.98, 0.45 + score * 0.09)
        assessment = "confirmed" if confidence >= 0.9 and len(items) >= 2 else "likely" if confidence >= 0.65 else "to_investigate"
        ranked.append(RootCauseCandidate(
            fault_type=fault, label=FAULT_POLICIES[fault].label,
            confidence=round(confidence, 3), assessment=assessment,
            supporting_evidence=items,
        ))

    high_risk = sorted(set(incident.requested_actions) & HIGH_RISK_ACTIONS)
    primary = ranked[0].fault_type if ranked else None
    search = by_tool.get("search_runbook", {})
    runbook = next((item for item in search.get("results", []) if not primary or item.get("fault_type") == primary), None)
    security_flags = sorted(set(security_flags + list(search.get("security_flags", []))))
    missing: list[str] = []
    contradictory = (
        any(alarm.alarm_type in {"link_down", "interface_down"} for alarm in incident.alarms)
        and interface.get("oper_status") == "up"
    )
    if not ranked:
        missing.extend(["需要至少一项可验证告警、指标或成功的只读工具结果", "需要明确受影响设备或接口"])
    if contradictory:
        missing.append("接口告警与实时接口状态矛盾，需要人工核对时间戳和设备时钟")
    remediation: list[RemediationStep] = []
    if primary:
        policy = FAULT_POLICIES[primary]
        for index, instruction in enumerate(policy.safe_actions, start=1):
            remediation.append(RemediationStep(order=index, instruction=instruction, risk_level=RiskLevel.LOW, source_runbook_id=runbook.get("runbook_id") if runbook else None))
    for action in high_risk:
        remediation.append(RemediationStep(order=len(remediation) + 1, instruction=f"仅创建变更建议：{action}；不得由 Agent 自动执行", risk_level=RiskLevel.HIGH, requires_approval=True, source_runbook_id=runbook.get("runbook_id") if runbook else None))

    outcome = "manual_required" if not ranked or contradictory else "completed"
    if security_flags and not ranked:
        outcome = "manual_required"
    return DiagnosisResult(
        case_id=incident.case_id,
        outcome=outcome,
        root_causes=ranked,
        remediation=remediation,
        risk_level=RiskLevel.HIGH if high_risk else RiskLevel.MEDIUM if ranked else RiskLevel.LOW,
        requires_human_review=bool(high_risk) or not ranked or contradictory,
        missing_information=missing,
        security_flags=security_flags,
        evidence_ids=sorted({item.evidence_id for candidate in ranked for item in candidate.supporting_evidence}),
    )


class TelecomPlanner:
    """Deterministic baseline planner; replaceable by any provider-neutral planner."""

    async def decide(self, *, request: str, observations: tuple[dict[str, Any], ...], step: int) -> PlannerAction:
        incident = IncidentRequest.model_validate(json.loads(request))
        successful_tools = {item.get("tool_name") for item in observations if item.get("status") == "succeeded"}
        device = incident.alarms[0].device_id if incident.alarms else (incident.metrics[0].target.split(":")[0] if incident.metrics else "unknown-device")
        interface = next((alarm.interface for alarm in incident.alarms if alarm.interface), "GigabitEthernet0/0/1")
        target = incident.metrics[0].target if incident.metrics else device
        metric = incident.metrics[0].metric if incident.metrics else "cpu_percent"

        if not successful_tools:
            return PlannerAction(kind="tool_batch", tools=[
                {"tool_name": "get_device_status", "arguments": {"device_id": device}},
                {"tool_name": "get_interface_status", "arguments": {"device_id": device, "interface": interface}},
                {"tool_name": "get_routing_neighbors", "arguments": {"device_id": device, "protocol": "bgp"}},
                {"tool_name": "get_routing_neighbors", "arguments": {"device_id": device, "protocol": "ospf"}},
                {"tool_name": "run_path_probe", "arguments": {"source": device, "destination": "synthetic-upstream.example"}},
                {"tool_name": "query_metrics", "arguments": {"target": target, "metric": metric, "time_range": "15m"}},
                {"tool_name": "list_related_alarms", "arguments": {"device_id": device, "time_window": "15m"}},
            ])

        if "search_runbook" not in successful_tools:
            hint = _fault_hint(incident)
            query = " ".join([hint or "unknown", *(alarm.alarm_type for alarm in incident.alarms), *(sample.metric for sample in incident.metrics[:5])])
            filters = {"fault_type": hint} if hint else {}
            return PlannerAction(kind="tool", tool={"tool_name": "search_runbook", "arguments": {"query": query, "filters": filters}})

        diagnosis = build_diagnosis(incident, observations)
        needs_change_review = bool(set(incident.requested_actions) & HIGH_RISK_ACTIONS)
        if needs_change_review and "request_change_approval" not in successful_tools:
            return PlannerAction(kind="tool", tool={
                "tool_name": "request_change_approval",
                "arguments": {"change": {"case_id": incident.case_id, "requested_actions": incident.requested_actions, "diagnosis": diagnosis.model_dump(mode="json")}},
            })

        if "create_ticket_draft" not in successful_tools:
            return PlannerAction(kind="tool", tool={
                "tool_name": "create_ticket_draft",
                "arguments": {"ticket": {"case_id": incident.case_id, "title": f"[Synthetic] {diagnosis.root_causes[0].label if diagnosis.root_causes else '需要人工诊断'}", "diagnosis": diagnosis.model_dump(mode="json")}},
            })

        ticket_output = next(item["output"] for item in observations if item.get("tool_name") == "create_ticket_draft" and item.get("status") == "succeeded")
        return PlannerAction(kind="finish", result={
            "case_id": incident.case_id,
            "diagnosis": diagnosis.model_dump(mode="json"),
            "ticket_draft": ticket_output,
            "data_boundary": "synthetic",
        })
