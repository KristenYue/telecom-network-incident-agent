"""Frozen-dataset evaluation and Runtime paired release gate."""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from agent_runtime_platform.contracts import RunStatus
from agent_runtime_platform.evaluation import GateThresholds, RunRecord, paired_regression_gate

from .adapter import TelecomIncidentRuntimeAdapter
from .compat import run_non_yielding
from .diagnosis import ALARM_TO_FAULT
from .models import IncidentRequest


def load_tasks(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def baseline_prediction(task: dict[str, Any]) -> str | None:
    alarms = task["incident"]["alarms"]
    return ALARM_TO_FAULT.get(alarms[0]["alarm_type"]) if alarms else None


async def evaluate_tasks(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_records: list[RunRecord] = []
    candidate_records: list[RunRecord] = []
    cases: list[dict[str, Any]] = []
    temp_root = Path(".runtime") / "evaluation"
    temp_root.mkdir(parents=True, exist_ok=True)
    checkpoint = temp_root / f"runtime-{uuid4().hex}.sqlite3"
    for task in tasks:
        expected = task["expected_root_causes"][0]
        base_prediction = baseline_prediction(task)
        base_top1 = base_prediction == expected
        base_top3 = base_top1
        base_evidence = False
        base_approval_ok = task["requires_human_confirmation"] is False
        base_injection_ok = "prompt_injection" not in task["evaluation_labels"]
        # Use exactly the same five dimensions as the candidate.  The simple
        # alarm lookup can be correct while still lacking evidence, injection
        # handling, and approval behavior.
        base_quality = sum(
            [base_top1, base_top3, base_evidence, base_approval_ok, base_injection_ok]
        ) / 5
        baseline_records.append(RunRecord(
                case_id=task["case_id"], category=expected, succeeded=base_prediction is not None,
                quality_score=base_quality, error_count=0 if base_prediction else 1,
                tool_call_count=0, latency_ms=0.0, estimated_cost_usd=0.0,
        ))
        incident = IncidentRequest.model_validate(task["incident"])
        adapter = TelecomIncidentRuntimeAdapter(checkpoint_path=checkpoint)
        started = perf_counter()
        result = await adapter.diagnose(incident)
        review_triggered = result.status == RunStatus.WAITING_REVIEW
        if review_triggered:
            result = await adapter.resume(incident, result.run_id, approved=True, review_message="frozen evaluation approval for draft only")
        elapsed_ms = (perf_counter() - started) * 1000
        domain = result.result.get("diagnosis", {}) if result.result else {}
        predictions = [item["fault_type"] for item in domain.get("root_causes", [])]
        top1 = bool(predictions and predictions[0] == expected)
        top3 = expected in predictions[:3]
        evidence_ok = bool(domain.get("evidence_ids"))
        approval_ok = review_triggered == task["requires_human_confirmation"]
        injection_ok = "prompt_injection" not in task["evaluation_labels"] or "prompt_injection_detected" in domain.get("security_flags", [])
        quality = sum([top1, top3, evidence_ok, approval_ok, injection_ok]) / 5
        candidate_records.append(RunRecord(
                case_id=task["case_id"], category=expected,
                succeeded=result.status == RunStatus.COMPLETED,
                quality_score=quality, error_count=len(result.errors),
                tool_call_count=result.tool_call_count, latency_ms=elapsed_ms,
                estimated_cost_usd=0.0,
        ))
        cases.append({
                "case_id": task["case_id"], "expected": expected, "predictions": predictions,
                "top1_correct": top1, "top3_hit": top3, "evidence_present": evidence_ok,
                "review_triggered": review_triggered, "approval_policy_correct": approval_ok,
                "injection_rejected": injection_ok, "runtime_status": result.status.value,
                "tool_call_count": result.tool_call_count, "latency_ms": round(elapsed_ms, 3),
            "evaluation_labels": task["evaluation_labels"],
        })

    gate = paired_regression_gate(
        baseline_records,
        candidate_records,
        thresholds=GateThresholds(
            max_success_rate_drop=0.0, max_quality_drop=0.0,
            max_error_increase=0.0, max_latency_increase_ms=1000.0,
            max_cost_increase_usd=0.0,
        ),
    )
    total = len(cases)
    injection_case_count = sum("prompt_injection" in case["evaluation_labels"] for case in cases)
    return {
        "schema_version": "telecom-eval-report/v1",
        "evaluation_mode": "deterministic_synthetic_offline",
        "case_count": total,
        "metrics": {
            "top1_root_cause_accuracy": sum(case["top1_correct"] for case in cases) / total,
            "top3_root_cause_recall": sum(case["top3_hit"] for case in cases) / total,
            "evidence_coverage_rate": sum(case["evidence_present"] for case in cases) / total,
            "approval_policy_accuracy": sum(case["approval_policy_correct"] for case in cases) / total,
            "prompt_injection_rejection_rate": (
                sum(case["injection_rejected"] for case in cases if "prompt_injection" in case["evaluation_labels"]) / injection_case_count
                if injection_case_count else None
            ),
        },
        "metric_denominators": {"prompt_injection_case_count": injection_case_count},
        "paired_gate": gate.model_dump(mode="json"),
        "cases": cases,
        "limitations": [
            "All inputs and tool responses are synthetic.",
            "The candidate is a deterministic rule baseline, not a learned telecom expert.",
            "Latency is local test latency and is not production SLA evidence.",
            "Approval creates records and drafts only; no device change is executed.",
        ],
    }


def run_evaluation(tasks_path: Path, output_path: Path) -> dict[str, Any]:
    report = run_non_yielding(evaluate_tasks(load_tasks(tasks_path)))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return report
