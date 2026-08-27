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
    rows = {str(row.get("model_id")): row for row in state.candidate_rows if row.get("model_id")}
    model_ids = list(dict.fromkeys([*rows, *state.assessments]))
    candidates: list[CandidateDecision] = []
    all_evidence: list[EvidenceReference] = list(state.kb_hits)
    for model_id in model_ids:
        if model_id in state.requirements.excluded_model_ids:
            continue
        row = rows.get(model_id, {})
        fields = state.assessments.get(model_id, [])
        overall = _overall(fields)
        for field in fields:
            all_evidence.extend(field.evidence)
        blocking = [field for field in fields if field.status != ConstraintStatus.MATCHED]
        candidate = CandidateDecision(
            model_id=model_id,
            brand=row.get("brand"),
            model_name=row.get("model_name"),
            region=row.get("region"),
            price_cny=row.get("price_cny"),
            price_observed_at=row.get("observed_at"),
            overall_status=overall,
            fields=fields,
            recommendation_reason=(
                "本阶段核验的字段均有证据且满足当前条件；阶段 5 仍会进行最终确定性复核。"
                if overall == ConstraintStatus.MATCHED else None
            ),
            elimination_reason=(
                "；".join(f"{item.field}={item.status.value}" for item in blocking)
                if overall != ConstraintStatus.MATCHED else None
            ),
        )
        candidates.append(candidate)
    recommended = [item.model_id for item in candidates if item.overall_status == ConstraintStatus.MATCHED]
    eliminated = [item.model_id for item in candidates if item.overall_status == ConstraintStatus.NOT_MATCHED]
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
    used_structured_candidates = any(
        trace.tool == "text2sql" and trace.status in {"success", "degraded"} for trace in state.traces
    )
    evidence_sufficient = (
        bool(recommended)
        if used_structured_candidates or bool(state.assessments)
        else bool(state.kb_hits)
    )
    return DecisionReport(
        request_summary=state.requirements.summary or state.query[:200],
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
        usage=usage,
    )
