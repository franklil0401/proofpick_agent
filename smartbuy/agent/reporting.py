"""Deterministic report assembly from tool observations."""

from __future__ import annotations

from typing import Any

from smartbuy.domain import (
    AgentState,
    CandidateDecision,
    ConstraintStatus,
    DecisionReport,
    EvidenceReference,
    FieldAssessment,
)
from smartbuy.constraints import VerificationStatus


def _overall(fields: list[FieldAssessment]) -> ConstraintStatus:
    statuses = {item.status for item in fields}
    if ConstraintStatus.CONFLICT in statuses:
        return ConstraintStatus.CONFLICT
    if ConstraintStatus.NOT_MATCHED in statuses:
        return ConstraintStatus.NOT_MATCHED
    if not fields or ConstraintStatus.UNKNOWN in statuses:
        return ConstraintStatus.UNKNOWN
    return ConstraintStatus.MATCHED


def build_report(
    state: AgentState,
    *,
    latency_ms: float,
    usage: dict[str, Any],
) -> DecisionReport:
    recommendation_task = state.requirements.task_type in {"filter", "comparison", "dynamic"}
    rows = {
        **state.candidate_pool_rows,
        **{str(row.get("model_id")): row for row in state.candidate_rows if row.get("model_id")},
    }
    verification_by_model = {
        item.model_id: item
        for item in (state.constraint_verification.candidates if state.constraint_verification else [])
    }
    model_ids = (
        list(verification_by_model)
        if verification_by_model
        else list(dict.fromkeys([*rows, *state.assessments]))
    )
    if state.ranked_eligible_model_ids:
        model_ids = list(
            dict.fromkeys(
                [
                    *state.ranked_eligible_model_ids,
                    *model_ids,
                ]
            )
        )
    candidates: list[CandidateDecision] = []
    all_evidence: list[EvidenceReference] = list(state.kb_hits)
    for model_id in model_ids:
        if model_id in state.requirements.excluded_model_ids:
            continue
        row = rows.get(model_id, {})
        fields = state.assessments.get(model_id, [])
        verification = verification_by_model.get(model_id)
        status_mapping = {
            VerificationStatus.PASSED: ConstraintStatus.MATCHED,
            VerificationStatus.FAILED: ConstraintStatus.NOT_MATCHED,
            VerificationStatus.UNKNOWN: ConstraintStatus.UNKNOWN,
            VerificationStatus.CONFLICT: ConstraintStatus.CONFLICT,
        }
        if recommendation_task and verification:
            overall = status_mapping[verification.overall_status]
        elif fields:
            overall = _overall(fields)
        else:
            overall = status_mapping[verification.overall_status] if verification else _overall(fields)
        for field in fields:
            all_evidence.extend(field.evidence)
        blocking = [field for field in fields if field.status != ConstraintStatus.MATCHED]
        price_result = next(
            (
                result
                for result in (verification.constraint_results if verification else [])
                if result.constraint.field == "price_cny"
            ),
            None,
        )
        candidate = CandidateDecision(
            model_id=model_id,
            brand=row.get("brand"),
            model_name=row.get("model_name"),
            region=row.get("region"),
            price_cny=(price_result.actual_value if price_result else row.get("price_cny")),
            price_observed_at=(
                verification.price_observed_at if verification else row.get("observed_at")
            ),
            overall_status=overall,
            fields=fields,
            eligible=bool(verification and verification.eligible),
            verifier_status=verification.overall_status if verification else None,
            constraint_results=verification.constraint_results if verification else [],
            violated_fields=verification.violated_fields if verification else [],
            unknown_fields=verification.unknown_fields if verification else [],
            conflict_fields=verification.conflict_fields if verification else [],
            unsupported_constraints=verification.unsupported_constraints if verification else [],
            verifier_version=verification.verifier_version if verification else None,
            recommendation_reason=(
                state.candidate_explanations.get(model_id)
                or "Constraint Checker 已确认全部受支持硬约束通过；软偏好只能影响排序，不能改变资格。"
                if verification and verification.eligible else None
            ),
            elimination_reason=(
                "；".join(
                    [
                        *[f"{field}=failed" for field in (verification.violated_fields if verification else [])],
                        *[f"{field}=unknown" for field in (verification.unknown_fields if verification else [])],
                        *[f"{field}=conflict" for field in (verification.conflict_fields if verification else [])],
                        *[f"{item.field}={item.status.value}" for item in blocking],
                    ]
                )
                if overall != ConstraintStatus.MATCHED else None
            ),
        )
        candidates.append(candidate)
    recommended = [item.model_id for item in candidates if item.eligible] if recommendation_task else []
    eliminated = [item.model_id for item in candidates if not item.eligible] if verification_by_model else [
        item.model_id for item in candidates if item.overall_status == ConstraintStatus.NOT_MATCHED
    ]
    unique_evidence: list[EvidenceReference] = []
    seen: set[tuple[str, str | None, str]] = set()
    for item in all_evidence:
        key = (item.source_id, item.evidence_id, item.model_id)
        if key not in seen:
            seen.add(key)
            unique_evidence.append(item)
    tools = list(
        dict.fromkeys(
            trace.tool
            for trace in state.traces
            if trace.tool not in {"set_requirements", "finish_decision"}
            and trace.status in {"success", "degraded", "unavailable"}
        )
    )
    evidence_statuses = {
        item.status for assessments in state.assessments.values() for item in assessments
    }
    if state.requirements.task_type == "unrelated":
        evidence_sufficient = False
    elif recommendation_task:
        evidence_sufficient = bool(recommended)
    else:
        evidence_sufficient = bool(state.kb_hits) and not (
            {ConstraintStatus.UNKNOWN, ConstraintStatus.CONFLICT} & evidence_statuses
        )
    return DecisionReport(
        request_summary=state.requirements.summary or state.query[:200],
        task_type=state.requirements.task_type,
        constraint_set=state.constraint_set,
        constraint_verification=state.constraint_verification,
        hard_constraints=state.requirements.hard_constraints,
        soft_preferences=state.requirements.soft_preferences,
        tools_used=tools,
        candidates=candidates,
        recommended_model_ids=recommended,
        eliminated_model_ids=eliminated,
        evidence=unique_evidence,
        degraded_states=list(dict.fromkeys(state.degraded_states)),
        pending_questions=state.requirements.pending_questions,
        abstained=not evidence_sufficient,
        stop_reason=state.stop_reason or "达到有界执行停止条件。",
        trace=state.traces,
        latency_ms=round(latency_ms, 3),
        tool_call_count=state.tool_call_count,
        constraint_check_latency_ms=state.constraint_check_latency_ms,
        usage=usage,
    )
