"""Monotonic candidate-set reduction independent of product category."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from smartbuy.domain_packs import LoadedDomainPack
from smartbuy.domain_packs.evaluator import DomainConstraintEvaluator
from smartbuy.identity import (
    ProductScopeResolutionStatus,
    ProductScopeType,
    QueryIntent,
    ResolvedProductScope,
)


@dataclass(frozen=True)
class ScopeTransition:
    before: tuple[str, ...]
    after: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if not set(self.after) <= set(self.before):
            raise ValueError("candidate scope transition is not monotonic")


class CandidateScopeReducer:
    def __init__(self, pack: LoadedDomainPack) -> None:
        self.pack = pack
        self.evaluator = DomainConstraintEvaluator(pack)

    def reduce(
        self,
        scope: ResolvedProductScope,
        products: dict[str, dict[str, Any]],
        constraints: Iterable[dict[str, Any]],
        *,
        intent: QueryIntent,
        require_unique: bool = False,
    ) -> tuple[ResolvedProductScope, ScopeTransition]:
        before = tuple(scope.product_ids)
        if scope.scope_type not in {
            ProductScopeType.PRODUCT_FAMILY,
            ProductScopeType.AMBIGUOUS_PRODUCT_SCOPE,
        }:
            return scope, ScopeTransition(before, before, "scope_not_family")
        normalized = list(constraints)
        after = list(before)
        if normalized:
            matched: list[str] = []
            for product_id in before:
                product = products[product_id]
                evidenced = {
                    item["field_id"] for item in product["evidence"]
                    if item["region"] == product["region"]
                    and item["variant_key"] == product["variant_key"]
                }
                _, eligible = self.evaluator.evaluate(
                    product["attributes"], normalized, evidenced_fields=evidenced
                )
                if eligible:
                    matched.append(product_id)
            after = matched
        if not after:
            status = ProductScopeResolutionStatus.NO_MATCH
            scope_type = scope.scope_type
            clarification = False
            reason = "family_constraints_produced_empty_scope"
        elif len(after) == 1:
            status = ProductScopeResolutionStatus.RESOLVED
            scope_type = ProductScopeType.EXACT_CONFIGURATION
            clarification = False
            reason = "family_constraints_resolved_unique_configuration"
        elif require_unique or intent == QueryIntent.CLARIFICATION_REQUIRED:
            status = ProductScopeResolutionStatus.NEEDS_CLARIFICATION
            scope_type = ProductScopeType.PRODUCT_FAMILY
            clarification = True
            reason = "family_scope_requires_configuration_or_region"
        else:
            status = ProductScopeResolutionStatus.RESOLVED
            scope_type = ProductScopeType.PRODUCT_FAMILY
            clarification = False
            reason = "family_scope_retains_multiple_configurations"
        families = sorted({products[item]["attributes"].get("family_id") for item in after})
        configurations = sorted({products[item]["attributes"].get("configuration_id") for item in after})
        regions = sorted({str(products[item]["region"]) for item in after})
        reduced = scope.model_copy(
            update={
                "scope_type": scope_type,
                "product_ids": sorted(after),
                "family_ids": [item for item in families if item is not None],
                "configuration_ids": [item for item in configurations if item is not None],
                "regions": regions,
                "clarification_required": clarification,
                "resolution_status": status,
                "resolution_reason": reason,
            }
        )
        scope.assert_monotonic_transition(reduced.product_ids)
        return reduced, ScopeTransition(before, tuple(reduced.product_ids), reason)
