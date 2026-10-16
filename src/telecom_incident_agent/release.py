"""Machine-readable release-readiness checks for the synthetic project."""

from __future__ import annotations

import json
from pathlib import Path

from .dataset import normalized_sha256


def check_release(root: Path) -> dict:
    required = [
        "README.md", "pyproject.toml", "Dockerfile", "compose.yaml",
        "docs/ARCHITECTURE.md", "docs/DATA_CARD.md",
        "docs/TOOLS_AND_PERMISSIONS.md", "docs/FAILURE_STATE_MACHINE.md",
        "data/evaluation/telecom_eval_v1.jsonl",
        "data/evaluation/telecom_eval_v1_manifest.json",
        "data/evaluation/telecom_eval_report_v1.json",
        "data/evaluation/telecom_failure_report_v1.json",
        "data/evaluation/telecom_rag_report_v1.json",
        "examples/trace_optical_high_risk.json",
    ]
    missing = [name for name in required if not (root / name).is_file()]
    checks: list[dict] = [{"name": "required_files", "passed": not missing, "detail": {"missing": missing}}]
    if missing:
        return {"status": "failed", "passed": False, "checks": checks}

    manifest = json.loads((root / "data/evaluation/telecom_eval_v1_manifest.json").read_text(encoding="utf-8"))
    actual_hash = normalized_sha256(root / "data/evaluation/telecom_eval_v1.jsonl")
    checks.append({"name": "dataset_integrity", "passed": manifest["case_count"] == 60 and manifest["fault_category_count"] == 12 and manifest["dataset_sha256"] == actual_hash, "detail": {"cases": manifest["case_count"], "fault_categories": manifest["fault_category_count"], "hash_matches": manifest["dataset_sha256"] == actual_hash}})

    evaluation = json.loads((root / "data/evaluation/telecom_eval_report_v1.json").read_text(encoding="utf-8"))
    checks.append({"name": "paired_runtime_gate", "passed": evaluation["case_count"] == 60 and evaluation["paired_gate"]["passed"], "detail": {"paired_cases": evaluation["paired_gate"]["paired_cases"], "failures": evaluation["paired_gate"]["failures"]}})

    failures = json.loads((root / "data/evaluation/telecom_failure_report_v1.json").read_text(encoding="utf-8"))
    checks.append({"name": "failure_injection_gate", "passed": failures["case_count"] >= 10 and failures["passed"], "detail": {"passed": failures["passed_count"], "total": failures["case_count"]}})

    rag = json.loads((root / "data/evaluation/telecom_rag_report_v1.json").read_text(encoding="utf-8"))
    checks.append({"name": "synthetic_rag_gate", "passed": all(value == 1.0 for value in rag["metrics"].values()), "detail": rag["metrics"]})

    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (root / "src").rglob("*.py")
        if path.name != "release.py"
    )
    forbidden_handlers = ["restart_device(", "restart_interface(", "change_route_policy(", "shutdown_interface("]
    present = [value for value in forbidden_handlers if value in text]
    checks.append({"name": "no_real_change_handlers", "passed": not present, "detail": {"present": present}})
    passed = all(check["passed"] for check in checks)
    return {
        "schema_version": "telecom-release-readiness/v1",
        "status": "ready_with_limitations" if passed else "failed",
        "passed": passed,
        "checks": checks,
        "limitations": [
            "Docker build and Compose startup are not verified on this host.",
            "PostgreSQL/Redis worker topology and browser Trace UI remain C4 work.",
            "All quality evidence is synthetic and offline.",
        ],
    }
