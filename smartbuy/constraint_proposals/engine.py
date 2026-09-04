"""Deterministic-first natural constraint parsing and strict proposal validation."""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from copy import deepcopy
from typing import Any, Iterable

from smartbuy.constraints import (
    ConstraintNormalizer,
    ConstraintOperator,
    ConstraintProvenance,
    ConstraintSet,
    ConstraintStrength,
    NormalizedConstraint,
)
from smartbuy.domain_packs.loader import DomainPackValidationError, LoadedDomainPack

from .models import (
    ClarificationState,
    ConstraintDiff,
    ConstraintProposal,
    ConstraintResolution,
    ProposalAction,
    ProposalKind,
    ProposalSource,
    ProposalStatus,
    SourceSpan,
    SpanSource,
)
from .spans import QuoteSpanResolver, QuoteSpanStatus


ENGINE_VERSION = "proofpick-natural-constraints-v1"
_NUMBER = r"(?:\d+(?:\.\d+)?\s*[kK千]?|[零〇一二两三四五六七八九十百千万]+)"
_BRANDS = {
    "dell": "Dell",
    "戴尔": "Dell",
    "asus": "ASUS",
    "华硕": "ASUS",
    "lg": "LG",
    "benq": "BenQ",
    "明基": "BenQ",
}
_RESOLUTIONS = {
    "1440p": "2560x1440",
    "wqhd": "2560x1440",
    "qhd": "2560x1440",
    "2k": "2560x1440",
    "3840×2160": "3840x2160",
    "3840x2160": "3840x2160",
    "uhd": "3840x2160",
    "4k": "3840x2160",
    "5k": "5120x2880",
    "8k": "7680x4320",
}
_BOUNDS = {
    "price_cny": (0.0, 10_000_000.0),
    "display_size_inch": (10.0, 100.0),
    "refresh_rate_hz": (20.0, 1_000.0),
    "usb_c_power_delivery_w": (0.0, 500.0),
    "width_mm": (50.0, 10_000.0),
}


def _chinese_number(token: str) -> float:
    compact = token.strip().replace(" ", "")
    if re.fullmatch(r"\d+(?:\.\d+)?[kK]", compact):
        return float(compact[:-1]) * 1000.0
    if re.fullmatch(r"\d+(?:\.\d+)?千", compact):
        return float(compact[:-1]) * 1000.0
    if re.fullmatch(r"\d+(?:\.\d+)?", compact):
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


def _proposal_id(
    query: str,
    field: str,
    action: ProposalAction,
    span: SourceSpan | None,
    quote: str | None = None,
) -> str:
    start = span.start if span else -1
    end = span.end if span else -1
    text = span.text if span else (quote or "")
    raw = f"{query}\0{field}\0{action.value}\0{start}\0{end}\0{text}"
    return "cp-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class ConstraintProposalValidator:
    """Validate rule/LLM proposals against exact text and the active Domain Pack."""

    def __init__(self, pack: LoadedDomainPack) -> None:
        self.pack = pack
        self.quote_resolver = QuoteSpanResolver()

    def validate(
        self,
        query: str,
        raw: dict[str, Any],
        *,
        source: ProposalSource,
        source_turn: int,
    ) -> ConstraintProposal:
        field = str(raw.get("field", "unknown"))[:80] or "unknown"
        action_raw = str(raw.get("action", "add"))
        try:
            action = ProposalAction(action_raw)
        except ValueError:
            return self._invalid(
                query,
                field,
                ProposalAction.ADD,
                None,
                source,
                source_turn,
                "action_invalid",
                source_quote=self._quote(raw),
            )
        proposal_kind = self._proposal_kind(raw.get("proposal_kind"))
        span, source_quote, span_source, occurrence, span_error = self._resolve_span(
            query, raw, source
        )
        if span_error:
            return self._invalid(
                query,
                field,
                action,
                span,
                source,
                source_turn,
                span_error,
                source_quote=source_quote,
                span_source=span_source,
                occurrence=occurrence,
                proposal_kind=proposal_kind,
            )
        if source == ProposalSource.LLM and not self._proposal_kind_matches(
            proposal_kind, action
        ):
            return self._invalid(
                query,
                field,
                action,
                span,
                source,
                source_turn,
                "proposal_kind_action_mismatch",
                source_quote=source_quote,
                span_source=span_source,
                occurrence=occurrence,
                proposal_kind=proposal_kind,
            )
        proposal_id = _proposal_id(query, field, action, span, source_quote)
        if action == ProposalAction.CANCEL:
            try:
                canonical = self.pack.canonical_field(field)
            except DomainPackValidationError:
                canonical = field
                status = ProposalStatus.UNSUPPORTED
                reason = "field_not_declared_by_domain_pack"
            else:
                status = ProposalStatus.SUPPORTED
                reason = "validated_cancel"
            return ConstraintProposal(
                proposal_id=proposal_id,
                field=canonical,
                status=status,
                action=action,
                source=source,
                source_span=span,
                source_quote=source_quote,
                span_source=span_source,
                occurrence=occurrence,
                proposal_kind=proposal_kind,
                clarification_question=raw.get("clarification_question"),
                source_turn=source_turn,
                confidence=float(raw.get("confidence", 1.0)),
                reason=reason,
            )
        try:
            canonical = self.pack.canonical_field(field)
        except DomainPackValidationError:
            unsupported = proposal_kind == ProposalKind.UNSUPPORTED_REQUEST
            return ConstraintProposal(
                proposal_id=proposal_id,
                field=field,
                operator=self._operator_or_none(raw.get("operator")),
                normalized_value=raw.get("value", raw.get("normalized_value")),
                unit=raw.get("unit"),
                strength=self._strength(raw.get("strength")),
                action=action,
                status=(
                    ProposalStatus.UNSUPPORTED
                    if source == ProposalSource.RULE or unsupported
                    else ProposalStatus.INVALID
                ),
                source=source,
                source_span=span,
                source_quote=source_quote,
                span_source=span_source,
                occurrence=occurrence,
                proposal_kind=proposal_kind,
                clarification_question=raw.get("clarification_question"),
                source_turn=source_turn,
                confidence=float(raw.get("confidence", 0.0)),
                reason="field_not_declared_by_domain_pack",
            )
        if proposal_kind == ProposalKind.UNSUPPORTED_REQUEST:
            return ConstraintProposal(
                proposal_id=proposal_id,
                field=canonical,
                operator=self._operator_or_none(raw.get("operator")),
                normalized_value=raw.get("value", raw.get("normalized_value")),
                unit=raw.get("unit"),
                strength=self._strength(raw.get("strength")),
                action=action,
                status=ProposalStatus.UNSUPPORTED,
                source=source,
                source_span=span,
                source_quote=source_quote,
                span_source=span_source,
                occurrence=occurrence,
                proposal_kind=proposal_kind,
                clarification_question=raw.get("clarification_question"),
                source_turn=source_turn,
                confidence=0.0,
                reason="unsupported_kind_for_declared_field",
            )
        status_raw = str(raw.get("status", "supported"))
        try:
            status = ProposalStatus(status_raw)
        except ValueError:
            status = ProposalStatus.INVALID
        operator = self._operator_or_none(raw.get("operator"))
        if (
            operator is None
            and status
            in {ProposalStatus.AMBIGUOUS, ProposalStatus.NEEDS_CONFIRMATION}
        ):
            return ConstraintProposal(
                proposal_id=proposal_id,
                field=canonical,
                operator=None,
                normalized_value=None,
                unit=self.pack.fields[canonical].unit,
                strength=self._strength(raw.get("strength")),
                action=action,
                status=status,
                source=source,
                source_span=span,
                source_quote=source_quote,
                span_source=span_source,
                occurrence=occurrence,
                proposal_kind=proposal_kind,
                clarification_question=raw.get("clarification_question"),
                source_turn=source_turn,
                confidence=float(raw.get("confidence", 0.5)),
                reason=str(raw.get("reason") or "clarification_required")[:240],
            )
        if operator is None:
            return self._invalid(
                query,
                canonical,
                action,
                span,
                source,
                source_turn,
                "operator_invalid",
                source_quote=source_quote,
                span_source=span_source,
                occurrence=occurrence,
                proposal_kind=proposal_kind,
            )
        try:
            self.pack.validate_operator(canonical, operator.value)
        except DomainPackValidationError:
            return self._invalid(
                query,
                canonical,
                action,
                span,
                source,
                source_turn,
                "operator_not_allowed",
                source_quote=source_quote,
                span_source=span_source,
                occurrence=occurrence,
                proposal_kind=proposal_kind,
            )
        value = raw.get("value", raw.get("normalized_value"))
        unit = raw.get("unit")
        if source == ProposalSource.LLM and source_quote:
            value, unit = self._numeric_from_exact_quote(
                canonical, operator, source_quote, value, unit
            )
        if status in {ProposalStatus.AMBIGUOUS, ProposalStatus.NEEDS_CONFIRMATION}:
            normalized = self._normalize_if_present(canonical, operator, value, unit)
            return ConstraintProposal(
                proposal_id=proposal_id,
                field=canonical,
                operator=operator,
                normalized_value=normalized,
                unit=self.pack.fields[canonical].unit,
                strength=self._strength(raw.get("strength")),
                action=action,
                status=status,
                source=source,
                source_span=span,
                source_quote=source_quote,
                span_source=span_source,
                occurrence=occurrence,
                proposal_kind=proposal_kind,
                clarification_question=raw.get("clarification_question"),
                source_turn=source_turn,
                confidence=float(raw.get("confidence", 0.5)),
                reason=str(raw.get("reason") or "clarification_required")[:240],
            )
        try:
            normalized = self._normalize(canonical, operator, value, unit)
            self._validate_bounds(canonical, normalized)
        except (DomainPackValidationError, TypeError, ValueError):
            return self._invalid(
                query,
                canonical,
                action,
                span,
                source,
                source_turn,
                "value_or_unit_invalid",
                source_quote=source_quote,
                span_source=span_source,
                occurrence=occurrence,
                proposal_kind=proposal_kind,
            )
        return ConstraintProposal(
            proposal_id=proposal_id,
            field=canonical,
            operator=operator,
            normalized_value=normalized,
            unit=self.pack.fields[canonical].unit,
            strength=self._strength(raw.get("strength")),
            action=action,
            status=ProposalStatus.SUPPORTED,
            source=source,
            source_span=span,
            source_quote=source_quote,
            span_source=span_source,
            occurrence=occurrence,
            proposal_kind=proposal_kind,
            clarification_question=raw.get("clarification_question"),
            source_turn=source_turn,
            confidence=float(raw.get("confidence", 1.0)),
            active=True,
            reason="schema_and_domain_pack_validated",
        )

    def _resolve_span(
        self, query: str, raw: dict[str, Any], source: ProposalSource
    ) -> tuple[SourceSpan | None, str | None, SpanSource, int | None, str | None]:
        if source == ProposalSource.LLM:
            quote = self._quote(raw)
            result = self.quote_resolver.resolve(
                query, quote, occurrence=raw.get("occurrence")
            )
            if result.resolved:
                return (
                    result.span,
                    result.quote,
                    SpanSource.SERVER_EXACT_QUOTE,
                    result.occurrence,
                    None,
                )
            reason = {
                QuoteSpanStatus.QUOTE_NOT_FOUND: "quote_not_found",
                QuoteSpanStatus.OCCURRENCE_REQUIRED: "quote_occurrence_required",
                QuoteSpanStatus.OCCURRENCE_OUT_OF_RANGE: "quote_occurrence_out_of_range",
                QuoteSpanStatus.INVALID_QUOTE: "quote_invalid",
            }[result.status]
            return (
                None,
                result.quote or None,
                SpanSource.UNRESOLVED_QUOTE,
                result.occurrence,
                reason,
            )
        span = self._legacy_rule_span(query, raw)
        return (
            span,
            span.text if span else None,
            SpanSource.SERVER_RULE_MATCH,
            None,
            None if span else "source_span_invalid",
        )

    @staticmethod
    def _legacy_rule_span(query: str, raw: dict[str, Any]) -> SourceSpan | None:
        try:
            start = int(raw["span_start"])
            end = int(raw["span_end"])
            text = str(raw["span_text"])
        except (KeyError, TypeError, ValueError):
            return None
        if start < 0 or end <= start or end > len(query) or query[start:end] != text:
            return None
        return SourceSpan(start=start, end=end, text=text)

    @staticmethod
    def _quote(raw: dict[str, Any]) -> str | None:
        value = raw.get("quote")
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _proposal_kind(value: Any) -> ProposalKind | None:
        if value is None:
            return None
        try:
            return ProposalKind(str(value))
        except ValueError:
            return None

    @staticmethod
    def _proposal_kind_matches(
        kind: ProposalKind | None, action: ProposalAction
    ) -> bool:
        if kind is None:
            return False
        if action == ProposalAction.CANCEL:
            return kind == ProposalKind.CANCEL_CONSTRAINT
        if action == ProposalAction.CONFIRM:
            return kind == ProposalKind.CONFIRM_CONSTRAINT
        return kind in {
            ProposalKind.SUPPORTED_CONSTRAINT,
            ProposalKind.UNSUPPORTED_REQUEST,
            ProposalKind.NEEDS_CLARIFICATION,
        }

    @staticmethod
    def _operator_or_none(value: Any) -> ConstraintOperator | None:
        try:
            return ConstraintOperator(str(value))
        except ValueError:
            return None

    @staticmethod
    def _strength(value: Any) -> ConstraintStrength:
        try:
            return ConstraintStrength(str(value or "hard"))
        except ValueError:
            return ConstraintStrength.HARD

    def _normalize_if_present(
        self, field: str, operator: ConstraintOperator, value: Any, unit: str | None
    ) -> Any:
        if value is None:
            return None
        try:
            return self._normalize(field, operator, value, unit)
        except (DomainPackValidationError, TypeError, ValueError):
            return None

    def _normalize(
        self, field: str, operator: ConstraintOperator, value: Any, unit: str | None
    ) -> Any:
        if operator == ConstraintOperator.RANGE:
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError("range requires two values")
            values = [self.pack.normalize_value(field, item, unit=unit) for item in value]
            return sorted(values)
        if operator == ConstraintOperator.CONTAINS_ALL:
            if not isinstance(value, list) or not value:
                raise ValueError("list operator requires values")
            if self.pack.fields[field].data_type.value == "string_list":
                return self.pack.normalize_value(field, value, unit=unit)
            return [self.pack.normalize_value(field, item, unit=unit) for item in value]
        if operator in {ConstraintOperator.IN, ConstraintOperator.NOT_IN}:
            if not isinstance(value, list) or not value:
                raise ValueError("list operator requires values")
            return [self.pack.normalize_value(field, item, unit=unit) for item in value]
        return self.pack.normalize_value(field, value, unit=unit)

    def _numeric_from_exact_quote(
        self,
        field: str,
        operator: ConstraintOperator,
        quote: str,
        value: Any,
        unit: str | None,
    ) -> tuple[Any, str | None]:
        definition = self.pack.fields[field]
        if definition.data_type.value not in {"number", "integer"}:
            return value, unit
        if operator == ConstraintOperator.RANGE:
            return value, unit
        units = sorted(
            {definition.unit or "", *definition.accepted_units}, key=len, reverse=True
        )
        units = [item for item in units if item]
        if not units:
            return value, unit
        pattern = "|".join(re.escape(item) for item in units)
        match = re.search(
            rf"(?<![\d.])(\d+(?:\.\d+)?)\s*({pattern})(?![a-z])",
            quote,
            flags=re.I,
        )
        if match is None:
            return value, unit
        numeric = float(match.group(1))
        if definition.data_type.value == "integer" and numeric.is_integer():
            numeric = int(numeric)
        return numeric, match.group(2)

    @staticmethod
    def _validate_bounds(field: str, value: Any) -> None:
        if field not in _BOUNDS:
            return
        low, high = _BOUNDS[field]
        values = value if isinstance(value, list) else [value]
        if any(not isinstance(item, (int, float)) or not low <= float(item) <= high for item in values):
            raise ValueError("numeric value outside supported range")

    @staticmethod
    def _invalid(
        query: str,
        field: str,
        action: ProposalAction,
        span: SourceSpan | None,
        source: ProposalSource,
        source_turn: int,
        reason: str,
        *,
        source_quote: str | None = None,
        span_source: SpanSource = SpanSource.UNRESOLVED_QUOTE,
        occurrence: int | None = None,
        proposal_kind: ProposalKind | None = None,
    ) -> ConstraintProposal:
        return ConstraintProposal(
            proposal_id=_proposal_id(query, field, action, span, source_quote),
            field=field,
            status=ProposalStatus.INVALID,
            action=action,
            source=source,
            source_span=span,
            source_quote=source_quote,
            span_source=span_source,
            occurrence=occurrence,
            proposal_kind=proposal_kind,
            source_turn=source_turn,
            confidence=0.0,
            reason=reason,
        )


class DeterministicConstraintParser:
    def __init__(self, pack: LoadedDomainPack) -> None:
        self.pack = pack
        self.validator = ConstraintProposalValidator(pack)

    @staticmethod
    def _fold(value: str) -> str:
        return unicodedata.normalize("NFKC", value).casefold()

    def _pack_rules(
        self,
        query: str,
        *,
        previous: set[str],
    ) -> list[dict[str, Any]]:
        """Parse declared Pack fields without category-specific Python rules."""
        # V1 Monitor already has a frozen deterministic grammar below.  Generic
        # Pack-driven parsing is opt-in through the V2 ``understanding`` policy
        # so adding a new domain cannot change that historical contract.
        if "understanding" not in self.pack.pack.policies:
            return []
        raws: list[dict[str, Any]] = []
        normalized_query = unicodedata.normalize("NFKC", query)
        implicit_minimum_fields = set(
            self.pack.pack.policies.get("understanding", {}).get(
                "implicit_minimum_fields", []
            )
        )
        unitless_numeric_fields = set(
            self.pack.pack.policies.get("understanding", {}).get(
                "unitless_numeric_fields", []
            )
        )
        unit_context_terms = self.pack.pack.policies.get("understanding", {}).get(
            "unit_context_terms", {}
        )
        cancelled_fields: set[str] = set()
        clauses = [
            match
            for match in re.finditer(
                r"(?:(?!(?:[，,；;。、]|并且|同时|以及|但是|不过|但|却|且)).)+",
                normalized_query,
            )
            if match.group(0).strip()
        ]
        unit_owners: dict[str, set[str]] = {}
        for candidate_field, candidate in self.pack.fields.items():
            if candidate.data_type.value not in {"number", "integer"}:
                continue
            for candidate_unit in {candidate.unit or "", *candidate.accepted_units}:
                if candidate_unit:
                    unit_owners.setdefault(self._fold(candidate_unit), set()).add(
                        candidate_field
                    )

        def append(
            field: str,
            operator: str | None,
            value: Any,
            start: int,
            end: int,
            *,
            unit: str | None = None,
            status: str = "supported",
            strength: str = "hard",
            action: str | None = None,
            reason: str | None = None,
        ) -> None:
            chosen = action or ("override" if field in previous else "add")
            raws.append({
                "field": field,
                "operator": operator,
                "value": value,
                "unit": unit,
                "strength": strength,
                "status": status,
                "action": chosen,
                "span_start": start,
                "span_end": end,
                "span_text": query[start:end],
                "confidence": 1.0 if status == "supported" else 0.6,
                "reason": reason,
            })

        cancel_terms = self.pack.pack.policies.get("understanding", {}).get(
            "cancel_terms", {}
        )
        for field_id, terms in cancel_terms.items():
            if field_id not in self.pack.fields:
                continue
            for term in terms:
                match = re.search(re.escape(str(term)), normalized_query, flags=re.I)
                if match is not None:
                    cancelled_fields.add(field_id)
                    append(
                        field_id,
                        None,
                        None,
                        match.start(),
                        match.end(),
                        action="cancel",
                    )
                    break

        for field_id, definition in self.pack.fields.items():
            if not definition.constraint_enabled or field_id in cancelled_fields:
                continue
            aliases = sorted(
                {definition.label, *definition.aliases, field_id},
                key=len,
                reverse=True,
            )
            alias_pattern = "|".join(re.escape(item) for item in aliases if item)
            if not alias_pattern:
                continue
            field_mentions = list(re.finditer(alias_pattern, normalized_query, flags=re.I))
            if definition.data_type.value in {"number", "integer"}:
                units = sorted(
                    {definition.unit or "", *definition.accepted_units},
                    key=len,
                    reverse=True,
                )
                unit_pattern = "|".join(re.escape(item) for item in units if item)
                if not unit_pattern and field_id not in unitless_numeric_fields:
                    continue
                for clause in clauses:
                    local_mentions = [
                        item for item in field_mentions
                        if clause.start() <= item.start() < clause.end()
                    ]
                    local = clause.group(0)
                    number_pattern = (
                        rf"({_NUMBER})\s*({unit_pattern})(?![a-z])"
                        if field_id not in unitless_numeric_fields
                        else rf"({_NUMBER})(?!\s*[A-Za-z一-鿿])"
                    )
                    numbers = list(re.finditer(number_pattern, local, flags=re.I))
                    if not local_mentions:
                        if field_id in unitless_numeric_fields:
                            # Unitless values are safe only when the declared
                            # field name is present ("Bluetooth 5.4").  A bare
                            # catalog token such as "PS5" must never bind to it.
                            continue
                        # A unit owned by exactly one Pack field is itself an
                        # unambiguous field discriminator (for example kg/g).
                        # Shared units such as GB remain unresolved unless a
                        # field alias is present in the same clause.
                        for number in numbers:
                            context = local[
                                max(0, number.start() - 16):min(len(local), number.end() + 10)
                            ]
                            number_unit = number.group(2) if number.lastindex and number.lastindex >= 2 else None
                            owners = unit_owners.get(self._fold(number_unit or ""), set())
                            if field_id in unitless_numeric_fields and not number_unit:
                                owners = {field_id}
                            contextual_owners = {
                                owner for owner in owners
                                if any(
                                    self._fold(str(term)) in self._fold(context)
                                    for term in unit_context_terms.get(owner, [])
                                )
                            }
                            resolved_owners = contextual_owners or owners
                            if resolved_owners != {field_id}:
                                continue
                            operator = (
                                "lte"
                                if re.search(
                                    r"(?:不超过|至多|最多|以内|以下|上限|不重于|不高于)",
                                    context,
                                )
                                else "gte"
                                if re.search(
                                    r"(?:至少|最低|不低于|不少于|以上|下限|不小于)",
                                    context,
                                )
                                else "eq"
                            )
                            append(
                                field_id,
                                operator,
                                _chinese_number(number.group(1)),
                                clause.start() + number.start(),
                                clause.start() + number.end(),
                                unit=number_unit,
                            )
                        continue
                    if not numbers:
                        vague = re.search(
                            rf"(?:{alias_pattern}).{{0,8}}(?:大些|大一点|高一点|轻一点|便宜点|别太贵|好一点|强一点)",
                            local,
                            flags=re.I,
                        )
                        if vague:
                            append(
                                field_id,
                                "lte" if "轻" in vague.group(0) or "便宜" in vague.group(0) else "gte",
                                None,
                                clause.start() + vague.start(),
                                clause.start() + vague.end(),
                                unit=definition.unit,
                                status="ambiguous",
                                strength="soft",
                                reason="qualitative_threshold_missing",
                            )
                        continue
                    for position, number in enumerate(numbers):
                        # Shared units (for example GB) are bound to the nearest
                        # declared field mention inside the same clause.
                        nearest = min(
                            local_mentions,
                            key=lambda item: min(
                                abs(number.start() - item.end()),
                                abs(item.start() - number.end()),
                            ),
                        )
                        distance = min(
                            abs(number.start() - nearest.end()),
                            abs(nearest.start() - number.end()),
                        )
                        if distance > 28:
                            continue
                        number_start = clause.start() + number.start()
                        number_end = clause.start() + number.end()
                        start = min(nearest.start(), number_start)
                        end = max(nearest.end(), number_end)
                        local_nearest_start = nearest.start() - clause.start()
                        local_nearest_end = nearest.end() - clause.start()
                        context = local[
                            max(0, min(local_nearest_start, number.start()) - 10):
                            min(len(local), max(local_nearest_end, number.end()) + 10)
                        ]
                        # Operator words may sit just outside the nearest field/value
                        # window (for example ``重量不要超过250克``).  The complete
                        # clause is still deterministic and Pack-scoped, so inspect it
                        # as a fallback instead of silently turning the bound into eq.
                        operator_context = f"{context} {local}"
                        if re.search(r"(?:不超过|不要超过|至多|最多|以内|以下|上限)", operator_context):
                            operator = "lte"
                        elif re.search(r"(?:至少|最低|不低于|不少于|以上|下限)", operator_context):
                            operator = "gte"
                        elif (
                            field_id in implicit_minimum_fields
                            and number_end <= nearest.start()
                            and re.search(r"(?:想要|需要|要求)", operator_context)
                        ):
                            operator = "gte"
                        else:
                            operator = "eq"
                        action = None
                        prefix = local[:number.start()]
                        if position > 0 and re.search(r"(?:改成|改为|调整为|覆盖成|覆盖为|以后|后一个|最终)", prefix):
                            action = "override"
                        append(
                            field_id,
                            operator,
                            _chinese_number(number.group(1)),
                            start,
                            end,
                            unit=(number.group(2) if number.lastindex and number.lastindex >= 2 else None),
                            action=action,
                        )
            elif definition.data_type.value == "boolean":
                for mention in field_mentions:
                    if re.match(r"\s*(?:版本|version)", normalized_query[mention.end():], flags=re.I):
                        # A more specific numeric field such as bluetooth_version
                        # owns "蓝牙版本 5.4".  The base boolean must not shadow it.
                        continue
                    clause = next(
                        (
                            item
                            for item in clauses
                            if item.start() <= mention.start() < item.end()
                        ),
                        None,
                    )
                    clause_start = clause.start() if clause is not None else 0
                    # Negation can authorize a boolean value only when it
                    # precedes the matched field inside the same clause.  A
                    # later constraint such as ``重量不要超过`` must not negate
                    # an earlier field such as ``主动降噪``.
                    context = normalized_query[
                        max(clause_start, mention.start() - 10):mention.end()
                    ]
                    if re.search(r"(?:多少|是什么|是否|能否|有没有|存在|核验|确认)", context):
                        # Intent processing owns fact fields; do not infer a
                        # boolean purchase condition from a question form.
                        continue
                    double_negative = re.search(r"(?:不能没有|不要不带|不能不支持)", context)
                    # ``无线`` contains the character ``无`` but is not a
                    # negation.  A bare ``无`` is accepted only when it is not
                    # the lexical prefix of ``无线``.
                    negative = re.search(r"(?:不要|不需要|排除|无(?!线)|不带|不支持)", context)
                    append(
                        field_id,
                        "eq",
                        bool(double_negative or not negative),
                        mention.start(),
                        mention.end(),
                    )
                    break
            elif definition.data_type.value == "string":
                value_map = {
                    self._fold(key): value for key, value in definition.value_aliases.items()
                }
                value_map.update({self._fold(value): value for value in definition.enum_values})
                for token in sorted(value_map, key=len, reverse=True):
                    match = re.search(
                        rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])",
                        self._fold(normalized_query),
                    )
                    if match:
                        append(field_id, "eq", value_map[token], match.start(), match.end())
                        break
            elif definition.data_type.value == "string_list":
                value_map = {
                    self._fold(key): value
                    for key, value in definition.value_aliases.items()
                }
                matches: list[tuple[int, int, str]] = []
                for token in sorted(value_map, key=len, reverse=True):
                    match = re.search(
                        rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])",
                        self._fold(normalized_query),
                    )
                    if match is not None:
                        matches.append((match.start(), match.end(), value_map[token]))
                if matches:
                    matches.sort()
                    values = list(dict.fromkeys(item[2] for item in matches))
                    append(
                        field_id,
                        "contains_all",
                        values,
                        min(item[0] for item in matches),
                        max(item[1] for item in matches),
                    )
        # A conversational replacement may omit the field in its second
        # clause ("storage was 2 TB; change it to at least 1 TB").  Bind the
        # replacement only when the closest preceding numeric field mention
        # is unique.  All vocabulary and units still come from the Pack.
        numeric_mentions: list[tuple[int, str]] = []
        for field_id, definition in self.pack.fields.items():
            if not definition.constraint_enabled or definition.data_type.value not in {"number", "integer"}:
                continue
            for alias in {definition.label, *definition.aliases, field_id}:
                if not alias:
                    continue
                numeric_mentions.extend(
                    (match.end(), field_id)
                    for match in re.finditer(re.escape(alias), normalized_query, flags=re.I)
                )
        update_pattern = re.compile(
            rf"(?:改成|改为|调整为|覆盖成|覆盖为|以后(?:按|用)?|最终(?:按|用)?)\s*"
            rf"(?:(至少|最低|不低于|不超过|至多|最多)\s*)?({_NUMBER})\s*([A-Za-z\u4e00-\u9fff]+)",
            flags=re.I,
        )
        for update in update_pattern.finditer(normalized_query):
            prior = sorted(
                (item for item in numeric_mentions if item[0] <= update.start()),
                key=lambda item: item[0],
                reverse=True,
            )
            if not prior:
                continue
            nearest_end = prior[0][0]
            nearest_fields = {field for end, field in prior if end == nearest_end}
            if len(nearest_fields) != 1:
                continue
            field_id = next(iter(nearest_fields))
            definition = self.pack.fields[field_id]
            accepted = {definition.unit or "", *definition.accepted_units}
            unit = update.group(3)
            if self._fold(unit) not in {self._fold(item) for item in accepted if item}:
                continue
            qualifier = update.group(1) or ""
            operator = (
                "gte" if qualifier in {"至少", "最低", "不低于"}
                else "lte" if qualifier in {"不超过", "至多", "最多"}
                else "eq"
            )
            append(
                field_id,
                operator,
                _chinese_number(update.group(2)),
                update.start(),
                update.end(),
                unit=unit,
                action="override",
            )
        qualitative = self.pack.pack.policies.get("understanding", {}).get(
            "qualitative_terms", {}
        )
        existing_fields = {item["field"] for item in raws}
        for field_id, policy in qualitative.items():
            if field_id in existing_fields or field_id not in self.pack.fields:
                continue
            for term in policy.get("terms", []):
                match = re.search(re.escape(str(term)), normalized_query, flags=re.I)
                if match is None:
                    continue
                append(
                    field_id,
                    (
                        str(policy.get("operator", "eq"))
                        if self.pack.fields[field_id].constraint_enabled
                        else None
                    ),
                    None,
                    match.start(),
                    match.end(),
                    unit=self.pack.fields[field_id].unit,
                    status="ambiguous",
                    strength=str(policy.get("strength", "soft")),
                    reason="qualitative_threshold_missing",
                )
                break
        shadow_fields = self.pack.pack.policies.get("understanding", {}).get(
            "constraint_shadow_fields", {}
        )
        present = {item["field"] for item in raws if item.get("status") == "supported"}
        shadowed = {
            str(generic)
            for specific in present
            for generic in shadow_fields.get(specific, [])
        }
        if shadowed:
            raws = [item for item in raws if item["field"] not in shadowed]
        return raws

    def parse(
        self,
        query: str,
        *,
        source_turn: int,
        previous_fields: Iterable[str] = (),
    ) -> list[ConstraintProposal]:
        previous = set(previous_fields)
        raws: list[dict[str, Any]] = []

        def add(
            field: str,
            operator: str | None,
            value: Any,
            match: re.Match[str],
            *,
            unit: str | None = None,
            strength: str = "hard",
            status: str = "supported",
            action: str | None = None,
            reason: str | None = None,
        ) -> None:
            chosen_action = action or ("override" if field in previous else "add")
            raws.append(
                {
                    "field": field,
                    "operator": operator,
                    "value": value,
                    "unit": unit,
                    "strength": strength,
                    "status": status,
                    "action": chosen_action,
                    "span_start": match.start(),
                    "span_end": match.end(),
                    "span_text": match.group(0),
                    "confidence": 1.0 if status == "supported" else 0.6,
                    "reason": reason,
                }
            )

        compact = query.casefold()
        cancelled: set[str] = set()
        cancel_patterns = {
            "price_cny": (
                r"(?:(?:取消|移除|撤销)(?:预算|价格)(?:要求|限制)?|"
                r"(?:预算|价格)(?:要求|限制)?"
                r"(?:不限|不用管|不用限制|不作限制|不再限制|移除|取消|撤销))"
            ),
            "display_size_inch": r"(?:取消尺寸(?:限制)?|尺寸不限|不再限制尺寸)",
            "resolution": r"(?:分辨率不限|取消分辨率)",
            "refresh_rate_hz": r"(?:刷新率不限|取消刷新率)",
            "is_oled": r"(?:不再要求非\s*oled|不再要求\s*oled|不排斥\s*oled|oled\s*不限)",
            "has_usb_c": r"(?:(?:usb[\s_-]?c|type[\s_-]?c)不限|取消(?:usb[\s_-]?c|type[\s_-]?c)限制)",
            "usb_c_video": r"(?:不再需要(?:usb[\s_-]?c|type[\s_-]?c)视频|取消(?:usb[\s_-]?c|type[\s_-]?c)视频)",
            "usb_c_power_delivery_w": r"(?:供电不限|取消供电要求|不再要求供电)",
            "width_mm": r"(?:宽度不限|取消宽度限制)",
            "brand": r"(?:品牌不限|不限品牌|取消品牌限制)",
            "stand_adjustment": r"(?:支架不限|取消支架要求)",
            "region": r"(?:地区不限|版本不限)",
        }
        for field, pattern in cancel_patterns.items():
            if match := re.search(pattern, query, flags=re.I):
                cancelled.add(field)
                add(field, None, None, match, action="cancel")

        if match := re.search(r"([一二两三四五六七八九])([一二三四五六七八九])千", query):
            low = _chinese_number(match.group(1) + "千")
            high = _chinese_number(match.group(2) + "千")
            add(
                "price_cny", "range", sorted([low, high]), match, unit="CNY",
                status="needs_confirmation", reason="colloquial_price_range",
            )
        elif any(token in compact for token in ("预算", "价格", "元", "以内", "以下")):
            range_match = re.search(
                rf"({_NUMBER})\s*(?:元)?\s*(?:到|至|[-~～])\s*({_NUMBER})\s*元?",
                query,
                flags=re.I,
            )
            if range_match:
                add(
                    "price_cny", "range",
                    sorted([_chinese_number(range_match.group(1)), _chinese_number(range_match.group(2))]),
                    range_match, unit="CNY",
                )
            else:
                upper = re.search(
                    rf"(?:(?:预算|价格)(?:上限|改成|调整为)?\s*)?(?:不超过|最多|控制在)?\s*({_NUMBER})\s*元?\s*(?:以内|以下)",
                    query,
                    flags=re.I,
                ) or re.search(
                    rf"(?:预算|价格)?\s*(?:不超过|最多|控制在)\s*({_NUMBER})\s*元?",
                    query,
                    flags=re.I,
                ) or re.search(
                    rf"(?:预算|价格)(?:上限|改成|调整为)?\s*({_NUMBER})\s*元",
                    query,
                    flags=re.I,
                )
                if upper:
                    add("price_cny", "lte", _chinese_number(upper.group(1)), upper, unit="CNY")

        if "display_size_inch" not in cancelled:
            if vague := re.search(r"(?:屏幕|尺寸)?\s*不要太大", query, flags=re.I):
                add(
                    "display_size_inch", "lte", None, vague, unit="inch",
                    status="ambiguous", reason="size_limit_missing",
                )
            size_range = re.search(
                rf"({_NUMBER})\s*(?:到|至|[-~～])\s*({_NUMBER})\s*(?:英寸|寸|inch)",
                query,
                flags=re.I,
            )
            if size_range:
                add(
                    "display_size_inch", "range",
                    sorted([_chinese_number(size_range.group(1)), _chinese_number(size_range.group(2))]),
                    size_range, unit="inch",
                )
            else:
                size = re.search(
                    rf"(?:(至少|不低于)\s*)?({_NUMBER})\s*(?:英寸|寸|inch)\s*(左右|以下|以内)?",
                    query,
                    flags=re.I,
                )
                if size:
                    suffix = (size.group(3) or "").casefold()
                    operator = "gte" if size.group(1) else ("lte" if suffix in {"以下", "以内"} else "eq")
                    status = "needs_confirmation" if suffix == "左右" else "supported"
                    add(
                        "display_size_inch", operator, _chinese_number(size.group(2)), size,
                        unit="inch", strength="soft" if suffix == "左右" else "hard",
                        status=status, reason="approximate_size" if status != "supported" else None,
                    )

        if "resolution" not in cancelled:
            explicit_resolution = re.search(
                r"(?<!\d)(\d{3,5})\s*[x×]\s*(\d{3,5})(?!\d)", query, flags=re.I
            )
            if explicit_resolution:
                resolution_context = query[
                    max(0, explicit_resolution.start() - 24):explicit_resolution.end() + 10
                ]
                add(
                    "resolution",
                    (
                        "gte"
                        if re.search(r"(?:至少|不低于|不少于|以上|更高)", resolution_context)
                        else "eq"
                    ),
                    f"{explicit_resolution.group(1)}x{explicit_resolution.group(2)}",
                    explicit_resolution,
                )
            for alias in (() if explicit_resolution else sorted(_RESOLUTIONS, key=len, reverse=True)):
                pattern = re.escape(alias)
                if re.fullmatch(r"[a-z0-9.+-]+", alias, flags=re.I):
                    pattern = rf"(?<![a-z0-9.]){pattern}(?![a-z0-9.])"
                match = re.search(pattern, query, flags=re.I)
                if match:
                    prefix = query[max(0, match.start() - 8):match.start()].casefold()
                    suffix = query[match.end():match.end() + 6].casefold()
                    operator = "gte" if any(x in prefix + suffix for x in ("至少", "不低于", "更高")) else "eq"
                    add("resolution", operator, _RESOLUTIONS[alias], match)
                    break

        if "refresh_rate_hz" not in cancelled:
            if high_refresh := re.search(r"高刷就行", query):
                add(
                    "refresh_rate_hz", "gte", None, high_refresh, unit="Hz",
                    status="ambiguous", reason="refresh_threshold_missing",
                )
            refresh = re.search(
                rf"(?:(至少|不低于|不少于)\s*)?({_NUMBER})\s*(?:hz|赫兹)",
                query,
                flags=re.I,
            )
            if refresh:
                add(
                    "refresh_rate_hz", "gte" if refresh.group(1) else "eq",
                    _chinese_number(refresh.group(2)), refresh, unit="Hz",
                )

        if "is_oled" not in cancelled:
            if match := re.search(r"不能不要\s*oled", query, flags=re.I):
                add("is_oled", "eq", True, match)
            elif match := re.search(r"(?:不要|别给我|非|排除|不考虑)\s*oled", query, flags=re.I):
                add("is_oled", "eq", False, match)
            elif match := re.search(r"\boled\b", query, flags=re.I):
                add("is_oled", "eq", True, match)

        usb_pattern = r"(?:usb[\s_-]?c|type[\s_-]?c)"
        usb_match = re.search(usb_pattern, query, flags=re.I)
        if usb_match and "has_usb_c" not in cancelled:
            double_negative = re.search(rf"不要不带\s*{usb_pattern}\s*的", query, flags=re.I)
            negative = re.search(rf"(?:不需要|不要|无|排除)\s*{usb_pattern}", query, flags=re.I)
            if double_negative:
                add("has_usb_c", "eq", True, double_negative)
            elif negative:
                add("has_usb_c", "eq", False, negative)
            elif re.search(r"(?:一线通|传视频|视频)", query[usb_match.start():], flags=re.I):
                video = re.search(rf"{usb_pattern}[^，。；]*?(?:一线通|传视频|视频)", query, flags=re.I)
                assert video is not None
                add("usb_c_video", "eq", True, video)
                add("has_usb_c", "eq", True, video)
            elif not re.search(r"(?:供电|充电|\bpd\b|瓦|\bw\b)", query, flags=re.I):
                add("has_usb_c", "eq", True, usb_match)
        power = re.search(
            rf"(?:(?:{usb_pattern})[^，。；]*?)?(?:(?:至少|不少于|不低于|别低于)\s*)?({_NUMBER})\s*(?:w|瓦)(?:供电|pd)?",
            query,
            flags=re.I,
        )
        if power and any(token in compact for token in ("供电", "pd", "type-c", "type c", "usb-c", "usb c")):
            add(
                "usb_c_power_delivery_w", "gte", _chinese_number(power.group(1)), power,
                unit="W",
            )
            # A terse "USB-C PD 65W" also explicitly requires the interface.
            # Natural-language power requirements such as "USB-C 至少 90 瓦供电"
            # remain one field: the PD constraint already implies what must be
            # checked, while avoiding an extra proposal the user did not state.
            if (
                usb_match
                and re.search(r"(?:\bpd\b|别低于)", query, flags=re.I)
                and not any(item["field"] == "has_usb_c" for item in raws)
            ):
                add("has_usb_c", "eq", True, usb_match)
        elif usb_match and re.search(r"给笔记本充电|为笔记本充电", query):
            charging = re.search(rf"{usb_pattern}[^，。；]*?(?:给|为)笔记本充电", query, flags=re.I)
            assert charging is not None
            add(
                "usb_c_power_delivery_w", "gte", None, charging, unit="W",
                status="needs_confirmation", reason="power_threshold_missing",
            )

        if "width_mm" not in cancelled:
            width = re.search(
                rf"(?:机身宽度|机身宽|宽度)\s*(?:不超过|最多|小于等于)?\s*({_NUMBER})\s*(mm|毫米|cm|厘米)",
                query,
                flags=re.I,
            )
            if width:
                raw_value = _chinese_number(width.group(1))
                unit = width.group(2).casefold()
                factor = 10.0 if unit in {"cm", "厘米"} else 1.0
                add("width_mm", "lte", raw_value * factor, width, unit="mm")

        if "brand" not in cancelled:
            for alias, brand in _BRANDS.items():
                match = re.search(re.escape(alias), query, flags=re.I)
                if not match:
                    continue
                prefix = query[max(0, match.start() - 8):match.start()].casefold()
                if any(token in prefix for token in ("排除", "不要", "不考虑", "拒绝")):
                    add("brand", "not_in", [brand], match)
                elif any(token in prefix for token in ("只考虑", "只要", "仅限")):
                    add("brand", "in", [brand], match)
                elif any(token in prefix for token in ("优先", "偏好", "更喜欢")):
                    add("brand", "in", [brand], match, strength="soft")
                break

        if "stand_adjustment" not in cancelled:
            stand = re.search(r"(?:支架[^，。；]*)?(升降|高度调节)(?:和|、)?(旋转|竖屏)?", query)
            if stand:
                values = ["高度"]
                if stand.group(2):
                    values.append("旋转")
                soft = any(token in query[max(0, stand.start() - 6):stand.end()] for token in ("最好", "希望", "偏好"))
                add(
                    "stand_adjustment", "contains_all", values, stand,
                    strength="soft" if soft else "hard",
                )

        if "region" not in cancelled:
            regions = ((r"(?:国行|中国大陆|中国版|中国区)", "CN"), (r"(?:美国版|美国区)", "US"), (r"(?:加拿大版|加拿大区)", "CA"))
            for pattern, value in regions:
                if match := re.search(pattern, query):
                    add("region", "eq", value, match)
                    break

        unsupported = {
            r"摄像头": ("camera", True),
            r"蓝牙": ("bluetooth", True),
            r"hdr\s*1000": ("hdr_certification", "HDR1000"),
            r"色彩(?:一定要)?准|颜色准确": ("color_accuracy", True),
        }
        for pattern, (field, value) in unsupported.items():
            if match := re.search(pattern, query, flags=re.I):
                add(field, "eq", value, match, status="unsupported", reason="field_not_declared_by_domain_pack")

        raws.extend(self._pack_rules(query, previous=previous))
        shadow_fields = self.pack.pack.policies.get("understanding", {}).get(
            "constraint_shadow_fields", {}
        )
        present = {item["field"] for item in raws if item.get("status") == "supported"}
        shadowed = {
            str(generic)
            for specific in present
            for generic in shadow_fields.get(specific, [])
        }
        if shadowed:
            raws = [item for item in raws if item["field"] not in shadowed]
        scope_or_evidence_language = bool(
            re.search(
                r"(?:不要|别)(?:混进|扩展到|加入候选)|"
                r"(?:排除).{0,12}(?:候选|地区证据)|"
                r"(?:不能|不得).{0,16}(?:替代|作为|算进).{0,8}(?:证据|事实|参数)",
                query,
                flags=re.I,
            )
        )
        if (
            "understanding" in self.pack.pack.policies
            and not raws
            and not scope_or_evidence_language
            and re.search(r"(?:必须|要求|需要|至少|不超过)", query, flags=re.I)
        ):
            match = re.search(r"\S(?:.*\S)?", query)
            if match:
                add(
                    "unsupported",
                    None,
                    None,
                    match,
                    status="unsupported",
                    reason="field_not_declared_by_domain_pack",
                )

        proposals = [
            self.validator.validate(query, raw, source=ProposalSource.RULE, source_turn=source_turn)
            for raw in raws
        ]
        return self._deduplicate_and_mark_conflicts(proposals)

    @staticmethod
    def _deduplicate_and_mark_conflicts(
        proposals: list[ConstraintProposal],
    ) -> list[ConstraintProposal]:
        unique: list[ConstraintProposal] = []
        seen: set[str] = set()
        for item in proposals:
            signature = json.dumps(
                [item.field, item.operator, item.normalized_value, item.action, item.status, item.strength],
                default=str,
                sort_keys=True,
            )
            if signature not in seen:
                seen.add(signature)
                unique.append(item)
        by_field: dict[str, list[ConstraintProposal]] = {}
        for item in unique:
            if item.active and item.action != ProposalAction.CANCEL:
                by_field.setdefault(item.field, []).append(item)
        conflicted = {
            field
            for field, items in by_field.items()
            if len({json.dumps(item.normalized_value, sort_keys=True) for item in items}) > 1
            and not any(item.action == ProposalAction.OVERRIDE for item in items[1:])
        }
        if not conflicted:
            return unique
        output: list[ConstraintProposal] = []
        for item in unique:
            if item.field in conflicted:
                output.append(
                    item.model_copy(
                        update={
                            "status": ProposalStatus.NEEDS_CONFIRMATION,
                            "active": False,
                            "reason": "current_input_constraints_conflict",
                        }
                    )
                )
            else:
                output.append(item)
        return output


class NaturalConstraintEngine:
    def __init__(
        self,
        pack: LoadedDomainPack,
        provider: Any | None = None,
        *,
        max_provider_calls: int = 1,
        max_cost_cny: float = 0.05,
        always_use_provider: bool = False,
    ) -> None:
        self.pack = pack
        self.parser = DeterministicConstraintParser(pack)
        self.validator = ConstraintProposalValidator(pack)
        self.provider = provider
        self.max_provider_calls = max_provider_calls
        self.max_cost_cny = max_cost_cny
        self.always_use_provider = always_use_provider
        self.legacy = ConstraintNormalizer()

    async def resolve(
        self,
        query: str,
        *,
        source_turn: int,
        previous: ConstraintSet | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> ConstraintResolution:
        started = time.perf_counter()
        previous_fields = [item.field for item in previous.active()] if previous else []
        proposals = self.parser.parse(
            query, source_turn=source_turn, previous_fields=previous_fields
        )
        provider_calls = input_tokens = output_tokens = 0
        cost = provider_latency = 0.0
        if (
            (not proposals or self.always_use_provider)
            and self.provider is not None
            and self.max_provider_calls > 0
            and self._needs_fallback(query)
        ):
            result = await self.provider.propose(query, self.pack)
            provider_calls = 1
            input_tokens = int(result.get("input_tokens", 0))
            output_tokens = int(result.get("output_tokens", 0))
            cost = float(result.get("estimated_cost_cny", 0.0))
            if cost > self.max_cost_cny:
                raise RuntimeError("constraint proposal cost limit exceeded")
            provider_latency = float(result.get("latency_ms", 0.0))
            raw_proposals = [
                self._apply_current_input_precedence(raw, previous_fields)
                for raw in result.get("proposals", [])
                if isinstance(raw, dict)
            ]
            provider_proposals = [
                self.validator.validate(
                    query, raw, source=ProposalSource.LLM, source_turn=source_turn
                )
                for raw in raw_proposals
            ]
            proposals = self.parser._deduplicate_and_mark_conflicts(
                [*proposals, *provider_proposals]
            )
        base = self.legacy.build(
            "",
            source_turn=source_turn,
            previous=previous,
            preferences=preferences or {},
        )
        existing_preference_fields = {
            item.field
            for item in base.constraints
            if item.provenance == ConstraintProvenance.LONG_TERM_PREFERENCE
        }
        pack_preferences = [
            item
            for item in self._pack_preference_constraints(
                preferences or {}, source_turn=source_turn
            )
            if item.field not in existing_preference_fields
        ]
        if pack_preferences:
            base = base.model_copy(
                update={"constraints": [*base.constraints, *pack_preferences]}
            )
        constraint_set, activated, diffs = self._apply(base, proposals)
        pending = [
            item.proposal_id
            for item in activated
            if item.status in {ProposalStatus.AMBIGUOUS, ProposalStatus.NEEDS_CONFIRMATION}
        ]
        return ConstraintResolution(
            query=query,
            source_turn=source_turn,
            proposals=activated,
            constraint_set=constraint_set,
            clarification_state=(
                ClarificationState.PENDING if pending else ClarificationState.NOT_REQUIRED
            ),
            clarification_question=self._question(activated) if pending else None,
            pending_proposal_ids=pending,
            diff=diffs,
            provider_calls=provider_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=round(max((time.perf_counter() - started) * 1000, provider_latency), 3),
            estimated_cost_cny=cost,
        )

    def _pack_preference_constraints(
        self,
        preferences: dict[str, Any],
        *,
        source_turn: int,
    ) -> list[NormalizedConstraint]:
        """Map Domain Pack memory keys without embedding category fields in code."""

        allowed = self.pack.pack.policies.get("memory", {}).get("allowed_keys", {})
        output: list[NormalizedConstraint] = []
        for key, raw_value in preferences.items():
            field_id = allowed.get(key)
            if field_id not in self.pack.fields:
                continue
            definition = self.pack.fields[field_id]
            if key.startswith("excluded_"):
                operator = ConstraintOperator.NOT_IN
            elif key.startswith(("min_", "budget_min_")):
                operator = ConstraintOperator.GTE
            elif key.startswith(("max_", "budget_max_")):
                operator = ConstraintOperator.LTE
            elif key.startswith("need_"):
                operator = ConstraintOperator.EQ
            elif key == "primary_use" and "contains_all" in definition.allowed_operators:
                operator = ConstraintOperator.CONTAINS_ALL
            else:
                operator = ConstraintOperator.EQ
            if operator.value not in definition.allowed_operators:
                continue
            values = raw_value if operator in {ConstraintOperator.NOT_IN, ConstraintOperator.CONTAINS_ALL} else [raw_value]
            if not isinstance(values, list):
                values = [values]
            try:
                normalized_values = [
                    self.pack.normalize_value(field_id, value) for value in values
                ]
            except DomainPackValidationError:
                continue
            normalized: Any = (
                normalized_values
                if operator in {ConstraintOperator.NOT_IN, ConstraintOperator.CONTAINS_ALL}
                else normalized_values[0]
            )
            output.append(
                NormalizedConstraint(
                    field=field_id,
                    operator=operator,
                    normalized_value=normalized,
                    unit=definition.unit,
                    hard_or_soft=(
                        ConstraintStrength.SOFT
                        if key.startswith("preferred_") or key == "primary_use"
                        else ConstraintStrength.HARD
                    ),
                    provenance=ConstraintProvenance.LONG_TERM_PREFERENCE,
                    source_text=f"已启用的 {self.pack.domain_id} 长期偏好：{key}",
                    source_turn=source_turn,
                    confidence=1.0,
                    supported=True,
                )
            )
        return output

    def _apply_current_input_precedence(
        self,
        raw: dict[str, Any],
        previous_fields: list[str],
    ) -> dict[str, Any]:
        """Mark a current supported constraint as an explicit override.

        The model does not receive memory state.  Precedence therefore remains a
        deterministic server responsibility instead of being inferred by the LLM.
        """
        item = dict(raw)
        if item.get("action", "add") != ProposalAction.ADD.value:
            return item
        try:
            canonical = self.pack.canonical_field(str(item.get("field", "")))
        except DomainPackValidationError:
            return item
        if canonical in previous_fields:
            item["action"] = ProposalAction.OVERRIDE.value
        return item

    def confirm(self, resolution: ConstraintResolution, answer: Any) -> ConstraintResolution:
        accepted = self._affirmative(answer)
        proposals: list[ConstraintProposal] = []
        for item in resolution.proposals:
            if item.proposal_id not in resolution.pending_proposal_ids:
                proposals.append(item)
                continue
            if accepted:
                if item.normalized_value is None:
                    proposals.append(
                        item.model_copy(
                            update={
                                "status": ProposalStatus.INVALID,
                                "active": False,
                                "reason": "confirmation_missing_concrete_value",
                            }
                        )
                    )
                else:
                    proposals.append(
                        item.model_copy(
                            update={
                                "status": ProposalStatus.SUPPORTED,
                                "active": True,
                                "action": ProposalAction.CONFIRM,
                                "reason": "explicitly_confirmed",
                            }
                        )
                    )
            else:
                proposals.append(
                    item.model_copy(
                        update={
                            "status": ProposalStatus.INVALID,
                            "active": False,
                            "reason": "user_rejected_clarification",
                        }
                    )
                )
        constraint_set, proposals, diffs = self._apply(
            resolution.constraint_set, proposals, only_confirmed=True
        )
        return resolution.model_copy(
            update={
                "proposals": proposals,
                "constraint_set": constraint_set,
                "clarification_state": (
                    ClarificationState.CONFIRMED if accepted else ClarificationState.REJECTED
                ),
                "clarification_question": None,
                "pending_proposal_ids": [],
                "diff": [*resolution.diff, *diffs],
            }
        )

    @staticmethod
    def _needs_fallback(query: str) -> bool:
        lowered = query.casefold()
        return any(
            token in lowered
            for token in ("必须", "不要", "至少", "不超过", "偏好", "需要", "最好", "限制")
        )

    @staticmethod
    def _affirmative(answer: Any) -> bool:
        if isinstance(answer, bool):
            return answer
        if isinstance(answer, dict):
            return bool(answer.get("confirmed", False))
        return str(answer).strip().casefold() in {
            "是", "确认", "确定", "可以", "yes", "true", "作为硬约束", "继续"
        }

    @staticmethod
    def _question(proposals: list[ConstraintProposal]) -> str:
        pending = [
            item
            for item in proposals
            if item.status in {ProposalStatus.AMBIGUOUS, ProposalStatus.NEEDS_CONFIRMATION}
        ]
        descriptions = "；".join(
            item.clarification_question
            or (
                f"{item.source_span.text if item.source_span else item.source_quote or item.field}"
                f" → {item.field} {item.operator or ''} {item.normalized_value}"
            )
            for item in pending[:4]
        )
        return f"请确认这些条件是否应进入筛选：{descriptions}。缺少具体数值时请直接补充数值。"

    @staticmethod
    def _apply(
        base: ConstraintSet,
        proposals: list[ConstraintProposal],
        *,
        only_confirmed: bool = False,
    ) -> tuple[ConstraintSet, list[ConstraintProposal], list[ConstraintDiff]]:
        constraints = [deepcopy(item) for item in base.constraints]
        base_constraint_count = len(constraints)
        cancelled = set(base.cancelled_fields)
        output: list[ConstraintProposal] = []
        diffs: list[ConstraintDiff] = []
        for original in proposals:
            item = original
            if only_confirmed and item.action != ProposalAction.CONFIRM:
                output.append(item)
                continue
            before_items = [
                current.model_dump(mode="json")
                for current in constraints
                if current.active and current.field == item.field
            ]
            if item.status != ProposalStatus.SUPPORTED:
                output.append(item.model_copy(update={"active": False}))
                continue
            active_same_field = [
                current for current in constraints
                if current.field == item.field and current.active
            ]
            preserve_conjunction = (
                item.action == ProposalAction.ADD
                and bool(active_same_field)
                and all(
                    current in constraints[base_constraint_count:]
                    for current in active_same_field
                )
                and all(current.operator != item.operator for current in active_same_field)
            )
            if not preserve_conjunction:
                for current in active_same_field:
                    current.active = False
            if item.action == ProposalAction.CANCEL:
                cancelled.add(item.field)
                output.append(item.model_copy(update={"active": False}))
                diffs.append(
                    ConstraintDiff(
                        field=item.field,
                        action=item.action,
                        before=before_items,
                        after=[],
                        proposal_id=item.proposal_id,
                    )
                )
                continue
            assert item.operator is not None
            assert item.source_span is not None
            constraint = NormalizedConstraint(
                field=item.field,
                operator=item.operator,
                normalized_value=item.normalized_value,
                unit=item.unit,
                hard_or_soft=item.strength,
                provenance=ConstraintProvenance.CURRENT_INPUT,
                source_text=item.source_span.text,
                source_turn=item.source_turn,
                confidence=item.confidence,
                supported=True,
                active=True,
                ambiguous=False,
                note=None,
            )
            constraints.append(constraint)
            item = item.model_copy(update={"active": True})
            output.append(item)
            # Proposal action describes the user's language. Replacing a system
            # default is recorded in the diff but is not rewritten into an
            # explicit user override. Explicit session overrides are already
            # assigned by the parser from previous_fields.
            action = item.action
            diff_action = (
                ProposalAction.OVERRIDE
                if action == ProposalAction.ADD and before_items
                else action
            )
            diffs.append(
                ConstraintDiff(
                    field=item.field,
                    action=diff_action,
                    before=before_items,
                    after=[constraint.model_dump(mode="json")],
                    proposal_id=item.proposal_id,
                )
            )
        return (
            ConstraintSet(
                constraints=constraints,
                cancelled_fields=sorted(cancelled),
                rejected_model_constraints=list(base.rejected_model_constraints),
            ),
            output,
            diffs,
        )
