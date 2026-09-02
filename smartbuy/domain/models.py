"""Validated public state and report schemas for the purchase-decision workflow."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from smartbuy.constraints.models import (
    ConstraintResult as DeterministicConstraintResult,
    ConstraintSet,
    VerificationBatch,
    VerificationStatus,
)
from smartbuy.constraint_proposals.models import (
    ClarificationState,
    ConstraintDiff,
    ConstraintProposal,
    ConstraintResolution,
)
from smartbuy.open_research.models import OpenResearchReport, ResearchMode


class ConstraintStatus(StrEnum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class ConstraintOperator(StrEnum):
    EQ = "eq"
    LTE = "lte"
    GTE = "gte"
    IN = "in"
    NOT_IN = "not_in"


class ConstraintSpec(BaseModel):
    field: str
    operator: ConstraintOperator = ConstraintOperator.EQ
    value: Any
    hard: bool = True


class UserRequirements(BaseModel):
    summary: str = ""
    task_type: Literal["fact", "filter", "comparison", "dynamic", "unrelated"] = "fact"
    hard_constraints: list[ConstraintSpec] = Field(default_factory=list)
    soft_preferences: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    excluded_model_ids: list[str] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)

    @field_validator("required_fields", "excluded_model_ids")
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


class AgentLimits(BaseModel):
    max_steps: int = Field(default=8, ge=1, le=8)
    max_tool_calls: int = Field(default=12, ge=1, le=16)
    tool_timeout_seconds: float = Field(default=20.0, ge=0.1, le=60.0)
    max_task_cost_cny: float = Field(default=0.25, gt=0, le=1.0)


class EvidenceReference(BaseModel):
    evidence_id: str | None = None
    source_id: str
    source_url: str
    source_type: str
    model_id: str
    region: str
    field: str | None = None
    value: Any = None
    location: str | None = None
    effective_time: str | None = None


class FieldAssessment(BaseModel):
    field: str
    status: ConstraintStatus
    actual_value: Any = None
    expected: ConstraintSpec | None = None
    reason: str
    evidence: list[EvidenceReference] = Field(default_factory=list)


class CandidateDecision(BaseModel):
    model_id: str
    brand: str | None = None
    model_name: str | None = None
    region: str | None = None
    price_cny: float | None = None
    price_observed_at: str | None = None
    overall_status: ConstraintStatus
    fields: list[FieldAssessment] = Field(default_factory=list)
    eligible: bool = False
    verifier_status: VerificationStatus | None = None
    constraint_results: list[DeterministicConstraintResult] = Field(default_factory=list)
    violated_fields: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    conflict_fields: list[str] = Field(default_factory=list)
    unsupported_constraints: list[str] = Field(default_factory=list)
    verifier_version: str | None = None
    recommendation_reason: str | None = None
    elimination_reason: str | None = None


class ToolTrace(BaseModel):
    step: int
    parent_step: int | None = None
    task_summary: str
    tool: str
    arguments_summary: dict[str, Any] = Field(default_factory=dict)
    status: Literal["success", "failed", "degraded", "unavailable"]
    result_summary: str
    next_action: str
    stop_or_degrade_reason: str | None = None
    duration_ms: float = Field(default=0.0, ge=0)


class UnresolvedFact(BaseModel):
    """Public, evidence-bound unknown or conflict that blocks a stronger claim."""

    model_id: str | None = None
    field: str
    status: Literal["unknown", "conflict"]
    values: list[Any] = Field(default_factory=list)
    reason: str
    evidence: list[EvidenceReference] = Field(default_factory=list)


class DecisionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: str = "smartbuy-decision-v3"
    mode: ResearchMode = ResearchMode.TRUSTED
    request_summary: str
    task_type: Literal["fact", "filter", "comparison", "dynamic", "unrelated"] = "fact"
    constraint_set: ConstraintSet = Field(default_factory=ConstraintSet)
    constraint_proposals: list[ConstraintProposal] = Field(default_factory=list)
    clarification_state: ClarificationState = ClarificationState.NOT_REQUIRED
    constraint_diff: list[ConstraintDiff] = Field(default_factory=list)
    constraint_verification: VerificationBatch | None = None
    hard_constraints: list[ConstraintSpec] = Field(default_factory=list)
    soft_preferences: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    candidates: list[CandidateDecision] = Field(default_factory=list)
    recommended_model_ids: list[str] = Field(default_factory=list)
    eliminated_model_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    unresolved_facts: list[UnresolvedFact] = Field(default_factory=list)
    degraded_states: list[str] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)
    abstained: bool = False
    stop_reason: str
    trace: list[ToolTrace] = Field(default_factory=list)
    latency_ms: float = 0.0
    tool_call_count: int = 0
    constraint_check_latency_ms: float = 0.0
    usage: dict[str, Any] = Field(default_factory=dict)
    open_research: OpenResearchReport | None = None

    @model_validator(mode="after")
    def enforce_mode_boundary(self) -> DecisionReport:
        if self.mode == ResearchMode.OPEN:
            if self.open_research is None:
                raise ValueError("Open Mode report requires an open_research payload")
            if self.recommended_model_ids or any(item.eligible for item in self.candidates):
                raise ValueError("Open Mode cannot expose Trusted eligible recommendations")
        elif self.open_research is not None:
            raise ValueError("Trusted Mode cannot contain open_research evidence")
        return self

    def to_markdown(self) -> str:
        if self.mode == ResearchMode.OPEN:
            assert self.open_research is not None
            lines = [
                "# ProofPick 开放研究报告",
                "",
                f"**需求摘要：** {self.request_summary}",
                "**运行模式：** Open Research（非 Trusted 推荐）",
                "",
                self.open_research.to_markdown(),
                "",
                "## 可审计工具轨迹",
                "",
            ]
            if not self.trace:
                lines.append("- 无")
            for item in self.trace:
                lines.append(
                    f"- step {item.step} / `{item.tool}` / **{item.status}**：{item.result_summary}"
                )
            if self.degraded_states:
                lines.extend(["", "## 降级状态", ""])
                lines.extend(f"- {item}" for item in self.degraded_states)
            lines.extend(["", "## 停止原因", "", self.stop_reason, ""])
            if self.constraint_verification is not None:
                lines.extend(
                    [
                        "## Trusted Checker 隔离审计",
                        "",
                        "- Open 商品进入 Trusted candidate pool：`0`",
                        "- Open 商品进入 Trusted eligible：`0`",
                        f"- Trusted 候选池：{', '.join(self.constraint_verification.candidate_pool_model_ids) or '空'}",
                        "",
                    ]
                )
            return "\n".join(lines)
        lines = [
            "# SmartBuy 消费决策报告", "", f"**需求摘要：** {self.request_summary}",
            f"**任务类型：** {self.task_type}", "",
        ]
        if self.hard_constraints:
            lines.extend(["## 硬约束", ""])
            for item in self.hard_constraints:
                lines.append(f"- `{item.field} {item.operator.value} {item.value}`")
            lines.append("")
        if self.constraint_proposals:
            lines.extend(["## 约束理解", ""])
            for item in self.constraint_proposals:
                active = "active" if item.active else "blocked"
                lines.append(
                    f"- `{item.source_span.text}` → `{item.field}`："
                    f"**{item.status.value}** / {active} / {item.action.value}"
                )
            if self.constraint_diff:
                lines.append(f"- 本轮约束变更：{len(self.constraint_diff)} 项")
            lines.append("")
        active_constraints = self.constraint_set.active()
        if active_constraints:
            lines.extend(["## 带来源的约束集合", ""])
            for item in active_constraints:
                support = "supported" if item.supported and not item.ambiguous else "unsupported/ambiguous"
                lines.append(
                    f"- `{item.field} {item.operator.value} {item.normalized_value}` "
                    f"（{item.hard_or_soft.value}；{item.provenance.value}；{support}；turn {item.source_turn}）"
                )
            lines.append("")
        if self.soft_preferences:
            lines.extend(["## 软偏好", "", *[f"- {item}" for item in self.soft_preferences], ""])
        lines.extend(["## 实际工具", "", ", ".join(self.tools_used) or "无", ""])
        lines.extend(["## 候选判断", ""])
        if not self.candidates:
            lines.extend(["没有可被完整验证的候选。", ""])
        for candidate in self.candidates:
            title = " / ".join(filter(None, [candidate.brand, candidate.model_name, candidate.region]))
            lines.append(f"### {candidate.model_id}（{candidate.overall_status.value}）")
            lines.append("")
            if title:
                lines.append(f"- 型号：{title}")
            if candidate.price_cny is not None:
                lines.append(f"- 价格观测：¥{candidate.price_cny:.2f}（{candidate.price_observed_at or '时间未知'}）")
            if candidate.verifier_status is not None:
                lines.append(
                    f"- Constraint Checker：**{candidate.verifier_status.value}**；"
                    f"eligible={str(candidate.eligible).lower()}；version={candidate.verifier_version}"
                )
                if candidate.violated_fields:
                    lines.append(f"- 违规字段：{', '.join(candidate.violated_fields)}")
                if candidate.unknown_fields:
                    lines.append(f"- 未知字段：{', '.join(candidate.unknown_fields)}")
                if candidate.conflict_fields:
                    lines.append(f"- 冲突字段：{', '.join(candidate.conflict_fields)}")
                if candidate.unsupported_constraints:
                    lines.append(f"- 未支持约束：{', '.join(candidate.unsupported_constraints)}")
                for result in candidate.constraint_results:
                    lines.append(
                        f"- 复核 `{result.constraint.field}`：**{result.status.value}**；"
                        f"实际值 `{result.actual_value}`；要求 `{result.constraint.normalized_value}`；{result.reason}"
                    )
            for field in candidate.fields:
                value_text = f"；值 `{field.actual_value}`" if field.actual_value is not None else ""
                lines.append(
                    f"- `{field.field}`：**{field.status.value}**{value_text} — {field.reason}"
                )
            if candidate.recommendation_reason:
                lines.append(f"- 推荐理由：{candidate.recommendation_reason}")
            if candidate.elimination_reason:
                lines.append(f"- 淘汰理由：{candidate.elimination_reason}")
            lines.append("")
        if self.unresolved_facts:
            lines.extend(["## 未知与冲突", ""])
            for item in self.unresolved_facts:
                subject = f"{item.model_id} / " if item.model_id else ""
                values = f"；观测值：{', '.join(str(value) for value in item.values)}" if item.values else ""
                lines.append(
                    f"- `{subject}{item.field}`：**{item.status}**{values}；{item.reason}"
                )
                for evidence in item.evidence:
                    evidence_value = (
                        f"（值：{evidence.value}）" if evidence.value is not None else ""
                    )
                    lines.append(
                        f"  - [{evidence.source_id}]({evidence.source_url}){evidence_value}"
                    )
            lines.append("")
        lines.extend(["## 证据来源", ""])
        if not self.evidence:
            lines.append("- 暂无足够的可访问证据。")
        else:
            seen: set[tuple[str, str | None]] = set()
            for item in self.evidence:
                key = (item.source_url, item.field)
                if key in seen:
                    continue
                seen.add(key)
                label = f"{item.model_id} / {item.field or '检索片段'} / {item.region}"
                observed = f" / {item.effective_time}" if item.effective_time else ""
                lines.append(f"- [{label}{observed}]({item.source_url})")
        lines.append("")
        if self.degraded_states:
            lines.extend(["## 降级状态", "", *[f"- {item}" for item in self.degraded_states], ""])
        if self.pending_questions:
            lines.extend(["## 仍需确认", "", *[f"- {item}" for item in self.pending_questions], ""])
        if self.abstained:
            lines.extend(["## 结论", "", "证据不足或存在冲突，本次不输出完全满足条件的推荐。", ""])
        lines.extend(["## 停止原因", "", self.stop_reason, ""])
        if self.constraint_verification is not None:
            lines.extend(
                [
                    "## Constraint Checker 审计",
                    "",
                    f"- 版本：`{self.constraint_verification.verifier_version}`",
                    f"- 复核时间策略：`{self.constraint_verification.checked_at}`",
                    f"- 完整候选池：{', '.join(self.constraint_verification.candidate_pool_model_ids) or '空'}",
                    f"- 合规候选：{', '.join(self.constraint_verification.eligible_model_ids) or '空'}",
                    f"- Checker 延迟：{self.constraint_check_latency_ms:.3f} ms（不调用模型）",
                    f"- 语义指纹：`{self.constraint_verification.semantic_fingerprint}`",
                    f"- 降级：{str(self.constraint_verification.degraded).lower()}",
                    "",
                ]
            )
        return "\n".join(lines)


class AgentState(BaseModel):
    session_id: str
    user_id: str | None = None
    query: str
    mode: ResearchMode = ResearchMode.TRUSTED
    thread_id: str | None = None
    turn_number: int = Field(default=1, ge=1)
    requirements: UserRequirements = Field(default_factory=UserRequirements)
    constraint_set: ConstraintSet = Field(default_factory=ConstraintSet)
    constraint_resolution: ConstraintResolution | None = None
    candidate_rows: list[dict[str, Any]] = Field(default_factory=list)
    candidate_pool_rows: dict[str, dict[str, Any]] = Field(default_factory=dict)
    candidate_pool_sources: dict[str, list[str]] = Field(default_factory=dict)
    assessments: dict[str, list[FieldAssessment]] = Field(default_factory=dict)
    kb_hits: list[EvidenceReference] = Field(default_factory=list)
    traces: list[ToolTrace] = Field(default_factory=list)
    degraded_states: list[str] = Field(default_factory=list)
    verified_fields: dict[str, list[str]] = Field(default_factory=dict)
    tool_call_count: int = 0
    stop_reason: str | None = None
    finished: bool = False
    constraint_verification: VerificationBatch | None = None
    constraint_check_latency_ms: float = 0.0
    ranked_eligible_model_ids: list[str] = Field(default_factory=list)
    candidate_explanations: dict[str, str] = Field(default_factory=dict)
    source_candidates: dict[str, dict[str, Any]] = Field(default_factory=dict)
    open_research: OpenResearchReport | None = None
