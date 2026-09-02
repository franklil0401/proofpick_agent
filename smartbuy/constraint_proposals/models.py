"""Schema-validated natural constraint proposals and clarification state."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from smartbuy.constraints import ConstraintOperator, ConstraintSet, ConstraintStrength


PROPOSAL_SCHEMA_VERSION = "proofpick-constraint-proposal-v1"
RESOLUTION_SCHEMA_VERSION = "proofpick-constraint-resolution-v1"


class ProposalStatus(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    AMBIGUOUS = "ambiguous"
    NEEDS_CONFIRMATION = "needs_confirmation"
    INVALID = "invalid"


class ProposalAction(StrEnum):
    ADD = "add"
    OVERRIDE = "override"
    CANCEL = "cancel"
    CONFIRM = "confirm"


class ProposalSource(StrEnum):
    RULE = "rule"
    LLM = "llm"


class ProposalKind(StrEnum):
    SUPPORTED_CONSTRAINT = "supported_constraint"
    UNSUPPORTED_REQUEST = "unsupported_request"
    NEEDS_CLARIFICATION = "needs_clarification"
    CANCEL_CONSTRAINT = "cancel_constraint"
    CONFIRM_CONSTRAINT = "confirm_constraint"


class SpanSource(StrEnum):
    SERVER_RULE_MATCH = "server_rule_match"
    SERVER_EXACT_QUOTE = "server_exact_quote"
    UNRESOLVED_QUOTE = "unresolved_quote"


class ClarificationState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class SourceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_order(self) -> SourceSpan:
        if self.end <= self.start:
            raise ValueError("source span end must be after start")
        return self


class ConstraintProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[PROPOSAL_SCHEMA_VERSION] = PROPOSAL_SCHEMA_VERSION
    proposal_id: str = Field(pattern=r"^cp-[a-f0-9]{24}$")
    field: str = Field(min_length=1, max_length=80)
    operator: ConstraintOperator | None = None
    normalized_value: Any = None
    unit: str | None = Field(default=None, max_length=32)
    strength: ConstraintStrength = ConstraintStrength.HARD
    action: ProposalAction = ProposalAction.ADD
    status: ProposalStatus
    source: ProposalSource
    source_span: SourceSpan | None = None
    source_quote: str | None = Field(default=None, min_length=1, max_length=300)
    span_source: SpanSource = SpanSource.SERVER_RULE_MATCH
    occurrence: int | None = Field(default=None, ge=1)
    proposal_kind: ProposalKind | None = None
    clarification_question: str | None = Field(default=None, max_length=600)
    source_turn: int = Field(ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    active: bool = False
    reason: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def enforce_activation_boundary(self) -> ConstraintProposal:
        if self.active and self.source_span is None:
            raise ValueError("active proposal requires a server-verified source span")
        if self.span_source == SpanSource.SERVER_EXACT_QUOTE:
            if self.source_span is None or self.source_quote != self.source_span.text:
                raise ValueError("server exact quote span must preserve the original quote")
        if self.active and self.status != ProposalStatus.SUPPORTED:
            raise ValueError("only supported proposals may be active")
        if self.active and self.action == ProposalAction.CANCEL:
            raise ValueError("cancel proposals are never active constraints")
        if self.status == ProposalStatus.SUPPORTED and self.action != ProposalAction.CANCEL:
            if self.operator is None or self.normalized_value is None:
                raise ValueError("supported proposal requires operator and value")
        return self


class ConstraintDiff(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str
    action: ProposalAction
    before: list[dict[str, Any]] = Field(default_factory=list)
    after: list[dict[str, Any]] = Field(default_factory=list)
    proposal_id: str


class ConstraintResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[RESOLUTION_SCHEMA_VERSION] = RESOLUTION_SCHEMA_VERSION
    query: str = Field(min_length=1, max_length=2_000)
    source_turn: int = Field(ge=1)
    proposals: list[ConstraintProposal] = Field(default_factory=list)
    constraint_set: ConstraintSet = Field(default_factory=ConstraintSet)
    clarification_state: ClarificationState = ClarificationState.NOT_REQUIRED
    clarification_question: str | None = Field(default=None, max_length=600)
    pending_proposal_ids: list[str] = Field(default_factory=list)
    diff: list[ConstraintDiff] = Field(default_factory=list)
    provider_calls: int = Field(default=0, ge=0, le=1)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    estimated_cost_cny: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def validate_clarification(self) -> ConstraintResolution:
        if self.clarification_state == ClarificationState.PENDING:
            if not self.pending_proposal_ids or not self.clarification_question:
                raise ValueError("pending clarification requires proposals and question")
        elif self.pending_proposal_ids:
            raise ValueError("only pending clarification may expose pending proposal ids")
        pending = {
            item.proposal_id
            for item in self.proposals
            if item.status in {ProposalStatus.AMBIGUOUS, ProposalStatus.NEEDS_CONFIRMATION}
        }
        if not set(self.pending_proposal_ids) <= pending:
            raise ValueError("pending proposal id does not reference an ambiguous proposal")
        return self


class PendingClarification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["proofpick-pending-clarification-v1"] = (
        "proofpick-pending-clarification-v1"
    )
    identity_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: str
    resolution: ConstraintResolution
