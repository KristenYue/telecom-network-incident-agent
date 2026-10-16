from pathlib import Path

from telecom_incident_agent.rag_evaluation import run_rag_evaluation


ROOT = Path(__file__).resolve().parents[1]
report = run_rag_evaluation(ROOT / "data" / "evaluation" / "telecom_rag_report_v1.json")
print(report["metrics"])
raise SystemExit(0 if all(value == 1.0 for value in report["metrics"].values()) else 1)
