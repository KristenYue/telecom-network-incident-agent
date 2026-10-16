from pathlib import Path

from telecom_incident_agent.release import check_release


def test_release_readiness_is_machine_verifiable():
    root = Path(__file__).resolve().parents[1]
    report = check_release(root)
    assert report["passed"] is True
    assert report["status"] == "ready_with_limitations"
    assert all(check["passed"] for check in report["checks"])
