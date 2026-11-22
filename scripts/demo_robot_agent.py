"""Save actual task, progress and shared Runtime evidence. Default requires live LLM."""
import argparse
import json
import platform
import time
from pathlib import Path
from uuid import uuid4

from telecom_incident_agent.robot_skills import WorkcellSimulation
from telecom_incident_agent.robot_tasks import RobotTasks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true", help="Explicit rule planner, NOT live model evidence")
    parser.add_argument("--cancel-after", type=int, choices=range(1, 8))
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--ros2", action="store_true", help="Use actual ROS2 Service/Action, no fallback")
    parser.add_argument("--output", required=True)
    parser.add_argument("--data-dir", default=".runtime/robot-demo")
    args = parser.parse_args()
    if args.ros2:
        from telecom_incident_agent.robot_ros import RosWorkcellTransport
        transport = RosWorkcellTransport()
    else:
        transport = WorkcellSimulation(delay=.1, unavailable=args.offline)
    service = RobotTasks(args.data_dir, transport=transport)
    started = time.perf_counter()
    try:
        task = service.submit("查询工作站状态，执行三点巡检，并根据真实结果生成报告。", str(uuid4()), model=not args.baseline)
        deadline = time.monotonic() + 240
        canceled = False
        while task["state"] in ("queued", "running"):
            events = service.events(task["id"])
            if args.cancel_after and not canceled and any(e["event"] == "progress" and e["data"]["inspected"] >= args.cancel_after for e in events):
                service.cancel(task["id"])
                canceled = True
            if time.monotonic() > deadline:
                raise TimeoutError("robot demo deadline")
            time.sleep(.01)
            task = service.get(task["id"])
        report = {"platform": platform.platform(), "elapsed_ms": (time.perf_counter()-started)*1000,
                  "planner": "rule_baseline" if args.baseline else "live_model",
                  "task": task, "events": service.events(task["id"]), "credentials_recorded": False}
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"state": task["state"], "planner": report["planner"], "output": str(out)}, ensure_ascii=False))
        if task["state"] not in ("completed", "canceled") and not args.offline:
            raise SystemExit(1)
    finally:
        service.close()


if __name__ == "__main__":
    main()
