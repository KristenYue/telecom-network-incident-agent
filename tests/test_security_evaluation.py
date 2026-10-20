from telecom_incident_agent.dataset_v2 import write_v2_candidate_bundle
from telecom_incident_agent.security_evaluation import evaluate_security_cohorts


def test_security_cohorts_are_executed_without_claiming_rbac(tmp_path):
    write_v2_candidate_bundle(tmp_path)
    report = evaluate_security_cohorts(tmp_path / "telecom_eval_v2_security_cohorts.jsonl")
    assert report["case_count"] == 88
    assert report["cohort_counts"] == {"prompt_injection": 40, "unauthorised_tool": 48}
    assert report["passed_counts"] == report["cohort_counts"]
    assert report["total_tool_executions"] == 0
    assert report["authorization_model"] == "tool allowlist; no user identity or RBAC claim"
