"""Deterministic outcome classification for every governed product domain."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DecisionResultStatus(StrEnum):
    RECOMMENDATION_AVAILABLE = "recommendation_available"
    ANSWER_AVAILABLE = "answer_available"
    NO_MATCHING_CANDIDATE = "no_matching_candidate"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED_REQUEST = "unsupported_request"
    TOOL_FAILURE = "tool_failure"
    SAFETY_BLOCKED = "safety_blocked"


@dataclass(frozen=True)
class ResultClassificationInput:
    recommendation_task: bool
    clarification_required: bool = False
    unsupported_request: bool = False
    tool_failure: bool = False
    safety_blocked: bool = False
    candidate_count: int = 0
    eligible_count: int = 0
    evidence_complete_count: int = 0
    unknown_or_conflict_count: int = 0


@dataclass(frozen=True)
class ResultClassification:
    status: DecisionResultStatus
    abstained: bool
    reason: str


def classify_result(value: ResultClassificationInput) -> ResultClassification:
    """Classify from deterministic state; text generation has no authority here."""

    if value.safety_blocked:
        return ResultClassification(
            DecisionResultStatus.SAFETY_BLOCKED,
            True,
            "候选范围安全门阻断了结果，未输出购买推荐。",
        )
    if value.clarification_required:
        return ResultClassification(
            DecisionResultStatus.NEEDS_CLARIFICATION,
            True,
            "等待用户澄清；未执行确定性推荐。",
        )
    if value.tool_failure:
        return ResultClassification(
            DecisionResultStatus.TOOL_FAILURE,
            True,
            "必要工具失败，不能伪装成没有合适商品。",
        )
    if value.recommendation_task:
        if value.eligible_count and value.evidence_complete_count:
            return ResultClassification(
                DecisionResultStatus.RECOMMENDATION_AVAILABLE,
                False,
                "存在范围内、Checker 合规且证据完整的候选。",
            )
        if value.eligible_count or value.unknown_or_conflict_count:
            return ResultClassification(
                DecisionResultStatus.INSUFFICIENT_EVIDENCE,
                True,
                "候选证据不足或存在 unknown/conflict，不能完成推荐。",
            )
        if value.unsupported_request:
            return ResultClassification(
                DecisionResultStatus.UNSUPPORTED_REQUEST,
                True,
                "请求包含当前 Domain Pack 不支持且无法安全完成的条件。",
            )
        return ResultClassification(
            DecisionResultStatus.NO_MATCHING_CANDIDATE,
            True,
            "确定性复核后没有满足全部硬约束的候选。",
        )
    if value.evidence_complete_count:
        return ResultClassification(
            DecisionResultStatus.ANSWER_AVAILABLE,
            False,
            "目标范围内的请求字段均有可追溯治理证据。",
        )
    if value.unsupported_request:
        return ResultClassification(
            DecisionResultStatus.UNSUPPORTED_REQUEST,
            True,
            "请求字段不在当前 Domain Pack 支持范围。",
        )
    return ResultClassification(
        DecisionResultStatus.INSUFFICIENT_EVIDENCE,
        True,
        "目标范围缺少完成事实核验所需的治理证据。",
    )
