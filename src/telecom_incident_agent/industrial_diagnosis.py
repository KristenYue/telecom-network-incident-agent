"""Read-only diagnosis for the simulated industrial equipment adapter."""

from agent_runtime_platform.contracts import PlannerAction
from agent_runtime_platform.tools import ToolRegistry, ToolSpec
import os
from functools import lru_cache

from .runbooks import retrieve_runbooks


RUNBOOKS = {
    "interlock": ("sim-interlock-001", "核对联锁输入和急停状态，保留现场证据后交由人工处置"),
    "transport": ("sim-transport-001", "检查模拟器进程与 TCP 通路，恢复读取后再判断设备状态"),
    "device_error": ("sim-device-error-001", "检查设备事件与校准记录，确认故障来源后再决定恢复操作"),
    "normal": ("sim-status-001", "记录当前状态，无需变更设备"),
    "inventory_alert": ("shelf-inventory-001", "核对库存遥测和现场称重记录，再安排补货"),
    "telemetry_unavailable": ("shelf-telemetry-001", "核对云端接收时间和最近上线状态"),
    "shelf_alert": ("shelf-alert-001", "排查货架现场告警及其传感器读数"),
}

EQUIPMENT_CORPUS = tuple(
    {"runbook_id": runbook_id, "fault_type": fault, "revision": "1",
     "instruction": instruction, "title": instruction, "keywords": [fault]}
    for fault, (runbook_id, instruction) in RUNBOOKS.items()
)


@lru_cache(maxsize=2)
def native_equipment_index(model_path, tokenizer_path):
    from edge_ai_sdk.embedding import NativeEmbedder
    from .knowledge import KnowledgeIndex
    documents = [{"document_id": r["runbook_id"], "version": r["revision"],
                  "device_family": "simulated-equipment", "fault_type": r["fault_type"],
                  "title": r["title"], "text": r["instruction"],
                  "source": "project://equipment/" + r["runbook_id"], "data_boundary": "simulation"}
                 for r in EQUIPMENT_CORPUS]
    return KnowledgeIndex(documents, embedder=NativeEmbedder(model_path, tokenizer_path))


def fault_from(snapshot):
    if not snapshot.get("reachable"):
        if snapshot.get("source") == "smart_shelf_cloud":
            return "telemetry_unavailable"
        return "transport"
    if snapshot["state"] in {"LOW_STOCK", "OUT_OF_STOCK"}:
        return "inventory_alert"
    if snapshot.get("source") == "smart_shelf_cloud" and snapshot["state"] != "NORMAL":
        return "shelf_alert"
    if snapshot["state"] == "E_STOP" or snapshot["data"].get("interlock_open") == "true":
        return "interlock"
    if snapshot["state"] in {"ERROR", "WARNING"}:
        return "device_error"
    return "normal"


def diagnostic_tools(read, may_send, report=None):
    async def read_snapshot():
        if not may_send():
            return {"reachable": False, "code": "LEASE_EXPIRED"}
        return read()

    async def search_equipment_runbook(fault: str):
        if fault not in RUNBOOKS:
            raise ValueError("unknown simulated equipment fault")
        model_path = os.getenv("EDGE_AI_MODEL_PATH")
        tokenizer_path = os.getenv("EDGE_AI_TOKENIZER_PATH")
        if model_path or tokenizer_path:
            if not model_path or not tokenizer_path:
                raise ValueError("native retrieval requires model and tokenizer paths")
            index = native_equipment_index(model_path, tokenizer_path)
            result = index.search(RUNBOOKS[fault][1], fault_type=fault, mode="dense", top_k=1)
            rows = result["results"]
            if result.get("dense_status") != "available" or not rows:
                raise RuntimeError("native equipment retrieval unavailable")
            row = rows[0]
            return {"runbook_id": row["document_id"], "revision": row["version"],
                    "instruction": row["text"], "retrieval_backend": "native_onnx",
                    "citation": row["chunk_id"], "sha256": row["sha256"]}
        return retrieve_runbooks(EQUIPMENT_CORPUS, fault, fault)[0]

    tools = [
        ToolSpec("read_equipment_snapshot", read_snapshot, permission="read"),
        ToolSpec("search_equipment_runbook", search_equipment_runbook, permission="read"),
    ]
    if report is not None:
        tools.append(ToolSpec("generate_equipment_report", report.generate, permission="read"))
    return ToolRegistry(tools)


class EquipmentPlanner:
    def __init__(self, generate_report=False):
        self.generate_report = generate_report

    async def decide(self, *, request, observations, step):
        successful = {
            item["tool_name"]: item["output"] for item in observations if item["status"] == "succeeded"
        }
        snapshot = successful.get("read_equipment_snapshot")
        if step == 0:
            return PlannerAction(kind="tool", tool={"tool_name": "read_equipment_snapshot", "arguments": {}})
        if snapshot is None:
            return PlannerAction(kind="finish", result={"outcome": "manual_required", "data_boundary": request})
        fault = fault_from(snapshot)
        runbook = successful.get("search_equipment_runbook")
        if step == 1:
            return PlannerAction(kind="tool", tool={
                "tool_name": "search_equipment_runbook", "arguments": {"fault": fault},
            })
        evidence = {
            "outcome": "normal" if fault == "normal" and runbook else "manual_required",
            "fault": fault,
            "snapshot": snapshot,
            "runbook": runbook,
            "data_boundary": request,
        }
        if self.generate_report and step == 2 and runbook:
            return PlannerAction(kind="tool", tool={
                "tool_name": "generate_equipment_report", "arguments": {"evidence": evidence},
            })
        if self.generate_report:
            evidence["model_report"] = successful.get("generate_equipment_report", {"status": "unavailable"})
        return PlannerAction(kind="finish", result=evidence)
