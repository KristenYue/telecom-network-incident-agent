"""Read-only Agent tools for the sibling SDV platform's bounded SOME/IP API."""

from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass

from agent_runtime_platform.contracts import PlannerAction
from agent_runtime_platform.tools import ToolRegistry, ToolSpec


MAX_PAYLOAD = 4096
PROTOCOL_VERSION = 1
INTERFACE_VERSION = 1
REQUEST = 0x00
RESPONSE = 0x80
RETURN_OK = 0x00

VEHICLE_STATE_SERVICE = 0x1234
GET_SNAPSHOT_METHOD = 0x0001
VEHICLE_DIAGNOSTIC_SERVICE = 0x1236
READ_DTC_METHOD = 0x0004


@dataclass(frozen=True)
class SomeIpMessage:
    service_id: int
    method_id: int
    client_id: int
    session_id: int
    message_type: int
    return_code: int
    payload: bytes
    interface_version: int = INTERFACE_VERSION


def encode_someip(message: SomeIpMessage) -> bytes:
    if len(message.payload) > MAX_PAYLOAD:
        raise ValueError("SOME/IP payload exceeds project boundary")
    return struct.pack(
        ">HHIHHBBBB",
        message.service_id,
        message.method_id,
        8 + len(message.payload),
        message.client_id,
        message.session_id,
        PROTOCOL_VERSION,
        message.interface_version,
        message.message_type,
        message.return_code,
    ) + message.payload


def decode_someip(data: bytes) -> SomeIpMessage:
    if len(data) < 16:
        raise ValueError("SOME/IP message requires a 16-byte header")
    service, method, covered, client, session, protocol, interface, kind, code = struct.unpack(
        ">HHIHHBBBB", data[:16]
    )
    if covered < 8 or covered > MAX_PAYLOAD + 8 or len(data) != covered + 8:
        raise ValueError("SOME/IP length mismatch or payload exceeds boundary")
    if protocol != PROTOCOL_VERSION or interface != INTERFACE_VERSION:
        raise ValueError("unsupported SOME/IP protocol or interface version")
    if kind not in {REQUEST, RESPONSE, 0x81}:
        raise ValueError("unsupported SOME/IP message type")
    return SomeIpMessage(service, method, client, session, kind, code, data[16:], interface)


def decode_snapshot(payload: bytes) -> dict:
    if len(payload) != 5 or payload[3] > 1 or payload[4] > 1:
        raise ValueError("vehicle snapshot response contract mismatch")
    return {
        "speed_kph": int.from_bytes(payload[0:2], "big") / 100.0,
        "battery_percent": payload[2],
        "door_open": bool(payload[3]),
        "all_signal_groups_fresh": bool(payload[4]),
    }


def decode_dtcs(payload: bytes) -> list[dict]:
    if len(payload) < 2:
        raise ValueError("diagnostic response is truncated")
    status, count = payload[0], payload[1]
    if status != 0:
        raise RuntimeError(f"diagnostic service rejected read with status {status}")
    if len(payload) != 2 + count * 9:
        raise ValueError("diagnostic DTC record length mismatch")
    records = []
    for index in range(count):
        offset = 2 + index * 9
        flags = payload[offset + 4]
        if flags & 0xF8:
            raise ValueError("diagnostic DTC flags are malformed")
        code = int.from_bytes(payload[offset : offset + 3], "big")
        records.append({
            "code": f"0x{code:06X}",
            "severity": payload[offset + 3],
            "test_failed": bool(flags & 0x01),
            "pending": bool(flags & 0x02),
            "confirmed": bool(flags & 0x04),
            "occurrence_count": int.from_bytes(payload[offset + 5 : offset + 9], "big"),
        })
    return records


class SdvSomeIpVehicleClient:
    """Strict UDP client for the two read-only services exposed by project one."""

    def __init__(self, *, snapshot_port: int, diagnostic_port: int, host: str = "127.0.0.1",
                 timeout_seconds: float = 1.0, client_id: int = 0xA617,
                 snapshot_reference_ms: int | None = None):
        self.host = host
        self.snapshot_port = snapshot_port
        self.diagnostic_port = diagnostic_port
        self.timeout_seconds = timeout_seconds
        self.client_id = client_id
        self.snapshot_reference_ms = snapshot_reference_ms
        self._session = 0
        self._lock = threading.Lock()

    def _next_session(self) -> int:
        with self._lock:
            self._session = self._session % 0xFFFF + 1
            return self._session

    def _request(self, *, port: int, service: int, method: int, payload: bytes) -> bytes:
        session = self._next_session()
        request = SomeIpMessage(service, method, self.client_id, session, REQUEST, RETURN_OK, payload)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
            channel.settimeout(self.timeout_seconds)
            channel.sendto(encode_someip(request), (self.host, port))
            raw, peer = channel.recvfrom(16 + MAX_PAYLOAD)
        if peer[0] != self.host or peer[1] != port:
            raise ValueError("SOME/IP response source mismatch")
        response = decode_someip(raw)
        expected = (service, method, self.client_id, session)
        actual = (response.service_id, response.method_id, response.client_id, response.session_id)
        if actual != expected:
            raise ValueError("SOME/IP response identity mismatch")
        if response.message_type != RESPONSE or response.return_code != RETURN_OK:
            raise RuntimeError("SOME/IP service returned an error")
        return response.payload

    def get_vehicle_snapshot(self) -> dict:
        # The request and CAN bus timestamps must share a clock domain.  Real
        # callers use monotonic milliseconds; the reproducible C++ fixture
        # injects 1050 because its seeded bus frames use 1000..1003.
        now_ms = (int(time.monotonic() * 1000) if self.snapshot_reference_ms is None
                  else self.snapshot_reference_ms)
        result = decode_snapshot(self._request(
            port=self.snapshot_port,
            service=VEHICLE_STATE_SERVICE,
            method=GET_SNAPSHOT_METHOD,
            payload=struct.pack(">qq", now_ms, 30_000),
        ))
        return {
            "outcome": "observed",
            "service": "vehicle.state",
            "method": "GetSnapshot",
            "data_boundary": "sdv_project1_bounded_someip",
            **result,
        }

    def read_active_dtcs(self) -> dict:
        records = decode_dtcs(self._request(
            port=self.diagnostic_port,
            service=VEHICLE_DIAGNOSTIC_SERVICE,
            method=READ_DTC_METHOD,
            payload=b"\x01",
        ))
        return {
            "outcome": "observed",
            "service": "vehicle.diagnostics",
            "method": "ReadDTCInformation",
            "active_only": True,
            "dtc_count": len(records),
            "dtcs": records,
            "freeze_frame_available_over_wire": False,
            "trace_available_over_wire": False,
            "data_boundary": "sdv_project1_bounded_someip",
        }

    def registry(self) -> ToolRegistry:
        def knowledge(topic: str) -> dict:
            if topic != "dtc_triage":
                raise ValueError("unknown SDV knowledge topic")
            return {
                "document_id": "sdv-dtc-triage",
                "revision": "1",
                "text": (
                    "先确认车辆信号新鲜度，再按DTC严重度、确认状态和发生次数排序。"
                    "当前跨进程协议未暴露Freeze Frame或内部Trace，缺失证据必须标记，不推断根因。"
                ),
                "source": "project_authored_diagnostic_runbook",
            }

        return ToolRegistry([
            ToolSpec("get_sdv_vehicle_snapshot", self.get_vehicle_snapshot),
            ToolSpec("read_sdv_active_dtcs", self.read_active_dtcs),
            ToolSpec("search_sdv_diagnostic_knowledge", knowledge),
        ])


class SdvDiagnosticPlanner:
    """Deterministic integration proof: Runtime must execute all real read-only tools."""

    async def decide(self, *, request, observations, step):
        results = [item for item in observations if item.get("kind") == "tool_result"]
        names = {item.get("tool_name") for item in results}
        if "get_sdv_vehicle_snapshot" not in names:
            return PlannerAction(kind="tool", tool={"tool_name": "get_sdv_vehicle_snapshot", "arguments": {}})
        if "read_sdv_active_dtcs" not in names:
            return PlannerAction(kind="tool", tool={"tool_name": "read_sdv_active_dtcs", "arguments": {}})
        if "search_sdv_diagnostic_knowledge" not in names:
            return PlannerAction(kind="tool", tool={
                "tool_name": "search_sdv_diagnostic_knowledge", "arguments": {"topic": "dtc_triage"}
            })
        return PlannerAction(kind="finish", result={
            "planner_mode": "deterministic_integration_proof",
            "summary": "已读取项目一真实车辆状态和DTC；当前证据可用于分诊，但协议未提供Freeze Frame/Trace，不能直接断言根因。",
            "evidence": results,
            "data_boundary": "sdv_project1_bounded_someip",
        })
