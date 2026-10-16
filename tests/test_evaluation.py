from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.dataset import generate_tasks
from telecom_incident_agent.evaluation import evaluate_tasks


def test_full_frozen_suite_meets_release_gate():
    report = run_non_yielding(evaluate_tasks(generate_tasks()))
    assert report["case_count"] == 60
    assert report["metrics"]["top1_root_cause_accuracy"] >= 0.95
    assert report["metrics"]["evidence_coverage_rate"] == 1.0
    assert report["metrics"]["approval_policy_accuracy"] == 1.0
    assert report["paired_gate"]["passed"] is True
