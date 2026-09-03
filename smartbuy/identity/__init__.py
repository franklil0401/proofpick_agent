"""Deterministic product identity and candidate-scope boundary."""

from .models import (
    IDENTITY_CONTRACT_VERSION,
    CandidateScope,
    ProductReference,
    QueryIntent,
    ReferencePolarity,
    ReferenceResolutionStatus,
    ProductMention,
    ProductScopeResolutionStatus,
    ProductScopeType,
    ResolvedProductScope,
)
from .resolver import ProductIdentityResolver
from .guards import (
    ProductIdentityMismatch,
    evidence_identity_status,
    product_identity,
    require_product_in_scope,
)

__all__ = [
    "IDENTITY_CONTRACT_VERSION",
    "CandidateScope",
    "ProductIdentityResolver",
    "ProductIdentityMismatch",
    "ProductMention",
    "ProductReference",
    "QueryIntent",
    "ReferencePolarity",
    "ReferenceResolutionStatus",
    "ProductScopeResolutionStatus",
    "ProductScopeType",
    "ResolvedProductScope",
    "evidence_identity_status",
    "product_identity",
    "require_product_in_scope",
]
