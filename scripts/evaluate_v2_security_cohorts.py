"""Execute the V2 security cohorts and save an evidence-bounded report."""

from pathlib import Path

from telecom_incident_agent.security_evaluation import run_security_evaluation


ROOT = Path(__file__).resolve().parents[1]
report = run_security_evaluation(
    ROOT / "data" / "evaluation" / "telecom_eval_v2_security_cohorts.jsonl",
    ROOT / "data" / "evaluation" / "telecom_eval_v2_security_cohort_report.json",
)
print(report["cohort_counts"])
print(f"passed={report['passed']} tool_executions={report['total_tool_executions']}")
