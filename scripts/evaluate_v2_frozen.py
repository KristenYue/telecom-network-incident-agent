"""Run the existing evaluator against the sealed V2 input and save actual results."""

import json
from pathlib import Path

from telecom_incident_agent.evaluation import run_evaluation


ROOT = Path(__file__).resolve().parents[1]
report = run_evaluation(
    ROOT / "data" / "evaluation" / "telecom_eval_v2_frozen.jsonl",
    ROOT / "data" / "evaluation" / "telecom_eval_v2_frozen_report.json",
)
frozen_manifest = json.loads((ROOT / "data" / "evaluation" / "telecom_eval_v2_frozen_manifest.json").read_text(encoding="utf-8"))
report["schema_version"] = "telecom-eval-report/v2"
report["input_manifest"] = {
    "file": "telecom_eval_v2_frozen_manifest.json",
    "frozen_file_sha256": frozen_manifest["frozen_file_sha256"],
    "case_count": frozen_manifest["case_count"],
}
report["evidence_boundary"] = (
    "Results apply only to the sealed, project-authored synthetic offline input. "
    "They are not production-network, operator-data, SLA, or generalization evidence."
)
output = ROOT / "data" / "evaluation" / "telecom_eval_v2_frozen_report.json"
output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
print(report["metrics"])
print(f"paired_gate_passed={report['paired_gate']['passed']}")
