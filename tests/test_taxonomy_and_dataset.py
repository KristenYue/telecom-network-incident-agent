import json

from telecom_incident_agent.dataset import generate_tasks, write_dataset
from telecom_incident_agent.taxonomy import FAULT_POLICIES


def test_frozen_taxonomy_has_twelve_fault_classes():
    assert len(FAULT_POLICIES) == 12
    assert all(policy.required_signals for policy in FAULT_POLICIES.values())
    assert all(policy.safe_actions for policy in FAULT_POLICIES.values())


def test_dataset_has_five_cases_per_fault_and_required_contract():
    tasks = generate_tasks()
    assert len(tasks) == 60
    for fault in FAULT_POLICIES:
        assert sum(task["expected_root_causes"] == [fault] for task in tasks) == 5
    assert all(task["source"]["type"] == "synthetic" for task in tasks)
    assert all(len(task["available_tools"]) == 9 for task in tasks)


def test_manifest_hashes_exact_frozen_jsonl(tmp_path):
    dataset = tmp_path / "tasks.jsonl"
    manifest_path = tmp_path / "manifest.json"
    manifest = write_dataset(dataset, manifest_path)
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["case_count"] == 60
    assert saved["dataset_sha256"] == manifest["dataset_sha256"]
    assert saved["sha256_mode"] == "sha256_utf8_lf_normalized"
