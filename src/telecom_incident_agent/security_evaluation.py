"""Execute the separately generated V2 security cohorts against real guards."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .dataset import generate_tasks
from .models import IncidentRequest
from .security import sanitize_untrusted_text
from .tools import SyntheticTelecomTools


def evaluate_security_cohorts(path: Path) -> dict[str, Any]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    template = IncidentRequest.model_validate(generate_tasks()[0]["incident"])
    cases: list[dict[str, Any]] = []
    for record in records:
        tools = SyntheticTelecomTools(template.model_copy(update={"case_id": record["case_id"]}))
        if record["cohort"] == "unauthorised_tool":
            try:
                tools.registry().resolve(record["requested_tool"])
            except ValueError:
                denied = True
            else:
                denied = False
            cases.append({
                "case_id": record["case_id"], "cohort": record["cohort"],
                "requested_tool": record["requested_tool"], "denied": denied,
                "tool_executions": len(tools.write_ledger), "passed": denied and not tools.write_ledger,
            })
        elif record["cohort"] == "prompt_injection":
            safe, flags = sanitize_untrusted_text(record["untrusted_text"])
            if safe == "[UNTRUSTED_INSTRUCTION_REMOVED]" and "prompt_injection_detected" in flags:
                handling_layer = "explicit_input_rejection"
                passed = record.get("expected_handling") == handling_layer
            else:
                requested_tool = record.get("requested_tool")
                denied = False
                if requested_tool:
                    try:
                        tools.registry().resolve(requested_tool)
                    except ValueError:
                        denied = True
                handling_layer = "permission_layer_block"
                passed = denied and record.get("expected_handling") == handling_layer
            cases.append({
                "case_id": record["case_id"], "cohort": record["cohort"],
                "security_flags": flags, "sanitized": safe, "tool_executions": len(tools.write_ledger),
                "handling_layer": handling_layer,
                "passed": passed and not tools.write_ledger,
            })
        else:
            raise ValueError(f"unsupported security cohort: {record['cohort']}")
    counts = Counter(case["cohort"] for case in cases)
    passed_counts = Counter(case["cohort"] for case in cases if case["passed"])
    handling_counts = Counter(
        case["handling_layer"]
        for case in cases
        if case["cohort"] == "prompt_injection"
    )
    return {
        "schema_version": "telecom-security-cohort-report/v2",
        "evaluation_mode": "deterministic_synthetic_offline",
        "authorization_model": "tool allowlist; no user identity or RBAC claim",
        "case_count": len(cases),
        "cohort_counts": dict(sorted(counts.items())),
        "passed_counts": dict(sorted(passed_counts.items())),
        "prompt_injection_handling_counts": dict(sorted(handling_counts.items())),
        "total_tool_executions": sum(case["tool_executions"] for case in cases),
        "passed": all(case["passed"] for case in cases),
        "cases": cases,
        "limitations": [
            "Unauthorised-tool checks prove that unsupported tool names cannot be resolved by this synthetic registry.",
            "This project does not implement identity authentication or role-based access control.",
            "No provider, device, or production security control is exercised.",
        ],
    }


def run_security_evaluation(input_path: Path, output_path: Path) -> dict[str, Any]:
    report = evaluate_security_cohorts(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return report
