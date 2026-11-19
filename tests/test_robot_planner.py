import pytest
from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.robot_tasks import RobotPlanner


class ModelStub:
    def __init__(self, action):
        self.action = action
    def decide(self, **kwargs):
        return self.action


def observation(name, output):
    return {"kind":"tool_result", "status":"succeeded", "tool_name":name, "output":output}


def test_only_explicitly_retry_safe_failure_can_be_replanned():
    action = {"kind":"tool", "tool_name":"inspect_workcell", "arguments":{"checkpoints":2}}
    planner = RobotPlanner(ModelStub(action))
    idle = observation("get_robot_status", {"state":"IDLE"})
    busy = observation("inspect_workcell", {"outcome":"busy", "retry_safe":True})
    result = run_non_yielding(planner.decide(request="inspect",observations=(idle,busy,idle),step=3))
    assert result.tool.tool_name == "inspect_workcell"
    unknown = observation("inspect_workcell", {"outcome":"result_unknown", "retry_safe":False})
    with pytest.raises(ValueError):
        run_non_yielding(planner.decide(request="inspect",observations=(idle,unknown,idle),step=3))
    with pytest.raises(ValueError):
        run_non_yielding(planner.decide(request="inspect",observations=(idle,busy,idle,busy,idle),step=5))


def test_failed_tool_cannot_become_success_evidence():
    planner = RobotPlanner(ModelStub({"kind":"finish", "summary":"completed"}))
    failed = {"kind":"tool_result", "status":"failed_closed", "tool_name":"inspect_workcell", "output":{"outcome":"completed"}}
    with pytest.raises(ValueError):
        run_non_yielding(planner.decide(request="inspect",observations=(failed,),step=1))
