"""Fail-closed candidate-chain invariants shared by every product domain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from smartbuy.identity import ResolvedProductScope


class CandidateChainViolation(ValueError):
    def __init__(self, code: str, stage: str) -> None:
        super().__init__(code)
        self.code = code
        self.stage = stage


@dataclass(frozen=True)
class CandidateChainSnapshot:
    catalog_ids: frozenset[str]
    scope_ids: frozenset[str]
    checker_pool_ids: frozenset[str]
    checker_eligible_ids: frozenset[str]
    report_ids: frozenset[str]
    recommended_ids: frozenset[str]


def _ids(values: Iterable[str]) -> frozenset[str]:
    return frozenset(str(value) for value in values)


def assert_candidate_chain(
    *,
    catalog_ids: Iterable[str],
    scope: ResolvedProductScope,
    checker_pool_ids: Iterable[str] = (),
    checker_eligible_ids: Iterable[str] = (),
    report_ids: Iterable[str] = (),
    recommended_ids: Iterable[str] = (),
    stage: str,
) -> CandidateChainSnapshot:
    """Require recommendation authority to shrink monotonically toward output."""

    snapshot = CandidateChainSnapshot(
        catalog_ids=_ids(catalog_ids),
        scope_ids=_ids(scope.product_ids),
        checker_pool_ids=_ids(checker_pool_ids),
        checker_eligible_ids=_ids(checker_eligible_ids),
        report_ids=_ids(report_ids),
        recommended_ids=_ids(recommended_ids),
    )
    if not snapshot.scope_ids <= snapshot.catalog_ids:
        raise CandidateChainViolation("scope_outside_domain_catalog", stage)
    if not snapshot.checker_pool_ids <= snapshot.scope_ids:
        raise CandidateChainViolation("checker_pool_outside_candidate_scope", stage)
    if not snapshot.checker_eligible_ids <= snapshot.checker_pool_ids:
        raise CandidateChainViolation("checker_eligible_outside_checker_pool", stage)
    if not snapshot.report_ids <= snapshot.scope_ids:
        raise CandidateChainViolation("report_outside_candidate_scope", stage)
    if not snapshot.recommended_ids <= snapshot.checker_eligible_ids:
        raise CandidateChainViolation("recommendation_outside_checker_eligible", stage)
    return snapshot


def assert_scope_restore(
    current_scope: ResolvedProductScope,
    restored_product_ids: Iterable[str],
) -> None:
    """A checkpoint may restore an equal or narrower set, never an older wider set."""

    try:
        current_scope.assert_monotonic_transition(list(restored_product_ids))
    except ValueError as exc:
        raise CandidateChainViolation("checkpoint_scope_expansion", "checkpoint_restore") from exc
