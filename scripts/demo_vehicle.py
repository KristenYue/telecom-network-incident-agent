"""Actual local simulation and shared Runtime approval flow; no live LLM claim."""
import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from telecom_incident_agent.adapter import TelecomIncidentRuntimeAdapter
from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.vehicle import VehiclePlanner, VehicleService


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--root", default=".runtime/vehicle")
    p.add_argument("--live-model", action="store_true")
    args = p.parse_args()
    root = Path(args.root)/str(uuid4())
    root.mkdir(parents=True)
    service = VehicleService(root/"signals.sqlite3", capacity=2)
    signals = {"speed_kph": 0, "battery_percent": 62, "door_open": False,
               "tire_kpa": {"front_left": 190, "front_right": 240, "rear_left": 240, "rear_right": 240}}
    service.ingest(1, signals)
    adapter = TelecomIncidentRuntimeAdapter(checkpoint_path=root/"runtime.sqlite3")
    def planner(climate=False):
        if args.live_model:
            from telecom_incident_agent.industrial_llm import IndustrialModelClient
            from telecom_incident_agent.vehicle_llm import VehicleLLMPlanner
            return VehicleLLMPlanner(IndustrialModelClient.from_environment(), allow_climate=climate)
        return VehiclePlanner(temperature=22.0 if climate else None)
    diagnosis = run_non_yielding(adapter._build_runtime(planner(), service.registry()).run(task_id=str(uuid4()), request="解释胎压告警"))
    runtime = adapter._build_runtime(planner(True), service.registry())
    pending = run_non_yielding(runtime.run(task_id=str(uuid4()), request="将模拟空调调至22度"))
    assert str(pending.status) == "waiting_review"
    result = run_non_yielding(runtime.resume(pending.run_id, approved=True))
    assert str(result.status) == "completed"
    service.ingest(2, signals, event_time=time.time()-120, online=False)
    flushed = service.reconnect()
    latest = service.latest()
    assert latest["sequence"] == 1  # delayed stale sample must not overwrite fresher state
    report = {"data_boundary": "vehicle_simulation", "planner": "live_model" if args.live_model else "rule_baseline", "live_llm": args.live_model,
              "diagnosis": diagnosis.model_dump(mode="json"), "approval": pending.model_dump(mode="json"),
              "control": result.model_dump(mode="json"), "reconnect": flushed, "latest": latest}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"approval": str(pending.status), "control": str(result.status), "flushed": flushed["flushed"]}))


if __name__ == "__main__":
    main()
