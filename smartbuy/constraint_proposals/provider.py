"""Bounded qwen-plus Function Calling adapter for constraint proposal fallback."""

from __future__ import annotations

import json
from typing import Any, Protocol

from smartbuy.domain_packs.loader import LoadedDomainPack
from smartbuy.observability import UsageLedger
from smartbuy.providers import BailianProvider


class ConstraintProposalProvider(Protocol):
    async def propose(
        self, query: str, pack: LoadedDomainPack
    ) -> dict[str, Any]: ...


class QwenConstraintProposalProvider:
    """Ask qwen-plus for candidates only; deterministic validation remains authoritative."""

    def __init__(self, provider: BailianProvider) -> None:
        self.provider = provider

    async def propose(self, query: str, pack: LoadedDomainPack) -> dict[str, Any]:
        fields = sorted(
            field.field_id for field in pack.fields.values() if field.constraint_enabled
        )
        tool = {
            "type": "function",
            "function": {
                "name": "submit_constraint_proposals",
                "description": (
                    "只提取用户原文中明确存在的约束候选。每条必须引用精确字符 span；"
                    "不要补充、推测或改写用户没有说过的条件。"
                ),
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "proposals": {
                            "type": "array",
                            "maxItems": 12,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "field": {"type": "string", "enum": fields},
                                    "operator": {
                                        "type": "string",
                                        "enum": [
                                            "eq", "lte", "gte", "range", "in",
                                            "not_in", "contains_all",
                                        ],
                                    },
                                    "value": {},
                                    "unit": {"type": ["string", "null"]},
                                    "strength": {"type": "string", "enum": ["hard", "soft"]},
                                    "action": {
                                        "type": "string",
                                        "enum": ["add", "override", "cancel"],
                                    },
                                    "status": {
                                        "type": "string",
                                        "enum": ["supported", "ambiguous", "needs_confirmation"],
                                    },
                                    "span_start": {"type": "integer", "minimum": 0},
                                    "span_end": {"type": "integer", "minimum": 1},
                                    "span_text": {"type": "string", "minLength": 1},
                                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                },
                                "required": [
                                    "field", "operator", "value", "unit", "strength",
                                    "action", "status", "span_start", "span_end",
                                    "span_text", "confidence",
                                ],
                            },
                        }
                    },
                    "required": ["proposals"],
                },
            },
        }
        result = await self.provider.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是约束候选提取器。只调用指定函数；原文 span 必须逐字符匹配。"
                        "模糊条件标记 needs_confirmation，不得自行补数值。"
                    ),
                },
                {"role": "user", "content": query},
            ],
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "submit_constraint_proposals"}},
            temperature=0.0,
            max_tokens=600,
        )
        calls = result.data.get("tool_calls") or []
        function = (calls[0].get("function") or {}) if len(calls) == 1 else {}
        if (
            len(calls) != 1
            or function.get("name") != "submit_constraint_proposals"
        ):
            proposals: list[dict[str, Any]] = []
        else:
            raw = function.get("arguments", "{}")
            try:
                payload = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                payload = {}
            proposals = payload.get("proposals", []) if isinstance(payload, dict) else []
            if not isinstance(proposals, list):
                proposals = []
        usage = result.usage
        return {
            "proposals": proposals[:12],
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "latency_ms": result.latency_ms,
            "estimated_cost_cny": UsageLedger.estimate_cost(
                self.provider.settings.chat_model,
                int(usage.get("input_tokens", 0)),
                int(usage.get("output_tokens", 0)),
            ),
        }
