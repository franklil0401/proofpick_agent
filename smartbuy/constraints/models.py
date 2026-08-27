"""Typed contracts for deterministic user constraints and verification output."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConstraintOperator(StrEnum):
    EQ = "eq"
    LTE = "lte"
    GTE = "gte"
    RANGE = "range"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS_ALL = "contains_all"


class ConstraintStrength(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class ConstraintProvenance(StrEnum):
    CURRENT_INPUT = "current_input"
    SESSION_CONFIRMED = "session_confirmed"
    LONG_TERM_PREFERENCE = "long_term_preference"
    SYSTEM_DEFAULT = "system_default"


class VerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class NormalizedConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    operator: ConstraintOperator
    normalized_value: Any
    unit: str | None = None
    hard_or_soft: ConstraintStrength
    provenance: ConstraintProvenance
    source_text: str
    source_turn: int = Field(ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    supported: bool = True
    active: bool = True
    ambiguous: bool = False
    note: str | None = None


class ConstraintSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "smartbuy-constraint-set-v1"
    constraints: list[NormalizedConstraint] = Field(default_factory=list)
    cancelled_fields: list[str] = Field(default_factory=list)
    rejected_model_constraints: list[str] = Field(default_factory=list)

    def active(self, *, hard_only: bool = False, supported_only: bool = False) -> list[NormalizedConstraint]:
        values = [item for item in self.constraints if item.active]
        if hard_only:
            values = [item for item in values if item.hard_or_soft == ConstraintStrength.HARD]
        if supported_only:
            values = [item for item in values if item.supported and not item.ambiguous]
        return values


class ConstraintResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint: NormalizedConstraint
    actual_value: Any = None
    status: VerificationStatus
    reason: str
    evidence_id: str | None = None
    source_id: str | None = None


class CandidateVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    overall_status: VerificationStatus
    constraint_results: list[ConstraintResult] = Field(default_factory=list)
    eligible: bool = False
    violated_fields: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    conflict_fields: list[str] = Field(default_factory=list)
    unsupported_constraints: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    price_observed_at: str | None = None
    checked_at: str
    verifier_version: str


class VerificationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verifier_version: str
    checked_at: str
    constraint_set_version: str
    candidate_pool_model_ids: list[str] = Field(default_factory=list)
    candidates: list[CandidateVerification] = Field(default_factory=list)
    unsupported_constraints: list[NormalizedConstraint] = Field(default_factory=list)
    eligible_model_ids: list[str] = Field(default_factory=list)
    rejected_model_ids: list[str] = Field(default_factory=list)
    semantic_fingerprint: str
    degraded: bool = False
    degrade_reason: str | None = None
