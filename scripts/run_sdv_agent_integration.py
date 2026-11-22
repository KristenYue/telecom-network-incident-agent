"""Launch project one's real services and prove Agent Runtime calls them."""

import argparse
import json
import socket
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from telecom_incident_agent.adapter import TelecomIncidentRuntimeAdapter
from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.sdv_services import SdvDiagnosticPlanner, SdvSomeIpVehicleClient


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def launch(server: Path, port: int, mode: str) -> subprocess.Popen:
    process = subprocess.Popen(
        [str(server), str(port), mode, "", "1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    deadline = time.monotonic() + 5
    lines = []
    while time.monotonic() < deadline:
        line = process.stdout.readline().strip()
        if line:
            lines.append(line)
        if line.startswith("READY "):
            return process
        if process.poll() is not None:
            break
    process.kill()
    raise RuntimeError(f"{mode} server did not become ready: {lines}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdv-server", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--root", default=".runtime/sdv-agent-integration")
    args = parser.parse_args()
    server = Path(args.sdv_server).resolve()
    if not server.is_file():
        raise FileNotFoundError(server)

    root = Path(args.root) / str(uuid4())
    root.mkdir(parents=True, exist_ok=True)
    snapshot_port, diagnostic_port = free_udp_port(), free_udp_port()
    while diagnostic_port == snapshot_port:
        diagnostic_port = free_udp_port()
    processes = []
    try:
        processes.append(launch(server, snapshot_port, "snapshot"))
        processes.append(launch(server, diagnostic_port, "diagnostic"))
        client = SdvSomeIpVehicleClient(
            snapshot_port=snapshot_port, diagnostic_port=diagnostic_port,
            timeout_seconds=2.0, snapshot_reference_ms=1_050,
        )
        adapter = TelecomIncidentRuntimeAdapter(checkpoint_path=root / "runtime.sqlite3")
        runtime = adapter._build_runtime(SdvDiagnosticPlanner(), client.registry())
        result = run_non_yielding(runtime.run(
            task_id=str(uuid4()), request="读取车辆状态与活动DTC，依据现有证据给出安全分诊"
        ))
        if str(result.status) != "completed":
            raise AssertionError(
                f"runtime ended as {result.status}: {result.model_dump(mode='json')}"
            )
        result_json = result.model_dump(mode="json")
        evidence = result_json["result"]["evidence"]
        outputs = {item["tool_name"]: item["output"] for item in evidence}
        snapshot = outputs["get_sdv_vehicle_snapshot"]
        diagnostics = outputs["read_sdv_active_dtcs"]
        assert snapshot["speed_kph"] == 123.45 and snapshot["battery_percent"] == 75
        assert snapshot["all_signal_groups_fresh"] is True
        assert diagnostics["dtc_count"] == 10
        assert diagnostics["dtcs"][0]["code"] == "0xC40001"
        for process in processes:
            if process.wait(timeout=5) != 0:
                raise RuntimeError("SDV service exited unsuccessfully")
        report = {
            "schema": "sdv-agent-integration-evidence/v1",
            "passed": True,
            "data_boundary": "cross_repo_localhost_udp_bounded_someip",
            "source_repository": "KristenYue/sdv-communication-integration-lab",
            "services": ["vehicle.state/GetSnapshot", "vehicle.diagnostics/ReadDTCInformation"],
            "read_only": True,
            "freeze_frame_available_over_wire": False,
            "trace_available_over_wire": False,
            "snapshot": snapshot,
            "diagnostics": diagnostics,
            "runtime": result_json,
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": True, "speed_kph": snapshot["speed_kph"],
                          "dtc_count": diagnostics["dtc_count"]}))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            remaining = process.stdout.read() if process.stdout is not None else ""
            if remaining.strip():
                print(remaining.strip())


if __name__ == "__main__":
    main()
