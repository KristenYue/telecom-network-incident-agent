"""Three actual FRR captures; exits nonzero unless session loss/recovery observed.

Run only against deploy/network_lab; no remote/production router mutations.
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.network_evidence import NetworkCollector, as_incident
from telecom_incident_agent.service import IncidentService

COMPOSE = ["docker", "compose", "-f", "deploy/network_lab/compose.yaml"]


def command(*args):
    return subprocess.run(COMPOSE + list(args), check=True, capture_output=True, text=True, timeout=30)


def established(snapshot):
    peers = snapshot["bgp"].get("ipv4Unicast", {}).get("peers", {})
    return bool(peers) and all(p.get("state") == "Established" for p in peers.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/evidence/network-live.json")
    args = parser.parse_args()
    collector = NetworkCollector(os.getenv("TELECOM_NETWORK_GATEWAY", "http://127.0.0.1:8092"),
                                 os.environ["TELECOM_NETWORK_TOKEN"])
    output = Path(args.output)
    service = IncidentService(output.parent / ".network-runtime")
    rows = []

    def collect(label, expected):
        deadline = time.monotonic() + 35
        while True:
            try:
                snapshot = collector.capture()
                if established(snapshot) == expected:
                    break
            except (OSError, ValueError):
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("FRR did not reach expected state: " + label)
            time.sleep(.5)
        started = time.perf_counter()
        record = run_non_yielding(service.create(as_incident(snapshot)))
        if record["runtime_status"] != "completed":
            raise RuntimeError("network diagnosis did not complete")
        rows.append({"scenario": label, "snapshot": snapshot, "record": record,
                     "diagnosis_ms": (time.perf_counter() - started) * 1000})

    # Gateway shares the r1 FRR binary and VTY sockets. Start separately to leave
    # upstream FRR init/daemon supervision intact.
    command("exec", "-d", "r1", "python3", "/opt/evidence/gateway.py")
    try:
        collect("established", True)
        command("exec", "-T", "r1", "vtysh", "-c", "configure terminal", "-c", "router bgp 65001",
                "-c", "neighbor 10.70.0.12 shutdown")
        collect("neighbor_shutdown", False)
    finally:
        command("exec", "-T", "r1", "vtysh", "-c", "configure terminal", "-c", "router bgp 65001",
                "-c", "no neighbor 10.70.0.12 shutdown")
    collect("recovered", True)
    faulty = rows[1]["record"]["result"]["result"]["diagnosis"]["root_causes"]
    if not faulty or faulty[0]["fault_type"] != "bgp_neighbor_down":
        raise RuntimeError("fault was not diagnosed")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"scope": "real FRR processes in isolated virtual network; deterministic planner; no LLM claim",
                                  "scenarios": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Verified FRR Established -> neighbor shutdown -> Established; evidence:", output)


if __name__ == "__main__":
    main()
