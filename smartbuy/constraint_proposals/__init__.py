"""V2 validated natural-constraint contracts.

Runtime components intentionally use their concrete modules to avoid coupling the
V1 domain models to orchestration initialization.
"""

from .models import (
    PROPOSAL_SCHEMA_VERSION,
    RESOLUTION_SCHEMA_VERSION,
    ClarificationState,
    ConstraintDiff,
    ConstraintProposal,
    ConstraintResolution,
    PendingClarification,
    ProposalAction,
    ProposalKind,
    ProposalSource,
    ProposalStatus,
    SourceSpan,
    SpanSource,
)
from .spans import QuoteSpanResolver, QuoteSpanResult, QuoteSpanStatus
from .settings import NaturalConstraintSettings

__all__ = [
    "PROPOSAL_SCHEMA_VERSION",
    "RESOLUTION_SCHEMA_VERSION",
    "ClarificationState",
    "ConstraintDiff",
    "ConstraintProposal",
    "ConstraintResolution",
    "NaturalConstraintSettings",
    "PendingClarification",
    "ProposalAction",
    "ProposalKind",
    "ProposalSource",
    "ProposalStatus",
    "QuoteSpanResolver",
    "QuoteSpanResult",
    "QuoteSpanStatus",
    "SourceSpan",
    "SpanSource",
]
