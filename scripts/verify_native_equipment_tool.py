"""Run the registered native retrieval tool; synthetic device, no LLM claim."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.industrial_diagnosis import diagnostic_tools


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    args = p.parse_args()
    registry = diagnostic_tools(lambda: {}, lambda: True)
    call = registry.execute("search_equipment_runbook", {"fault": "interlock"})
    result = run_non_yielding(call) if sys.platform == "win32" else asyncio.run(call)
    assert result["retrieval_backend"] == "native_onnx"
    assert result["runbook_id"] == "sim-interlock-001"
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"tool": "search_equipment_runbook", "result": result,
                               "llm_called": False, "device_boundary": "simulation"},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print("Native retrieval tool verified")


if __name__ == "__main__":
    main()
