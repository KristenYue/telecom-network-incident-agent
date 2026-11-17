"""Run a deterministic task against the C++ simulation over its TCP protocol."""

import json
from uuid import uuid5


PREPARE = (
    ("power_on", {}),
    ("home", {}),
    ("calibrate", {}),
    ("load_profile", {"name": "device-task-demo", "sample_count": 40}),
)
WRITES = dict((*PREPARE, ("start_run", {}), ("emergency_stop", {})))


def emit(**event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def run(client, task_id, scenario, allow_write, emit=emit, may_send=lambda: True):
    from edge_validation.client import DeviceClientError

    if scenario != "status" and not allow_write:
        emit(task_id=str(task_id), layer="orchestrator", code="WRITE_NOT_AUTHORIZED")
        return 2
    commands = {
        "status": ("status",),
        "run": ("status", *dict(PREPARE), "start_run", "status"),
        "interlock": ("status", "emergency_stop", "start_run"),
    }[scenario]
    for index, command in enumerate(commands):
        request_id = str(uuid5(task_id, f"{scenario}:{index}:{command}"))
        context = {"task_id": str(task_id), "request_id": request_id, "command": command}
        if not may_send():
            emit(**context, layer="orchestrator", code="LEASE_EXPIRED")
            return 3
        try:
            response = client.command(command, WRITES.get(command), request_id=request_id)
        except DeviceClientError as exc:
            emit(**context, layer="transport", code="OUTCOME_UNKNOWN", error=str(exc))
            try:
                state = client.status()
                emit(task_id=str(task_id), layer="reconciliation", observed=state.model_dump(mode="json"))
            except DeviceClientError as status_error:
                emit(task_id=str(task_id), layer="reconciliation", error=str(status_error))
            return 3
        emit(**context, layer="device", response=response.model_dump(mode="json"))
        if not response.ok:
            return 0 if scenario == "interlock" and command == "start_run" and response.code == "SAFETY_INTERLOCK" else 4
    return 4 if scenario == "interlock" else 0
