"""Seal the V2 pre-freeze candidate after its integrity checks pass."""

from pathlib import Path

from telecom_incident_agent.dataset_v2 import seal_v2_frozen_input


ROOT = Path(__file__).resolve().parents[1]
manifest = seal_v2_frozen_input(ROOT / "data" / "evaluation")
print(
    "sealed V2 input: "
    f"cases={manifest['case_count']} sha256={manifest['frozen_file_sha256']} "
    f"status={manifest['status']}"
)
