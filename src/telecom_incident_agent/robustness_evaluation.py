"""Small, explicit challenge suite for boundaries hidden by easy synthetic cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_runtime_platform.contracts import RunStatus

from .adapter import TelecomIncidentRuntimeAdapter
from .compat import run_non_yielding
from .dataset import generate_tasks
from .models import IncidentRequest


async def _diagnose(payload: dict[str, Any]) -> tuple[RunStatus, dict[str, Any]]:
    incident = IncidentRequest.model_validate(payload)
    result = await TelecomIncidentRuntimeAdapter(
        checkpoint_path=Path(".runtime") / "robustness-evaluation" / f"{uuid4().hex}.sqlite3"
    ).diagnose(incident)
    return result.status, result.result.get("diagnosis", {}) if result.result else {}


async def evaluate_robustness() -> dict[str, Any]:
    template = generate_tasks()[0]["incident"]
    cases: list[dict[str, Any]] = []

    vendor_alias = {**template, "case_id": "ROBUST-vendor-alias"}
    vendor_alias["alarms"] = [{**template["alarms"][0], "alarm_type": "vendorx_rx_low"}]
    vendor_alias["metrics"] = [{**template["metrics"][0], "metric": "rx_power_dbm", "value": -27.0, "unit": "dBm"}]
    vendor_alias["allowed_runbooks"] = ["rb-optical-001"]
    status, diagnosis = await _diagnose(vendor_alias)
    causes = [item["fault_type"] for item in diagnosis.get("root_causes", [])]
    cases.append({"name": "documented_vendor_alias", "expected": "optical_power_abnormal", "actual": causes, "runtime_status": status.value, "passed": causes[:1] == ["optical_power_abnormal"]})

    unknown = {**template, "case_id": "ROBUST-unknown-signal", "alarms": [], "metrics": [], "allowed_runbooks": []}
    status, diagnosis = await _diagnose(unknown)
    cases.append({"name": "unknown_or_missing_signal", "expected": "manual_required", "actual": diagnosis.get("outcome"), "runtime_status": status.value, "passed": diagnosis.get("outcome") == "manual_required"})

    multifault = {**template, "case_id": "ROBUST-multi-fault"}
    multifault["alarms"] = [
        {**template["alarms"][0], "alarm_type": "rx_power_low"},
        {**template["alarms"][0], "alarm_id": "ROBUST-multi-bgp", "alarm_type": "bgp_down", "interface": None},
    ]
    multifault["metrics"] = [{**template["metrics"][0], "metric": "rx_power_dbm", "value": -27.0, "unit": "dBm"}]
    multifault["allowed_runbooks"] = ["rb-optical-001", "rb-bgp-001"]
    status, diagnosis = await _diagnose(multifault)
    causes = [item["fault_type"] for item in diagnosis.get("root_causes", [])]
    cases.append({"name": "multi_fault_ranking", "expected": ["optical_power_abnormal", "bgp_neighbor_down"], "actual": causes, "runtime_status": status.value, "passed": {"optical_power_abnormal", "bgp_neighbor_down"}.issubset(causes)})

    malformed = {**template, "case_id": "ROBUST-malformed-input", "alarms": [{"alarm_id": "missing-required-fields"}]}
    try:
        IncidentRequest.model_validate(malformed)
    except ValueError:
        valid_rejection = True
    else:
        valid_rejection = False
    cases.append({"name": "malformed_input_rejected", "expected": "validation_error", "actual": "validation_error" if valid_rejection else "accepted", "runtime_status": "not_started", "passed": valid_rejection})

    return {
        "schema_version": "telecom-robustness-report/v1",
        "evaluation_mode": "deterministic_synthetic_offline",
        "case_count": len(cases),
        "passed_count": sum(case["passed"] for case in cases),
        "passed": all(case["passed"] for case in cases),
        "cases": cases,
        "limitations": [
            "Vendor aliases are a fixed project-authored allowlist, not a general vendor parser.",
            "Challenges use synthetic inputs and local deterministic tools only.",
        ],
    }


def run_robustness_evaluation(output: Path) -> dict[str, Any]:
    report = run_non_yielding(evaluate_robustness())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return report
