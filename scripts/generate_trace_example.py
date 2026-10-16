import json
from pathlib import Path

from telecom_incident_agent.adapter import TelecomIncidentRuntimeAdapter
from telecom_incident_agent.compat import run_non_yielding
from telecom_incident_agent.demo import sample_incident


ROOT = Path(__file__).resolve().parents[1]
incident = sample_incident(high_risk=True)
adapter = TelecomIncidentRuntimeAdapter(
    checkpoint_path=ROOT / ".runtime" / "trace-example.sqlite3"
)
paused = run_non_yielding(adapter.diagnose(incident, task_id="trace-example"))
completed = run_non_yielding(
    adapter.resume(
        incident,
        paused.run_id,
        approved=True,
        review_message="synthetic reviewer approved draft creation only",
    )
)
payload = {
    "schema_version": "telecom-trace-example/v1",
    "input": incident.model_dump(mode="json"),
    "paused": paused.model_dump(mode="json"),
    "completed": completed.model_dump(mode="json"),
    "data_boundary": "synthetic",
}
output = ROOT / "examples" / "trace_optical_high_risk.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
    newline="\n",
)
print(output)
