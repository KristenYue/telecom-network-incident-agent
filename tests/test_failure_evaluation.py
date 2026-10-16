from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.failure_evaluation import evaluate_failures


def test_failure_injection_suite_passes_at_least_ten_scenarios():
    report = run_non_yielding(evaluate_failures())
    assert report["case_count"] >= 10
    assert report["passed"] is True
    assert report["passed_count"] == report["case_count"]
