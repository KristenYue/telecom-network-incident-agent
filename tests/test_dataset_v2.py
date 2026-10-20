import json

from telecom_incident_agent.dataset_v2 import (
    DEVELOPMENT_CASE_COUNT,
    PRE_FREEZE_CASE_COUNT,
    PROMPT_INJECTION_CASE_COUNT,
    UNAUTHORISED_TOOL_CASE_COUNT,
    generate_development_tasks,
    generate_pre_freeze_tasks,
    generate_security_cohorts,
    seal_v2_frozen_input,
    validate_split_isolation,
    write_v2_candidate_bundle,
)
from telecom_incident_agent.models import IncidentRequest


def test_v2_case_counts_contracts_and_split_isolation():
    development = generate_development_tasks()
    pre_freeze = generate_pre_freeze_tasks()
    assert len(development) == DEVELOPMENT_CASE_COUNT == 240
    assert len(pre_freeze) == PRE_FREEZE_CASE_COUNT == 100
    assert all(task["dataset_version"] == "telecom-synthetic-v2" for task in development + pre_freeze)
    assert all(len(task["available_tools"]) == 9 for task in development + pre_freeze)
    assert sum("prompt_injection" in task["evaluation_labels"] for task in pre_freeze) == 12
    assert all(IncidentRequest.model_validate(task["incident"]) for task in development + pre_freeze)
    validate_split_isolation(development, pre_freeze)


def test_v2_security_cohort_counts_are_separate_from_accuracy_metrics():
    records = generate_security_cohorts()
    assert sum(record["cohort"] == "unauthorised_tool" for record in records) == UNAUTHORISED_TOOL_CASE_COUNT == 48
    assert sum(record["cohort"] == "prompt_injection" for record in records) == PROMPT_INJECTION_CASE_COUNT == 40
    assert all("expected_authorization" in record or "expected_handling" in record for record in records)


def test_v2_candidate_manifest_is_explicitly_not_a_frozen_result(tmp_path):
    manifest = write_v2_candidate_bundle(tmp_path)
    saved = json.loads((tmp_path / "telecom_eval_v2_candidate_manifest.json").read_text(encoding="utf-8"))
    assert manifest == saved
    assert saved["status"] == "pre_freeze_candidate_not_evaluation_evidence"
    assert len(saved["files"]) == 3


def test_v2_seal_binds_candidate_hash_without_creating_a_result(tmp_path):
    write_v2_candidate_bundle(tmp_path)
    frozen = seal_v2_frozen_input(tmp_path)
    assert frozen["status"] == "frozen_input_no_metrics"
    assert frozen["case_count"] == 100
    assert frozen["source_candidate_sha256"] == frozen["frozen_file_sha256"]
    assert not {"metrics", "top1_root_cause_accuracy", "top3_root_cause_recall"} & set(frozen)
