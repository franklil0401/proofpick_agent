"""Deterministic product identity and candidate-scope boundary."""

from .models import (
    IDENTITY_CONTRACT_VERSION,
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
    "ProductIdentityResolver",
    "ProductIdentityMismatch",
    "ProductMention",
    "ProductScopeResolutionStatus",
    "ProductScopeType",
    "ResolvedProductScope",
    "evidence_identity_status",
    "product_identity",
    "require_product_in_scope",
]
