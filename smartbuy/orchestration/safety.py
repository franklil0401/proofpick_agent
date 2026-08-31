"""Orchestration-level invariant checks around the existing deterministic gate."""

from __future__ import annotations

from smartbuy.domain import DecisionReport


class SafetyGateError(RuntimeError):
    pass


def validate_checker_terminal(report: DecisionReport) -> None:
    """Reject every recommendation not authorized by the existing Checker output."""
    verification = report.constraint_verification
    if verification is None:
        if report.recommended_model_ids:
            raise SafetyGateError("recommendation_without_constraint_verification")
        raise SafetyGateError("constraint_verification_missing")
    eligible = set(verification.eligible_model_ids)
    recommended = set(report.recommended_model_ids)
    if not recommended.issubset(eligible):
        raise SafetyGateError("recommendation_outside_checker_eligible_set")
    if verification.degraded and recommended:
        raise SafetyGateError("recommendation_during_checker_degradation")
    reported_eligible = {item.model_id for item in report.candidates if item.eligible}
    if reported_eligible - eligible:
        raise SafetyGateError("candidate_eligibility_disagrees_with_checker")


def fail_closed_report(report: DecisionReport, reason: str) -> DecisionReport:
    """Remove recommendation authority without inventing product or evidence facts."""
    safe = report.model_copy(deep=True)
    safe.recommended_model_ids = []
    safe.abstained = True
    safe.stop_reason = f"编排安全门已阻断推荐：{reason[:160]}"
    marker = f"orchestration_fail_closed:{reason[:120]}"
    if marker not in safe.degraded_states:
        safe.degraded_states.append(marker)
    for candidate in safe.candidates:
        candidate.eligible = False
        candidate.recommendation_reason = None
        candidate.elimination_reason = candidate.elimination_reason or "编排安全门未确认推荐资格。"
    return safe
