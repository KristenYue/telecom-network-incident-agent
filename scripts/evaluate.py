from pathlib import Path

from telecom_incident_agent.evaluation import run_evaluation


ROOT = Path(__file__).resolve().parents[1]
report = run_evaluation(
    ROOT / "data" / "evaluation" / "telecom_eval_v1.jsonl",
    ROOT / "data" / "evaluation" / "telecom_eval_report_v1.json",
)
print(report["metrics"])
print(f"paired_gate_passed={report['paired_gate']['passed']}")
raise SystemExit(0 if report["paired_gate"]["passed"] else 1)
