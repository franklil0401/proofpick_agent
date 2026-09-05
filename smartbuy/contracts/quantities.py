"""Exact-source numeric requirements normalized by the active field contract.

This layer describes quantities; the caller owns query intent and activation.
No model output, product names, or catalog values participate in parsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from smartbuy.domain_packs.loader import LoadedDomainPack


NUMERIC_PATTERN = r"(?:-?\d+(?:\.\d+)?\s*[kK千]?|[零〇一二两三四五六七八九十百千万]+)"
_NUMBER = NUMERIC_PATTERN
_COMPARISON = (
    r"不能超过|不得超过|不要超过|不超过|小于等于|不高于|不重于|最多|至多|上限|以内|以下|<=|≤|"
    r"大于等于|不低于|不少于|不小于|至少|最少|最低|下限|以上|>=|≥|等于|恰好|正好|="
)
_UPPER = re.compile(r"不能超过|不得超过|不要超过|不超过|小于等于|不高于|不重于|最多|至多|上限|以内|以下|<=|≤")
_LOWER = re.compile(r"大于等于|不低于|不少于|不小于|至少|最少|最低|下限|以上|>=|≥")
_SOFT = re.compile(r"偏好|最好|希望|左右|大约|约莫|around|prefer", re.I)
_PREFERENCE = re.compile(r"偏好|最好|希望|prefer", re.I)
_CANCEL = re.compile(r"取消|移除|撤销|不限|不限制|不再限制")
_QUALITATIVE = re.compile(r"窄一点|宽一点|大一点|小一点|强一点|高一点|轻一点|便宜一点")
_STRICT_COMPARISON = re.compile(r"小于|大于|少于|多于|低于|高于|(?<![<>=])[<>](?!=)")
_CLAUSE = re.compile(r"[^，,；;。！？!?、\n]+")


@dataclass(frozen=True)
class NumericRequirement:
    field: str
    operator: str
    value: Any
    unit: str | None
    source_text: str
    span_start: int
    span_end: int
    resolved: bool
    reason: str | None = None


def parse_numeric_token(token: str) -> float:
    """Parse the existing Chinese/Arabic numeric grammar without changing spans."""
    compact = token.strip().replace(" ", "")
    if re.fullmatch(r"-?\d+(?:\.\d+)?[kK千]", compact):
        return float(compact[:-1]) * 1000.0
    if re.fullmatch(r"-?\d+(?:\.\d+)?", compact):
        return float(compact)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    colloquial = re.fullmatch(r"([一二两三四五六七八九])千([一二三四五六七八九])", compact)
    if colloquial:
        return float(digits[colloquial.group(1)] * 1000 + digits[colloquial.group(2)] * 100)
    total = section = number = 0
    units = {"十": 10, "百": 100, "千": 1000, "万": 10_000}
    for char in compact:
        if char in digits:
            number = digits[char]
            continue
        unit = units.get(char)
        if unit is None:
            raise ValueError("unsupported numeric token")
        if unit == 10_000:
            section = (section + number) * unit
            total += section
            section = number = 0
        else:
            section += (number or 1) * unit
            number = 0
    return float(total + section + number)


def extract_numeric_requirements(
    query: str,
    pack: LoadedDomainPack,
    *,
    field_ids: Iterable[str] | None = None,
    implicit_operators: dict[str, str] | None = None,
    implicit_unit_fields: Iterable[str] = (),
) -> list[NumericRequirement]:
    """Return every numeric obligation, including unresolved explicit bounds.

Aliases, legal units, decimal conversion and bounds come from the Domain Pack.
Raw offsets are always measured on ``query`` itself.  Shared units need a field
mention; a unique unit can identify its field.  Unknown units are never inferred.
"""
    selected = set(field_ids) if field_ids is not None else set(pack.fields)
    implicit_fields = set(implicit_unit_fields)
    contextual_minimum_fields = set(pack.pack.policies.get("understanding", {}).get("implicit_minimum_fields", []))
    definitions = {
        name: field for name, field in pack.fields.items()
        if field.data_type.value in {"number", "integer"}
    }
    aliases = {
        name: sorted({field.label, field.field_id, *field.aliases}, key=len, reverse=True)
        for name, field in definitions.items()
    }
    unit_owners: dict[str, set[str]] = {}
    for name, field in definitions.items():
        for unit in {field.unit or "", *field.accepted_units} - {""}:
            unit_owners.setdefault(unit.casefold(), set()).add(name)
    output: list[NumericRequirement] = []
    for clause in _CLAUSE.finditer(query):
        text = clause.group(0)
        mentions = []
        for name, terms in aliases.items():
            pattern = "|".join(re.escape(term) for term in terms if term)
            mentions.extend((match.start(), match.end(), name) for match in re.finditer(pattern, text, re.I))
        mentions.sort(key=lambda item: (item[0], -(item[1] - item[0])))
        # Prefer the longest field alias at each position.
        kept = []
        for mention in mentions:
            if not any(start <= mention[0] < end for start, end, _ in kept):
                kept.append(mention)
        for field_id, definition in definitions.items():
            if field_id not in selected:
                continue
            units = sorted({definition.unit or "", *definition.accepted_units} - {""}, key=len, reverse=True)
            if not units:
                continue
            unit_pattern = "(?:" + "|".join(re.escape(unit) for unit in units) + ")"
            expression = re.compile(
                rf"(?P<low>{_NUMBER})\s*(?P<low_unit>{unit_pattern})?\s*(?:-|到|至|~|～)\s*"
                rf"(?P<high>{_NUMBER})\s*(?P<high_unit>{unit_pattern})(?![A-Za-z])|"
                rf"(?P<value>{_NUMBER})\s*(?P<unit>{unit_pattern})(?![A-Za-z])",
                re.I,
            )
            segments = [(start, end, name) for start, end, name in kept if name == field_id]
            if segments:
                first_start, first_end, _ = segments[0]
                prior_boundary = max((end for _, end, name in kept if end <= first_start and name != field_id), default=0)
                prior_values = list(expression.finditer(text[prior_boundary:first_start]))
                if prior_values and not text[prior_boundary + prior_values[-1].end():first_start].strip():
                    value_start = prior_boundary + prior_values[-1].start()
                    comparator = re.search(rf"(?:{_COMPARISON})\s*$", text[prior_boundary:value_start])
                    bound_start = prior_boundary + comparator.start() if comparator else value_start
                    segments[0] = (bound_start, first_end, field_id)
            # Include implicit, unit-disambiguated requirements (e.g. >=144Hz).
            if not segments:
                if field_id not in implicit_fields:
                    continue
                segments = [(0, 0, field_id)]
            for start, alias_end, _ in segments:
                explicit = alias_end > start
                segment_end = next((pos for pos, _, _ in kept if pos >= alias_end and pos > start), len(text)) if explicit else len(text)
                segment = text[start:segment_end]
                field_prefix = segment[:max(0, alias_end - start) + 4]
                preceding = text[max(0, start - 8):start]
                if _CANCEL.search(field_prefix) or (
                    _PREFERENCE.search(preceding + segment)
                    and not re.search(r"必须|硬性|要求", preceding + segment)
                ):
                    continue
                approximate = bool(_SOFT.search(segment))
                if approximate and not re.search(_COMPARISON, segment):
                    continue
                matches = list(expression.finditer(segment))
                handled = False
                previous_end = alias_end - start
                for match in matches:
                    actual_unit = match.group("unit") or match.group("high_unit")
                    if not explicit and unit_owners.get(actual_unit.casefold()) != {field_id}:
                        continue
                    if not explicit and any(pos <= match.start() < end for pos, end, _ in kept):
                        continue
                    context_start = max(0, previous_end)
                    # A later bound's comparator must not change the earlier bound.
                    prefix = segment[context_start:match.start()]
                    suffix_match = re.match(r"\s*(?:以内|以下|以上)", segment[match.end():])
                    suffix = suffix_match.group(0) if suffix_match else ""
                    context = prefix + suffix
                    strict_comparison = bool(_STRICT_COMPARISON.search(_UPPER.sub("", _LOWER.sub("", context))))
                    operator = (
                        "range" if match.group("low") is not None
                        else "lte" if _UPPER.search(context)
                        else "gte" if _LOWER.search(context)
                        else (implicit_operators or {}).get(field_id, "eq")
                    )
                    original_alias_start = next((pos for pos, end, name in kept if name == field_id and end == alias_end), -1)
                    if (
                        match.group("low") is None
                        and not _UPPER.search(context) and not _LOWER.search(context)
                        and field_id in contextual_minimum_fields
                        and start + match.end() <= original_alias_start
                        and re.search(r"想要|需要|要求", text[max(0, start - 8):segment_end])
                    ):
                        operator = "gte"
                    quote_start = start + (0 if not handled and explicit else max(context_start, 0))
                    consumed_end = match.end() + len(suffix)
                    quote_end = start + consumed_end
                    reason = None
                    try:
                        if strict_comparison:
                            raise ValueError("strict operator is outside the supported contract")
                        if approximate:
                            raise ValueError("approximate hard threshold needs confirmation")
                        if match.group("low") is not None:
                            value = [
                                pack.normalize_value(field_id, parse_numeric_token(match.group("low")), unit=match.group("low_unit") or actual_unit),
                                pack.normalize_value(field_id, parse_numeric_token(match.group("high")), unit=actual_unit),
                            ]
                            if value[0] > value[1]:
                                raise ValueError("inverted range")
                        else:
                            value = pack.normalize_value(field_id, parse_numeric_token(match.group("value")), unit=actual_unit)
                        # Fields disabled in the V2 Pack can remain part of a legacy
                        # parser contract; the caller still decides activation.
                        if definition.constraint_enabled:
                            pack.validate_operator(field_id, operator)
                    except (ValueError, RuntimeError):
                        value = None
                        reason = "comparison_operator_unresolved" if strict_comparison else "value_unit_or_operator_invalid"
                    absolute_start, absolute_end = clause.start() + quote_start, clause.start() + quote_end
                    output.append(NumericRequirement(
                        field_id, operator, value, definition.unit,
                        query[absolute_start:absolute_end], absolute_start, absolute_end,
                        reason is None, reason,
                    ))
                    handled = True
                    previous_end = consumed_end
                # Any unmatched comparison in an explicit field segment remains
                # an obligation, including a second bound with an omitted alias.
                remainder_start = previous_end if handled else 0
                remainder = segment[remainder_start:]
                if explicit and (re.search(_COMPARISON, remainder) or _QUALITATIVE.search(remainder) or _STRICT_COMPARISON.search(remainder)):
                    absolute_start = clause.start() + start + remainder_start
                    absolute_end = clause.start() + segment_end
                    output.append(NumericRequirement(
                        field_id, "lte" if _UPPER.search(remainder) else "gte" if _LOWER.search(remainder) else "eq",
                        None, definition.unit, query[absolute_start:absolute_end],
                        absolute_start, absolute_end, False, "quantity_or_unit_unresolved",
                    ))
    return output
