import pytest
from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.vehicle_llm import VehicleLLMPlanner


class ModelStub:
    def __init__(self, action):
        self.action = action
    def decide(self, **kwargs):
        return self.action


def test_model_cannot_grant_itself_climate_permission():
    planner = VehicleLLMPlanner(ModelStub({"kind":"tool", "tool_name":"set_cabin_temperature", "arguments":{"celsius":22.0}}))
    with pytest.raises(PermissionError):
        run_non_yielding(planner.decide(request="diagnose", observations=(), step=0))


def test_model_cannot_finish_without_vehicle_observations():
    planner = VehicleLLMPlanner(ModelStub({"kind":"finish", "summary":"all good"}))
    with pytest.raises(ValueError):
        run_non_yielding(planner.decide(request="diagnose", observations=(), step=0))


def test_model_cannot_select_safety_critical_control():
    planner = VehicleLLMPlanner(ModelStub({"kind":"tool", "tool_name":"set_brake", "arguments":{}}), allow_climate=True)
    with pytest.raises(ValueError):
        run_non_yielding(planner.decide(request="stop", observations=(), step=0))
