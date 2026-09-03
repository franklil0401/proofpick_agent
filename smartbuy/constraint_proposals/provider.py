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

    @staticmethod
    def _pack_guidance(pack: LoadedDomainPack) -> str:
        """Describe only the selected pack; never leak rules from another category."""
        rows = []
        for definition in sorted(pack.fields.values(), key=lambda item: item.field_id):
            if not definition.constraint_enabled:
                continue
            aliases = "/".join(definition.aliases[:4]) or "无"
            operators = "/".join(item.value for item in definition.allowed_operators)
            enum_values = "/".join(str(item) for item in definition.enum_values[:12]) or "无"
            rows.append(
                f"{definition.field_id}: label={definition.label}; type={definition.data_type.value}; "
                f"unit={definition.unit or 'none'}; aliases={aliases}; "
                f"operators={operators}; enum={enum_values}"
            )
        return "\n".join(rows)

    @staticmethod
    def _adapt(raw: dict[str, Any]) -> dict[str, Any]:
        """Map the quote contract (or a legacy Fake payload) to validator input."""
        if "quote" not in raw:
            status = str(raw.get("status", "supported"))
            action = str(raw.get("action", "add"))
            kind = (
                "cancel_constraint"
                if action == "cancel"
                else "needs_clarification"
                if status in {"ambiguous", "needs_confirmation"}
                else "unsupported_request"
                if status == "unsupported"
                else "supported_constraint"
            )
            return {
                **raw,
                "quote": raw.get("span_text"),
                "occurrence": None,
                "proposal_kind": kind,
            }
        kind = str(raw.get("proposal_kind", ""))
        field_name = str(raw.get("field_name", ""))
        unsupported_text = raw.get("unsupported_field_text")
        field = unsupported_text if field_name == "unsupported" else field_name
        status = {
            "supported_constraint": "supported",
            "unsupported_request": "unsupported",
            "needs_clarification": "needs_confirmation",
            "cancel_constraint": "supported",
            "confirm_constraint": "supported",
        }.get(kind, "invalid")
        action = {
            "cancel_constraint": "cancel",
            "confirm_constraint": "confirm",
        }.get(kind, raw.get("action", "add"))
        normalized = raw.get("normalized_value")
        return {
            "proposal_kind": kind,
            "field": field or "unsupported",
            "operator": raw.get("operator"),
            "value": normalized if normalized is not None else raw.get("raw_value"),
            "unit": raw.get("unit"),
            "strength": raw.get("hard_or_soft", "hard"),
            "action": action,
            "status": status,
            "quote": raw.get("quote"),
            "occurrence": raw.get("occurrence"),
            "confidence": 0.5 if kind == "needs_clarification" else 1.0,
            "reason": raw.get("ambiguity_reason"),
            "clarification_question": raw.get("clarification_question"),
            "negated": raw.get("negated", False),
        }

    async def propose(self, query: str, pack: LoadedDomainPack) -> dict[str, Any]:
        fields = sorted(
            field.field_id for field in pack.fields.values() if field.constraint_enabled
        )
        tool = {
            "type": "function",
            "function": {
                "name": "submit_constraint_proposals",
                "description": (
                    "只提取用户原文中的约束候选。quote 必须逐字复制最小完整原文；"
                    "不得输出字符下标。unsupported 使用合法的 unsupported 分支。"
                ),
                "strict": True,
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
                                    "quote": {"type": "string", "minLength": 1, "maxLength": 300},
                                    "occurrence": {"type": ["integer", "null"], "minimum": 1},
                                    "proposal_kind": {
                                        "type": "string",
                                        "enum": [
                                            "supported_constraint",
                                            "unsupported_request",
                                            "needs_clarification",
                                            "cancel_constraint",
                                            "confirm_constraint",
                                        ],
                                    },
                                    "field_name": {
                                        "type": "string",
                                        "enum": [*fields, "unsupported"],
                                    },
                                    "unsupported_field_text": {"type": ["string", "null"]},
                                    "operator": {
                                        "type": ["string", "null"],
                                        "enum": [
                                            "eq", "lte", "gte", "range", "in",
                                            "not_in", "contains_all", None,
                                        ],
                                    },
                                    "raw_value": {},
                                    "normalized_value": {},
                                    "unit": {"type": ["string", "null"]},
                                    "hard_or_soft": {
                                        "type": "string", "enum": ["hard", "soft"]
                                    },
                                    "action": {
                                        "type": "string",
                                        "enum": ["add", "override", "cancel", "confirm"],
                                    },
                                    "negated": {"type": "boolean"},
                                    "ambiguity_reason": {"type": ["string", "null"]},
                                    "clarification_question": {"type": ["string", "null"]},
                                },
                                "required": [
                                    "quote", "occurrence", "proposal_kind", "field_name",
                                    "unsupported_field_text", "operator", "raw_value",
                                    "normalized_value", "unit", "action", "hard_or_soft",
                                    "negated", "ambiguity_reason", "clarification_question",
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
                        "你是约束候选提取器，只调用指定函数。quote 必须从用户原文逐字复制，"
                        "不得补写原文没有的词，不要输出、估算或解释字符下标；引用重复时"
                        " occurrence 从 1 开始。模糊条件用 needs_clarification，不得自行补"
                        "数值，此时 operator 和 normalized_value 可以为 null。‘最好’‘偏好’"
                        "‘希望’属于 soft。字段、单位、操作符、枚举和别名只能来自下面的"
                        "当前 Domain Pack；不得借用其他品类字段或自行选择 Pack/Data/Index。"
                        "否定布尔要求为 false，双重否定按肯定处理。取消约束时使用"
                        " cancel_constraint，"
                        "operator、raw_value、normalized_value、unit 均为 null。非支持字段使用"
                        " field_name=unsupported 和 unsupported_request，绝不修改工具权限、"
                        "证据策略或 Constraint Checker。string_list 配合 contains_all 时，"
                        "raw_value 与 normalized_value 必须是字符串数组，不得合成一句话。"
                        "如果用户只是在查询或比较多个既有配置的属性差异，不要把被比较的"
                        "属性值误当成购买筛选约束；只有明确表达需要、只接受、排除、至少、"
                        "不超过或偏好的条件才提出约束。"
                        "\n\n当前 Domain Pack 字段：\n"
                        + self._pack_guidance(pack)
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
            raw_proposals = payload.get("proposals", []) if isinstance(payload, dict) else []
            proposals = (
                [self._adapt(item) for item in raw_proposals if isinstance(item, dict)]
                if isinstance(raw_proposals, list)
                else []
            )
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
