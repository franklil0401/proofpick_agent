"""Immutable, domain-neutral data contracts for ProofPick V2.

These models do not replace V1 schemas.  They define the boundary used by
adapters while the V1 workflow remains authoritative and unchanged.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CONTRACT_VERSION = "proofpick-domain-contract-v1"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldDataType(StrEnum):
    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    STRING_LIST = "string_list"


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


class FieldState(StrEnum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class FieldDefinition(FrozenModel):
    field_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    data_type: FieldDataType
    nullable: bool = True
    unit: str | None = None
    accepted_units: dict[str, float] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    enum_values: list[str] = Field(default_factory=list)
    value_aliases: dict[str, str] = Field(default_factory=dict)
    constraint_enabled: bool = False
    allowed_operators: list[ConstraintOperator] = Field(default_factory=list)
    evidence_required: bool = False
    dynamicity: Literal["stable", "observed", "derived"] = "stable"
    storage_binding: str | None = None

    @model_validator(mode="after")
    def validate_definition(self) -> FieldDefinition:
        if self.constraint_enabled and not self.allowed_operators:
            raise ValueError("constraint-enabled field must declare allowed operators")
        if self.enum_values and self.data_type != FieldDataType.STRING:
            raise ValueError("enum_values are only valid for string fields")
        if self.accepted_units and not self.unit:
            raise ValueError("accepted_units require a canonical unit")
        return self


class Constraint(FrozenModel):
    """LLM may propose this object; deterministic code validates and activates it."""

    field: str
    operator: ConstraintOperator
    normalized_value: Any
    unit: str | None = None
    strength: ConstraintStrength
    provenance: ConstraintProvenance
    source_text: str
    source_turn: int = Field(ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    proposed_by: Literal["llm", "deterministic", "user"]
    supported: bool = False
    active: bool = False
    ambiguous: bool = False
    validated_by: Literal["deterministic"] = "deterministic"

    @model_validator(mode="after")
    def enforce_proposal_ownership(self) -> Constraint:
        if self.proposed_by == "llm" and (self.supported or self.active):
            raise ValueError("LLM proposals cannot self-validate or self-activate")
        return self


class SourceRecord(FrozenModel):
    source_id: str
    product_id: str
    source_type: str
    title: str
    url: str
    is_official: bool
    region: str | None = None
    published_at: str | None = None
    accessed_at: str
    content_hash: str
    redistribution_status: str
    notes: str | None = None
    owner: Literal["deterministic"] = "deterministic"


class EvidenceRecord(FrozenModel):
    evidence_id: str
    source_id: str
    product_id: str
    field_id: str
    normalized_value: Any = None
    original_value: Any = None
    evidence_location: str | None = None
    confidence_level: str | None = None
    effective_time: str | None = None
    conflict_group: str | None = None
    state: FieldState
    owner: Literal["deterministic"] = "deterministic"


class Product(FrozenModel):
    product_id: str
    domain_id: str
    brand: str
    model_name: str
    region: str
    attributes: dict[str, Any]
    source_ids: list[str] = Field(default_factory=list)
    data_version: str
    owner: Literal["deterministic"] = "deterministic"


class CandidateFieldDecision(FrozenModel):
    field_id: str
    required_value: Any = None
    actual_value: Any = None
    state: FieldState
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class Candidate(FrozenModel):
    product_id: str
    field_decisions: list[CandidateFieldDecision] = Field(default_factory=list)
    overall_state: FieldState
    eligible: bool = False
    violated_fields: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    conflict_fields: list[str] = Field(default_factory=list)
    unsupported_constraints: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    checker_version: str
    owner: Literal["deterministic"] = "deterministic"

    @model_validator(mode="after")
    def enforce_fail_closed_eligibility(self) -> Candidate:
        blockers = bool(
            self.violated_fields
            or self.unknown_fields
            or self.conflict_fields
            or self.unsupported_constraints
        )
        if self.eligible and (self.overall_state != FieldState.MATCHED or blockers):
            raise ValueError("eligible candidate must be fully matched without blockers")
        if self.overall_state in {FieldState.UNKNOWN, FieldState.CONFLICT} and self.eligible:
            raise ValueError("unknown/conflict cannot become eligible")
        return self


class ToolResult(FrozenModel):
    tool_name: str
    status: Literal["success", "failed", "degraded", "unavailable"]
    data: Any = None
    evidence_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    degraded: bool = False
    retry_count: int = Field(default=0, ge=0)
    error_category: str | None = None
    contract_version: str = CONTRACT_VERSION


class DataVersion(FrozenModel):
    version_id: str
    domain_id: str
    schema_version: str
    source_hash: str
    created_at: str
    product_count: int = Field(ge=0)
    source_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    immutable: bool = True


class DomainPackManifest(FrozenModel):
    manifest_schema_version: str
    domain_pack_version: str
    domain_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    display_name: str
    contract_versions: list[str]
    compatible_loader_versions: list[str]
    data_versions: list[str]
    files: dict[str, str]


class DomainPack(FrozenModel):
    manifest: DomainPackManifest
    fields: list[FieldDefinition]
    policies: dict[str, Any]
    fingerprint: str


class ProductPack(FrozenModel):
    """Metadata boundary only; V2-1D deliberately has no import workflow."""

    pack_id: str
    domain_id: str
    pack_version: str
    data_version: DataVersion
    product_source: str
    source_source: str
    evidence_source: str
    content_hashes: dict[str, str]
