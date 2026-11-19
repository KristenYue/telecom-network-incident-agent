import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from telecom_incident_agent.robot_skills import WorkcellSimulation
from telecom_incident_agent.robot_tasks import RobotTasks


def wait(service, task_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        task = service.get(task_id)
        if task["state"] not in ("queued", "running"):
            return task
        time.sleep(.01)
    raise AssertionError("task deadline")


def test_duplicate_requests_share_one_execution_and_reject_changed_payload(tmp_path):
    service = RobotTasks(tmp_path)
    try:
        with ThreadPoolExecutor(4) as pool:
            tasks = list(pool.map(lambda _: service.submit("inspect", "same-key"), range(8)))
        assert len({t["id"] for t in tasks}) == 1
        final = wait(service, tasks[0]["id"])
        assert final["state"] == "completed"
        assert len([e for e in service.events(final["id"]) if e["event"] == "progress"]) == 3
        with pytest.raises(ValueError):
            service.submit("different", "same-key")
    finally:
        service.close()


def test_cancel_propagates_and_history_reopens(tmp_path):
    service = RobotTasks(tmp_path, transport=WorkcellSimulation(delay=.1))
    try:
        task = service.submit("inspect", "cancel")
        deadline = time.monotonic()+3
        while not any(e["event"] == "progress" for e in service.events(task["id"])):
            assert time.monotonic()<deadline
            time.sleep(.01)
        service.cancel(task["id"])
        final = wait(service, task["id"])
        assert final["state"] == "canceled"
        assert final["result"]["runtime"]["result"]["outcome"] == "canceled"
    finally:
        service.close()
    reopened = RobotTasks(tmp_path)
    try:
        assert reopened.get(task["id"])["state"] == "canceled"
    finally:
        reopened.close()


def test_offline_never_claims_inspection_completed(tmp_path):
    service = RobotTasks(tmp_path, transport=WorkcellSimulation(unavailable=True))
    try:
        task = service.submit("inspect", "offline")
        final = wait(service, task["id"])
        assert final["state"] == "failed_closed"
        assert not any(e["event"] == "progress" for e in service.events(task["id"]))
    finally:
        service.close()
