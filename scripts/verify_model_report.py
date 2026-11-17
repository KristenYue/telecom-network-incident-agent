"""Run the simulated-equipment model report through the configured live provider."""

import argparse
import asyncio
import getpass
import os
from pathlib import Path
from uuid import uuid4

from edge_validation.client import DeviceClient
from telecom_incident_agent.adapter import TelecomIncidentRuntimeAdapter


async def verify(port):
    if not os.getenv("TELECOM_MODEL_API_KEY"):
        os.environ["TELECOM_MODEL_API_KEY"] = getpass.getpass("Model API key: ")
    adapter = TelecomIncidentRuntimeAdapter(checkpoint_path=Path(".runtime/model-verification.sqlite3"))
    result = await adapter.diagnose_equipment(DeviceClient(port=port), task_id=str(uuid4()), may_send=lambda: True)
    evidence = result.result or {}
    if evidence.get("model_report", {}).get("status") != "generated" or evidence["snapshot"].get("reachable") is not True:
        raise SystemExit("Live verification failed: both device telemetry and provider-generated report are required")
    if result.tool_call_count != 3:
        raise SystemExit("Live verification failed: expected telemetry, retrieval and model trace")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18765)
    asyncio.run(verify(parser.parse_args().port))
