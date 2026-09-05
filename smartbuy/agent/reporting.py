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
    UnresolvedFact,
)
from smartbuy.constraints import VerificationStatus
from smartbuy.agent.fact_completion import from_agent_state


_FIELD_QUERY_MARKERS: dict[str, tuple[str, ...]] = {
    "price_cny": ("价格", "预算", "元以内", "元内"),
    "stock_status": ("库存", "有货", "缺货"),
    "display_size_inch": ("尺寸", "英寸", "寸"),
    "resolution": ("分辨率", "4k", "5k", "8k", "uhd", "qhd", "wqhd", "2k"),
    "refresh_rate_hz": ("刷新率", "hz", "赫兹"),
    "panel_type": ("面板", "ips", "va", "tn"),
    "is_oled": ("oled", "非 oled", "不要 oled"),
    "has_usb_c": ("usb-c", "usb c", "type-c", "type c"),
    "usb_c_video": ("usb-c 视频", "usb c 视频", "type-c 视频", "视频输入"),
    "usb_c_power_delivery_w": ("供电", "pd", "瓦"),
    "stand_adjustment": ("支架", "升降", "旋转", "俯仰"),
    "width_mm": ("宽度", "机身宽", "桌面空间"),
    "weight_kg": ("重量", "多重"),
    "warranty": ("保修", "质保"),
    "region": ("地区", "版本", "中国版", "国行", "美国版", "加拿大版"),
    "brand": ("品牌", "排除 dell", "排除华硕", "只考虑"),
}


def _query_relevant_fields(query: str) -> set[str]:
    normalized = query.casefold()
    return {
        field
        for field, markers in _FIELD_QUERY_MARKERS.items()
        if any(marker in normalized for marker in markers)
    }


def _overall(fields: list[FieldAssessment]) -> ConstraintStatus:
    statuses = {item.status for item in fields}
    if ConstraintStatus.CONFLICT in statuses:
        return ConstraintStatus.CONFLICT
    if ConstraintStatus.NOT_MATCHED in statuses:
        return ConstraintStatus.NOT_MATCHED
    if not fields or ConstraintStatus.UNKNOWN in statuses:
        return ConstraintStatus.UNKNOWN
    return ConstraintStatus.MATCHED


def _merge_status(*statuses: ConstraintStatus) -> ConstraintStatus:
    """Fail closed when the verifier and field evidence disagree."""

    priority = {
        ConstraintStatus.MATCHED: 0,
        ConstraintStatus.UNKNOWN: 1,
        ConstraintStatus.CONFLICT: 2,
        ConstraintStatus.NOT_MATCHED: 3,
    }
    return max(statuses, key=priority.__getitem__)


def build_report(
    state: AgentState,
    *,
    latency_ms: float,
    usage: dict[str, Any],
) -> DecisionReport:
    if state.mode.value == "open" and state.open_research is not None:
        tools = list(
            dict.fromkeys(
                trace.tool
                for trace in state.traces
                if trace.tool not in {"set_requirements", "finish_decision"}
                and trace.status in {"success", "degraded", "unavailable"}
            )
        )
        return DecisionReport(
            mode=state.mode,
            request_summary=state.requirements.summary or state.query[:200],
            task_type=state.requirements.task_type,
            constraint_set=state.constraint_set,
            constraint_proposals=(
                state.constraint_resolution.proposals if state.constraint_resolution else []
            ),
            clarification_state=(
                state.constraint_resolution.clarification_state
                if state.constraint_resolution
                else "not_required"
            ),
            constraint_diff=(
                state.constraint_resolution.diff if state.constraint_resolution else []
            ),
            constraint_verification=state.constraint_verification,
            hard_constraints=state.requirements.hard_constraints,
            soft_preferences=state.requirements.soft_preferences,
            tools_used=tools,
            candidates=[],
            recommended_model_ids=[],
            eliminated_model_ids=[],
            evidence=[],
            unresolved_facts=[],
            degraded_states=list(dict.fromkeys(state.degraded_states)),
            pending_questions=state.requirements.pending_questions,
            abstained=True,
            stop_reason=state.stop_reason or "Open Research 已完成并停止；未生成 Trusted 推荐。",
            trace=state.traces,
            latency_ms=round(latency_ms, 3),
            tool_call_count=state.tool_call_count,
            constraint_check_latency_ms=state.constraint_check_latency_ms,
            usage=usage,
            open_research=state.open_research,
        )
    # A comparison is an evidence-bearing analysis, not a purchase decision.
    # It may populate candidate/evidence sections, but only an explicit filter
    # or dynamic purchase request may publish recommended model ids.
    recommendation_task = state.requirements.task_type in {"filter", "dynamic"}
    fact_task = state.requirements.task_type in {"fact", "comparison"}
    completion = from_agent_state(state) if fact_task else None
    cells = {(row["product_id"], row["field"]): row for row in completion["matrix"]} if completion else {}
    rows = {
        **state.candidate_pool_rows,
        **{str(row.get("model_id")): row for row in state.candidate_rows if row.get("model_id")},
    }
    verification_by_model = {
        item.model_id: item
        for item in (state.constraint_verification.candidates if state.constraint_verification else [])
    }
    active_fields = {item.field for item in state.constraint_set.active()}
    relevant_fields = set(state.requirements.required_fields)
    if state.requirements.task_type == "filter":
        # The planning model may request broad catalog columns for internal ranking.
        # Public output stays scoped to explicit query concepts and provenance-gated constraints.
        relevant_fields &= _query_relevant_fields(state.query)
    relevant_fields.update(active_fields)
    if completion is not None:
        relevant_fields = {row["field"] for row in completion["matrix"]}
    model_ids = (
        list(verification_by_model)
        if verification_by_model
        else list(dict.fromkeys([*rows, *state.assessments]))
    )
    if completion is not None:
        model_ids = list(dict.fromkeys(row["product_id"] for row in completion["matrix"]))
    if state.ranked_eligible_model_ids and not fact_task:
        model_ids = list(
            dict.fromkeys(
                [
                    *state.ranked_eligible_model_ids,
                    *model_ids,
                ]
            )
        )
    candidates: list[CandidateDecision] = []
    # Retrieval references locate sources; without a checked value they are not
    # fact citations and must not shadow a later, properly valued Evidence ref.
    all_evidence: list[EvidenceReference] = [] if fact_task else list(state.kb_hits)
    for model_id in model_ids:
        if model_id in state.requirements.excluded_model_ids:
            continue
        row = rows.get(model_id, {})
        fields = [
            item
            for item in state.assessments.get(model_id, [])
            if not relevant_fields or item.field in relevant_fields
        ]
        if completion is not None:
            original = fields
            fields = []
            for field in sorted(relevant_fields):
                cell = cells[(model_id, field)]
                if cell["status"].startswith("verified_"):
                    status = {
                        "verified_unknown": ConstraintStatus.UNKNOWN,
                        "verified_conflict": ConstraintStatus.CONFLICT,
                        "verified_value": ConstraintStatus.MATCHED,
                    }[cell["status"]]
                    if status == ConstraintStatus.MATCHED and any(
                        item.field == field and item.status == ConstraintStatus.NOT_MATCHED for item in original
                    ):
                        status = ConstraintStatus.NOT_MATCHED
                    fields.append(FieldAssessment(
                        field=field, status=status, actual_value=cell["actual_value"], reason=cell["reason"],
                        evidence=[EvidenceReference.model_validate(item) for item in cell["evidence"]],
                    ))
                else:
                    fields.append(FieldAssessment(
                        field=field, status=ConstraintStatus.UNKNOWN,
                        reason=f"{cell['status']}: {cell['reason']}；尚未完成核验，不能断言资料缺失。",
                    ))
        verification = verification_by_model.get(model_id)
        status_mapping = {
            VerificationStatus.PASSED: ConstraintStatus.MATCHED,
            VerificationStatus.FAILED: ConstraintStatus.NOT_MATCHED,
            VerificationStatus.UNKNOWN: ConstraintStatus.UNKNOWN,
            VerificationStatus.CONFLICT: ConstraintStatus.CONFLICT,
        }
        if recommendation_task and verification:
            verifier_overall = status_mapping[verification.overall_status]
            overall = (
                _merge_status(verifier_overall, _overall(fields))
                if fields
                else verifier_overall
            )
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
            eligible=(
                bool(recommendation_task and verification.eligible and overall == ConstraintStatus.MATCHED)
                if verification
                else recommendation_task and overall == ConstraintStatus.MATCHED
            ),
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
                if recommendation_task and verification and verification.eligible else None
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
    eliminated = [item.model_id for item in candidates if not item.eligible] if recommendation_task and verification_by_model else [
        item.model_id for item in candidates if item.overall_status == ConstraintStatus.NOT_MATCHED
    ]
    if fact_task:
        eliminated = []
    candidate_ids = {item.model_id for item in candidates}
    unique_evidence: list[EvidenceReference] = []
    seen: set[tuple[str, str | None, str]] = set()
    for item in all_evidence:
        if candidate_ids and item.model_id not in candidate_ids:
            continue
        if relevant_fields and item.field not in relevant_fields:
            continue
        key = (item.source_id, item.evidence_id, item.model_id)
        if key not in seen:
            seen.add(key)
            unique_evidence.append(item)
    unresolved_facts: list[UnresolvedFact] = []
    unresolved_keys: set[tuple[str | None, str, str]] = set()
    observed_fields: set[str] = set()
    for candidate in candidates:
        observed_fields.update(item.field for item in candidate.fields)
        observed_fields.update(item.constraint.field for item in candidate.constraint_results)
        for field in candidate.fields:
            if field.status not in {ConstraintStatus.UNKNOWN, ConstraintStatus.CONFLICT}:
                continue
            key = (candidate.model_id, field.field, field.status.value)
            if key in unresolved_keys:
                continue
            unresolved_keys.add(key)
            values = (
                list(field.actual_value)
                if isinstance(field.actual_value, (list, tuple, set))
                else ([field.actual_value] if field.actual_value is not None else [])
            )
            unresolved_facts.append(
                UnresolvedFact(
                    model_id=candidate.model_id,
                    field=field.field,
                    status=field.status.value,
                    values=values,
                    reason=field.reason,
                    evidence=field.evidence,
                )
            )
    for constraint in state.constraint_set.active():
        if constraint.supported and not constraint.ambiguous:
            continue
        key = (None, constraint.field, ConstraintStatus.UNKNOWN.value)
        if key in unresolved_keys:
            continue
        unresolved_keys.add(key)
        observed_fields.add(constraint.field)
        unresolved_facts.append(
            UnresolvedFact(
                field=constraint.field,
                status=ConstraintStatus.UNKNOWN.value,
                reason=constraint.note or "该约束不在当前支持范围或表达有歧义，需要用户确认。",
            )
        )
    for field in sorted(relevant_fields - observed_fields):
        key = (None, field, ConstraintStatus.UNKNOWN.value)
        if key in unresolved_keys:
            continue
        unresolved_keys.add(key)
        unresolved_facts.append(
            UnresolvedFact(
                field=field,
                status=ConstraintStatus.UNKNOWN.value,
                reason="未获得该字段的可核验证据；工具不可用、候选为空或本轮未完成核验。",
            )
        )
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
    elif completion is not None:
        evidence_sufficient = completion["answer_sufficient"]
    else:
        evidence_sufficient = bool(state.kb_hits) and not (
            {ConstraintStatus.UNKNOWN, ConstraintStatus.CONFLICT} & evidence_statuses
        )
    stop_reason = state.stop_reason or "达到有界执行停止条件。"
    if completion is not None:
        usage = {**usage, "fact_completion": {**completion, "checks": state.fact_completion_checks},
                 "verification_tools_used": list(dict.fromkeys(check["tool"] for check in state.fact_completion_checks))}
        if completion["completion_status"] == "complete":
            stop_reason = ("全部目标商品—请求字段已完成核验。" if evidence_sufficient else
                           "全部目标商品—请求字段已核验；存在 unknown/conflict，不作确定事实或购买满足声明。")
        else:
            stop_reason = (f"字段核验{completion['completion_status']}："
                           f"{completion['checked_count']}/{completion['required_count']}；"
                           "未核验、工具失败或预算耗尽的字段明确保留，不宣称证据充分，安全停止。")
        usage["result_status"] = "answer_available" if evidence_sufficient else "partial_answer" if completion["checked_count"] else "unable_to_verify"
    return DecisionReport(
        request_summary=state.requirements.summary or state.query[:200],
        task_type=state.requirements.task_type,
        constraint_set=state.constraint_set,
        constraint_proposals=(
            state.constraint_resolution.proposals if state.constraint_resolution else []
        ),
        clarification_state=(
            state.constraint_resolution.clarification_state
            if state.constraint_resolution
            else "not_required"
        ),
        constraint_diff=(state.constraint_resolution.diff if state.constraint_resolution else []),
        constraint_verification=state.constraint_verification,
        hard_constraints=state.requirements.hard_constraints,
        soft_preferences=state.requirements.soft_preferences,
        tools_used=tools,
        candidates=candidates,
        recommended_model_ids=recommended,
        eliminated_model_ids=eliminated,
        evidence=unique_evidence,
        unresolved_facts=unresolved_facts,
        degraded_states=list(dict.fromkeys(state.degraded_states)),
        pending_questions=state.requirements.pending_questions,
        abstained=not evidence_sufficient,
        stop_reason=stop_reason,
        trace=state.traces,
        latency_ms=round(latency_ms, 3),
        tool_call_count=state.tool_call_count,
        constraint_check_latency_ms=state.constraint_check_latency_ms,
        usage=usage,
    )
