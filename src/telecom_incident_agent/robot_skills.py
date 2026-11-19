"""Robot capability contracts; simulation and ROS adapters share one interface."""
from __future__ import annotations

import time
from typing import Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field


class InspectArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    checkpoints: int = Field(default=3, ge=1, le=8)


class RobotTransport(Protocol):
    boundary: str
    def status(self) -> dict: ...
    def inspect(self, checkpoints: int, feedback: Callable, canceled: Callable) -> dict: ...


class WorkcellSimulation:
    """Logic-only workcell: no navigation, physics or hardware claims."""
    boundary = "logic_simulation"

    def __init__(self, *, delay: float = .02, unavailable: bool = False):
        self.delay = delay
        self.unavailable = unavailable
        self.busy = False

    def status(self):
        return {"state": "OFFLINE" if self.unavailable else "INSPECTING" if self.busy else "IDLE",
                "data_boundary": self.boundary}

    def inspect(self, checkpoints, feedback, canceled):
        if self.unavailable:
            return {"outcome": "unavailable", "inspected": 0, "retry_safe": True}
        if self.busy:
            return {"outcome": "busy", "inspected": 0, "retry_safe": True}
        self.busy = True
        try:
            for point in range(1, checkpoints + 1):
                time.sleep(self.delay)
                if canceled():
                    return {"outcome": "canceled", "inspected": point - 1}
                feedback({"inspected": point, "total": checkpoints})
            return {"outcome": "completed", "inspected": checkpoints}
        finally:
            self.busy = False


SKILLS = [
    {"name": "get_robot_status", "permission": "read", "parameters": {"type": "object", "additionalProperties": False}},
    {"name": "inspect_workcell", "permission": "write", "precondition": "IDLE",
     "parameters": InspectArguments.model_json_schema(), "cancelable": True,
     "replay_safe": False},
]
