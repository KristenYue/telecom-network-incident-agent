"""Actual LLM -> C++ device -> native ONNX knowledge tool -> final report."""
import argparse
import hashlib
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from edge_validation.client import DeviceClient
from telecom_incident_agent.adapter import TelecomIncidentRuntimeAdapter
from telecom_incident_agent.compat import run_non_yielding


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulator", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    for key in ("EDGE_AI_MODEL_PATH", "EDGE_AI_TOKENIZER_PATH"):
        if not os.getenv(key):
            raise ValueError(f"{key} required; no lexical fallback")
    root = Path(".runtime/native-llm")/str(uuid4())
    root.mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (root/"simulator.log").open("w") as log:
        process = subprocess.Popen([args.simulator,"--port",str(port),"--log",str(root/"events.jsonl")], stdout=log, stderr=log)
        try:
            client = DeviceClient(port=port, timeout=2)
            deadline = time.monotonic()+10
            while True:
                try:
                    client.status()
                    break
                except Exception:
                    if process.poll() is not None or time.monotonic()>deadline:
                        raise RuntimeError("C++ simulator startup failed")
                    time.sleep(.1)
            client.power_on()
            client.inject_fault("interlock_open")
            client.home()
            adapter = TelecomIncidentRuntimeAdapter(checkpoint_path=root/"runtime.sqlite3")
            result = run_non_yielding(adapter.diagnose_equipment_agent(client,
                request="分析设备A无法启动的原因，依据设备观测和运行手册给出处置建议。",
                task_id=str(uuid4()), may_send=lambda: True))
            trace = result.model_dump(mode="json")
            native = [c["output"] for step in trace["steps"] for c in step["tool_calls"]
                      if c["tool_name"] == "search_equipment_runbook" and c["status"] == "succeeded"]
            if str(result.status)!="completed" or not native or native[0].get("retrieval_backend")!="native_onnx":
                raise RuntimeError("live native chain did not complete; no success evidence written")
            report = {"execution":"live_llm_cpp_device_native_onnx", "data_boundary":"simulated_device_pretrained_encoder",
                      "credentials_recorded":False,"model_sha256":hashlib.sha256(Path(os.environ["EDGE_AI_MODEL_PATH"]).read_bytes()).hexdigest(),
                      "result":trace}
            output = Path(args.output)
            output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
            print(json.dumps({"status":str(result.status),"tool_calls":result.tool_call_count,"native_retrieval":True}))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
