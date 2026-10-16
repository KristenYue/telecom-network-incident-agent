import json
from pathlib import Path

from telecom_incident_agent.release import check_release


ROOT = Path(__file__).resolve().parents[1]
report = check_release(ROOT)
output = ROOT / "data" / "evaluation" / "release_readiness.json"
output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if report["passed"] else 1)
