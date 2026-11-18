"""Run the live LLM planner against the C++ simulator and save a public-safe trace."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
EDGE_SOURCE = ROOT.parent / "edge-device-verification-lab" / "src"
for source in (ROOT / "src", EDGE_SOURCE):
    if source.exists() and str(source) not in sys.path:
        sys.path.insert(0, str(source))

from edge_validation.client import DeviceClient
from telecom_incident_agent.adapter import TelecomIncidentRuntimeAdapter


DEFAULT_REQUEST = "帮我分析设备 A 为什么无法启动，并提供故障原因和下一步处理建议。"


async def run(args) -> dict:
    if not (os.getenv("TELECOM_MODEL_API_KEY") or os.getenv("FSO_MODEL_API_KEY")):
        os.environ["TELECOM_MODEL_API_KEY"] = getpass.getpass("Model API key (not saved): ")
    client = DeviceClient(port=args.port, timeout=2)
    if args.prepare_interlock:
        client.power_on()
        client.inject_fault("interlock_open")
        client.home()
    adapter = TelecomIncidentRuntimeAdapter(checkpoint_path=ROOT / args.checkpoint)
    result = await adapter.diagnose_equipment_agent(
        client,
        request=args.request,
        task_id=f"LIVE-{uuid4().hex[:12].upper()}",
        may_send=lambda: True,
    )
    document = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "execution": "live_model_and_cpp_simulator",
        "credentials_recorded": False,
        "request": args.request,
        "result": result.model_dump(mode="json"),
    }
    if result.status != "completed":
        raise SystemExit(json.dumps(document, ensure_ascii=False, indent=2))
    evidence = result.result or {}
    if evidence.get("agent_mode") != "model_driven" or result.tool_call_count != 2:
        raise SystemExit("live verification requires model-driven planning and two Runtime tool calls")
    if [row.get("runbook_id") for row in evidence.get("evidence", []) if row.get("source") == "runbook"] != [
        "sim-interlock-001"
    ]:
        raise SystemExit("live verification did not produce the expected interlock evidence")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--request", default=DEFAULT_REQUEST)
    parser.add_argument("--prepare-interlock", action="store_true")
    parser.add_argument("--checkpoint", default=".runtime/industrial-llm-live.sqlite3")
    parser.add_argument("--output", default="docs/industrial-agent-live.json")
    args = parser.parse_args()
    document = asyncio.run(run(args))
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(document, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
