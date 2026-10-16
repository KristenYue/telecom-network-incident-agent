"""Strict domain contracts for incidents, evidence, diagnoses, and tickets."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


DEVICE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$"
INTERFACE_PATTERN = r"^[A-Za-z][A-Za-z0-9/_.:-]{0,63}$"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Alarm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alarm_id: str = Field(min_length=1, max_length=100)
    device_id: str = Field(pattern=DEVICE_PATTERN)
    alarm_type: str = Field(min_length=1, max_length=100)
    severity: Literal["info", "warning", "major", "critical"]
    observed_at: datetime
    interface: str | None = Field(default=None, pattern=INTERFACE_PATTERN)
    details: dict[str, Any] = Field(default_factory=dict)


class MetricSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(min_length=1, max_length=150)
    metric: str = Field(min_length=1, max_length=100)
    value: float
    unit: str = Field(min_length=1, max_length=30)
    observed_at: datetime


class IncidentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    dataset_version: str = Field(default="telecom-synthetic-v1", max_length=100)
    topology_summary: str = Field(min_length=1, max_length=4000)
    alarms: list[Alarm] = Field(default_factory=list, max_length=200)
    logs: list[str] = Field(default_factory=list, max_length=200)
    metrics: list[MetricSample] = Field(default_factory=list, max_length=1000)
    allowed_runbooks: list[str] = Field(default_factory=list, max_length=100)
    requested_actions: list[str] = Field(default_factory=list, max_length=20)
    failure_injections: dict[str, str] = Field(default_factory=dict)
    synthetic: bool = True

    @field_validator("logs")
    @classmethod
    def enforce_log_budget(cls, values: list[str]) -> list[str]:
        if sum(len(value) for value in values) > 50_000:
            raise ValueError("combined log text exceeds 50000 characters")
        return values


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_type: Literal["alarm", "metric", "tool", "runbook", "log"]
    source_id: str
    summary: str
    supports: bool = True


class RootCauseCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fault_type: str
    label: str
    confidence: float = Field(ge=0, le=1)
    assessment: Literal["confirmed", "likely", "to_investigate"]
    supporting_evidence: list[Evidence]
    contradicting_evidence: list[Evidence] = Field(default_factory=list)


class RemediationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: int = Field(ge=1)
    instruction: str
    risk_level: RiskLevel
    requires_approval: bool = False
    source_runbook_id: str | None = None


class DiagnosisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    outcome: Literal["completed", "degraded", "manual_required", "failed_closed"]
    root_causes: list[RootCauseCandidate]
    remediation: list[RemediationStep]
    risk_level: RiskLevel
    requires_human_review: bool
    missing_information: list[str] = Field(default_factory=list)
    security_flags: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    data_boundary: str = "synthetic"


class TicketDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str
    case_id: str
    title: str
    status: Literal["draft"] = "draft"
    diagnosis: DiagnosisResult
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    idempotency_key: str


class IncidentEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    run_id: str
    runtime_status: str
    domain_outcome: str | None = None
    result: dict[str, Any] | None = None
    pending_review: bool = False
