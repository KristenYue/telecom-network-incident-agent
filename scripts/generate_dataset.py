from pathlib import Path

from telecom_incident_agent.dataset import write_dataset


ROOT = Path(__file__).resolve().parents[1]
manifest = write_dataset(
    ROOT / "data" / "evaluation" / "telecom_eval_v1.jsonl",
    ROOT / "data" / "evaluation" / "telecom_eval_v1_manifest.json",
)
print(f"generated {manifest['case_count']} cases; sha256={manifest['dataset_sha256']}")
