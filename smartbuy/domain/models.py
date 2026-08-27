"""Validated public state and report schemas for the purchase-decision workflow."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class DecisionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: str = "smartbuy-decision-v1"
    request_summary: str
    hard_constraints: list[ConstraintSpec] = Field(default_factory=list)
    soft_preferences: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    candidates: list[CandidateDecision] = Field(default_factory=list)
    recommended_model_ids: list[str] = Field(default_factory=list)
    eliminated_model_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    degraded_states: list[str] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)
    abstained: bool = False
    stop_reason: str
    trace: list[ToolTrace] = Field(default_factory=list)
    latency_ms: float = 0.0
    tool_call_count: int = 0
    usage: dict[str, Any] = Field(default_factory=dict)

    def to_markdown(self) -> str:
        lines = ["# SmartBuy 消费决策报告", "", f"**需求摘要：** {self.request_summary}", ""]
        if self.hard_constraints:
            lines.extend(["## 硬约束", ""])
            for item in self.hard_constraints:
                lines.append(f"- `{item.field} {item.operator.value} {item.value}`")
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
            for field in candidate.fields:
                lines.append(f"- `{field.field}`：**{field.status.value}** — {field.reason}")
            if candidate.recommendation_reason:
                lines.append(f"- 推荐理由：{candidate.recommendation_reason}")
            if candidate.elimination_reason:
                lines.append(f"- 淘汰理由：{candidate.elimination_reason}")
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
                lines.append(f"- [{label}]({item.source_url})")
        lines.append("")
        if self.degraded_states:
            lines.extend(["## 降级状态", "", *[f"- {item}" for item in self.degraded_states], ""])
        if self.pending_questions:
            lines.extend(["## 仍需确认", "", *[f"- {item}" for item in self.pending_questions], ""])
        if self.abstained:
            lines.extend(["## 结论", "", "证据不足或存在冲突，本次不输出完全满足条件的推荐。", ""])
        lines.extend(["## 停止原因", "", self.stop_reason, ""])
        return "\n".join(lines)


class AgentState(BaseModel):
    session_id: str
    user_id: str | None = None
    query: str
    requirements: UserRequirements = Field(default_factory=UserRequirements)
    candidate_rows: list[dict[str, Any]] = Field(default_factory=list)
    assessments: dict[str, list[FieldAssessment]] = Field(default_factory=dict)
    kb_hits: list[EvidenceReference] = Field(default_factory=list)
    traces: list[ToolTrace] = Field(default_factory=list)
    degraded_states: list[str] = Field(default_factory=list)
    verified_fields: dict[str, list[str]] = Field(default_factory=dict)
    tool_call_count: int = 0
    stop_reason: str | None = None
    finished: bool = False
