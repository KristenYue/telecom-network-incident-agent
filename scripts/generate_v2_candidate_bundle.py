"""Generate reviewable V2 evaluation inputs; it intentionally does not seal them."""

from pathlib import Path

from telecom_incident_agent.dataset_v2 import write_v2_candidate_bundle


ROOT = Path(__file__).resolve().parents[1]
manifest = write_v2_candidate_bundle(ROOT / "data" / "evaluation")
print(
    "generated V2 candidate bundle: "
    f"development={manifest['development_case_count']} "
    f"pre_freeze={manifest['pre_freeze_case_count']} "
    f"status={manifest['status']}"
)
