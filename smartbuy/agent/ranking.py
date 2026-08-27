"""LLM soft-preference ranking behind an immutable deterministic eligibility set."""

from __future__ import annotations

import json
from typing import Any

from smartbuy.constraints import (
    ConstraintProvenance,
    ConstraintStrength,
    NormalizedConstraint,
    VerificationBatch,
)


def enforce_eligible_ranking(
    eligible_model_ids: list[str],
    proposed_order: list[str],
    proposed_explanations: dict[str, Any] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Filter model output and append omissions so it cannot add or delete eligible candidates."""
    eligible = list(dict.fromkeys(eligible_model_ids))
    allowed = set(eligible)
    order = list(dict.fromkeys(item for item in proposed_order if item in allowed))
    order.extend(item for item in eligible if item not in order)
    raw_explanations = proposed_explanations or {}
    explanations = {
        model_id: str(raw_explanations[model_id])[:240]
        for model_id in order
        if model_id in raw_explanations
    }
    return order, explanations


async def rank_compliant_candidates(
    provider: Any,
    verification: VerificationBatch,
    soft_constraints: list[NormalizedConstraint],
) -> tuple[list[str], dict[str, str], bool]:
    """Ask the LLM only to order the immutable eligible set; return deterministic fallback on failure."""
    eligible = verification.eligible_model_ids
    active_soft = [
        item
        for item in soft_constraints
        if item.active
        and item.hard_or_soft == ConstraintStrength.SOFT
        and item.provenance != ConstraintProvenance.SYSTEM_DEFAULT
        and item.supported
        and not item.ambiguous
    ]
    if len(eligible) < 2 or not active_soft:
        order, explanations = enforce_eligible_ranking(eligible, eligible)
        return order, explanations, False
    candidates = {
        item.model_id: {
            result.constraint.field: result.actual_value
            for result in item.constraint_results
            if result.actual_value is not None
        }
        for item in verification.candidates
        if item.eligible
    }
    schema = {
        "type": "function",
        "function": {
            "name": "rank_compliant_candidates",
            "description": "只对已由代码确认合规的完整候选集合排序，不得增删型号或修改资格。",
            "parameters": {
                "type": "object",
                "properties": {
                    "ordered_model_ids": {
                        "type": "array",
                        "items": {"type": "string", "enum": eligible},
                    },
                    "explanations": {
                        "type": "object",
                        "additionalProperties": {"type": "string", "maxLength": 240},
                    },
                },
                "required": ["ordered_model_ids", "explanations"],
                "additionalProperties": False,
            },
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你只能按软偏好排列给定的合规型号，必须返回全部型号且每个恰好一次。"
                "不得新增硬约束、修改复核状态、删除候选或添加集合外型号。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "eligible_model_ids": eligible,
                    "soft_preferences": [item.model_dump(mode="json") for item in active_soft],
                    "verified_values": candidates,
                },
                ensure_ascii=False,
                default=str,
            ),
        },
    ]
    try:
        response = await provider.chat(
            messages,
            tools=[schema],
            tool_choice={"type": "function", "function": {"name": "rank_compliant_candidates"}},
            temperature=0.0,
            max_tokens=500,
        )
        tool_calls = response.data.get("tool_calls") or []
        function = (tool_calls[0].get("function") or {}) if tool_calls else {}
        arguments = function.get("arguments", "{}")
        payload = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        order, explanations = enforce_eligible_ranking(
            eligible,
            list(payload.get("ordered_model_ids", [])),
            payload.get("explanations") if isinstance(payload.get("explanations"), dict) else {},
        )
        return order, explanations, False
    except Exception:
        order, explanations = enforce_eligible_ranking(eligible, eligible)
        return order, explanations, True
