"""Deterministic synthetic telecom tools with contracts and failure injection."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agent_runtime_platform.tools import ToolExecutionContext, ToolRegistry, ToolSpec

from .models import DEVICE_PATTERN, INTERFACE_PATTERN, IncidentRequest
from .runbooks import RUNBOOKS
from .security import sanitize_untrusted_text


class DeviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(pattern=DEVICE_PATTERN)


class InterfaceInput(DeviceInput):
    interface: str = Field(pattern=INTERFACE_PATTERN)


class RoutingInput(DeviceInput):
    protocol: Literal["bgp", "ospf"]


class PathProbeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=1, max_length=255)


class MetricsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=1, max_length=150)
    metric: str = Field(min_length=1, max_length=100)
    time_range: str = Field(default="15m", pattern=r"^\d+(m|h|d)$")


class RelatedAlarmInput(DeviceInput):
    time_window: str = Field(default="15m", pattern=r"^\d+(m|h)$")


class RunbookSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=1000)
    filters: dict[str, str] = Field(default_factory=dict)


class ToolTimeoutError(TimeoutError):
    pass


class ToolConnectionError(ConnectionError):
    pass


class ToolRateLimitError(RuntimeError):
    pass


class ToolServerError(RuntimeError):
    pass


def _metric(incident: IncidentRequest, name: str, *, target: str | None = None) -> float | None:
    values = [
        sample.value
        for sample in incident.metrics
        if sample.metric == name and (target is None or sample.target == target)
    ]
    return values[-1] if values else None


class SyntheticTelecomTools:
    """Tool handlers are bound to one immutable incident request."""

    def __init__(self, incident: IncidentRequest, *, timeout_seconds: float = 0.2) -> None:
        self.incident = incident
        self.timeout_seconds = timeout_seconds
        self.write_ledger: dict[str, dict[str, Any]] = {}

    async def _execute(self, name: str, operation: Callable[[], Any]) -> Any:
        # These fixtures never perform network I/O.  A timeout is injected as a
        # typed result immediately, which keeps offline tests deterministic and
        # avoids pretending that a local sleep measures a real device timeout.
        mode = self.incident.failure_injections.get(name)
        if mode == "timeout":
            raise ToolTimeoutError(
                f"synthetic timeout after {self.timeout_seconds}s: {name}"
            )
        if mode == "connection":
            raise ToolConnectionError(f"synthetic connection failure: {name}")
        if mode == "rate_limit":
            raise ToolRateLimitError(f"synthetic 429 rate limit: {name}")
        if mode == "server_error":
            raise ToolServerError(f"synthetic 5xx response: {name}")
        if mode == "invalid_json":
            raise ValueError(f"synthetic invalid payload: {name}")
        if mode == "semantic_error":
            raise ValueError(f"synthetic semantic validation error: {name}")
        value = operation()
        if mode == "missing_field":
            raise ValueError(f"synthetic response missing required field: {name}")
        if mode == "contradictory" and isinstance(value, dict):
            value["synthetic_contradiction"] = True
            if "oper_status" in value:
                value["oper_status"] = "up" if value["oper_status"] == "down" else "down"
        return value

    async def get_device_status(self, device_id: str) -> dict[str, Any]:
        parsed = DeviceInput(device_id=device_id)
        return await self._execute("get_device_status", lambda: {
            "device_id": parsed.device_id,
            "online": not any(a.device_id == parsed.device_id and a.alarm_type == "device_down" for a in self.incident.alarms),
            "cpu_percent": _metric(self.incident, "cpu_percent", target=parsed.device_id) or 32.0,
            "memory_percent": _metric(self.incident, "memory_percent", target=parsed.device_id) or 45.0,
            "device_time": datetime.now(timezone.utc).isoformat(),
            "software_version": "synthetic-os-1.0",
            "last_restart": "2026-10-01T00:00:00+00:00",
            "synthetic": True,
        })

    async def get_interface_status(self, device_id: str, interface: str) -> dict[str, Any]:
        parsed = InterfaceInput(device_id=device_id, interface=interface)
        alarms = [a for a in self.incident.alarms if a.device_id == parsed.device_id and a.interface == parsed.interface]
        target = f"{parsed.device_id}:{parsed.interface}"
        link_down = any(a.alarm_type in {"link_down", "interface_down"} for a in alarms)
        return await self._execute("get_interface_status", lambda: {
            "device_id": parsed.device_id,
            "interface": parsed.interface,
            "oper_status": "down" if link_down else "up",
            "admin_status": "up",
            "rx_power_dbm": _metric(self.incident, "rx_power_dbm", target=target) or -8.0,
            "ber": _metric(self.incident, "ber", target=target) or 0.0,
            "packet_loss_percent": _metric(self.incident, "packet_loss_percent", target=target) or 0.0,
            "utilization_percent": _metric(self.incident, "utilization_percent", target=target) or 20.0,
            "last_change": max((a.observed_at for a in alarms), default=datetime.now(timezone.utc)).isoformat(),
            "synthetic": True,
        })

    async def get_routing_neighbors(self, device_id: str, protocol: str) -> dict[str, Any]:
        parsed = RoutingInput(device_id=device_id, protocol=protocol)
        bad_types = {"bgp": {"bgp_down", "bgp_neighbor_down"}, "ospf": {"ospf_down", "ospf_adjacency"}}[parsed.protocol]
        unhealthy = any(a.device_id == parsed.device_id and a.alarm_type in bad_types for a in self.incident.alarms)
        state = "idle" if parsed.protocol == "bgp" and unhealthy else "down" if unhealthy else "established" if parsed.protocol == "bgp" else "full"
        return await self._execute("get_routing_neighbors", lambda: {
            "device_id": parsed.device_id, "protocol": parsed.protocol,
            "neighbors": [{"peer": "192.0.2.1", "state": state, "last_change_seconds": 180 if unhealthy else 86400}],
            "synthetic": True,
        })

    async def run_path_probe(self, source: str, destination: str) -> dict[str, Any]:
        parsed = PathProbeInput(source=source, destination=destination)
        loss = _metric(self.incident, "packet_loss_percent") or 0.0
        latency = _metric(self.incident, "latency_ms") or 12.0
        jitter = _metric(self.incident, "jitter_ms") or 2.0
        dependency_failed = any(a.alarm_type in {"dns_timeout", "upstream_failure"} for a in self.incident.alarms)
        return await self._execute("run_path_probe", lambda: {
            "source": parsed.source, "destination": parsed.destination,
            "reachable": not dependency_failed and loss < 100,
            "packet_loss_percent": loss, "latency_ms": latency, "jitter_ms": jitter,
            "hops": [{"hop": 1, "node": parsed.source, "latency_ms": min(latency, 5.0)}, {"hop": 2, "node": parsed.destination, "latency_ms": latency}],
            "synthetic": True,
        })

    async def query_metrics(self, target: str, metric: str, time_range: str) -> dict[str, Any]:
        parsed = MetricsInput(target=target, metric=metric, time_range=time_range)
        points = [sample.model_dump(mode="json") for sample in self.incident.metrics if sample.target == parsed.target and sample.metric == parsed.metric]
        return await self._execute("query_metrics", lambda: {
            "target": parsed.target, "metric": parsed.metric, "time_range": parsed.time_range,
            "points": points, "synthetic": True,
        })

    async def list_related_alarms(self, device_id: str, time_window: str) -> dict[str, Any]:
        parsed = RelatedAlarmInput(device_id=device_id, time_window=time_window)
        alarms = [alarm.model_dump(mode="json") for alarm in self.incident.alarms]
        return await self._execute("list_related_alarms", lambda: {
            "device_id": parsed.device_id, "time_window": parsed.time_window,
            "alarms": alarms, "count": len(alarms), "synthetic": True,
        })

    async def search_runbook(self, query: str, filters: dict[str, str]) -> dict[str, Any]:
        parsed = RunbookSearchInput(query=query, filters=filters)
        safe_query, flags = sanitize_untrusted_text(parsed.query)
        fault_filter = parsed.filters.get("fault_type")
        allowed = set(self.incident.allowed_runbooks)
        scored: list[tuple[int, dict[str, Any]]] = []
        for runbook in RUNBOOKS:
            if allowed and runbook["runbook_id"] not in allowed:
                continue
            if fault_filter and runbook["fault_type"] != fault_filter:
                continue
            haystack = " ".join([runbook["title"], runbook["fault_type"], *runbook["keywords"]]).lower()
            score = sum(1 for token in safe_query.lower().replace("_", " ").split() if token in haystack)
            if score or fault_filter == runbook["fault_type"]:
                scored.append((score + 1, runbook))
        results = [item for _, item in sorted(scored, key=lambda pair: (-pair[0], pair[1]["runbook_id"]))[:5]]
        return await self._execute("search_runbook", lambda: {
            "query": safe_query, "results": results, "security_flags": flags,
            "no_answer": not results, "synthetic": True,
        })

    async def create_ticket_draft(self, ticket: dict[str, Any], runtime_context: ToolExecutionContext) -> dict[str, Any]:
        key = runtime_context.idempotency_key
        def create() -> dict[str, Any]:
            if key not in self.write_ledger:
                self.write_ledger[key] = {
                    "ticket_id": f"TKT-{uuid4().hex[:10].upper()}",
                    "status": "draft", "ticket": ticket,
                    "idempotency_key": key, "synthetic": True,
                }
            return self.write_ledger[key]
        return await self._execute("create_ticket_draft", create)

    async def request_change_approval(self, change: dict[str, Any], runtime_context: ToolExecutionContext) -> dict[str, Any]:
        key = runtime_context.idempotency_key
        def create() -> dict[str, Any]:
            if key not in self.write_ledger:
                self.write_ledger[key] = {
                    "approval_id": f"APR-{uuid4().hex[:10].upper()}",
                    "status": "approved_for_draft_only", "change": change,
                    "idempotency_key": key, "execution_performed": False,
                    "synthetic": True,
                }
            return self.write_ledger[key]
        return await self._execute("request_change_approval", create)

    def registry(self) -> ToolRegistry:
        return ToolRegistry([
            ToolSpec("get_device_status", self.get_device_status, permission="read"),
            ToolSpec("get_interface_status", self.get_interface_status, permission="read"),
            ToolSpec("get_routing_neighbors", self.get_routing_neighbors, permission="read"),
            ToolSpec("run_path_probe", self.run_path_probe, permission="compute", replay_safe=True),
            ToolSpec("query_metrics", self.query_metrics, permission="read"),
            ToolSpec("list_related_alarms", self.list_related_alarms, permission="read"),
            ToolSpec("search_runbook", self.search_runbook, permission="read"),
            ToolSpec("create_ticket_draft", self.create_ticket_draft, permission="write", replay_safe=True, inject_context=True),
            ToolSpec("request_change_approval", self.request_change_approval, permission="dangerous", replay_safe=True, inject_context=True),
        ])
