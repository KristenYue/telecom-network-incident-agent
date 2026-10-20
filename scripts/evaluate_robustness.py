from pathlib import Path

from telecom_incident_agent.robustness_evaluation import run_robustness_evaluation


ROOT = Path(__file__).resolve().parents[1]
report = run_robustness_evaluation(ROOT / "data" / "evaluation" / "telecom_robustness_report_v1.json")
print(f"passed={report['passed_count']}/{report['case_count']}")
raise SystemExit(0 if report["passed"] else 1)
