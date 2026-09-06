"""Audit input obligations against effective constraints before any recommendation.

This gate never activates LLM proposals or evaluates product eligibility. It
compares independently located user requirements with the resolver's contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from smartbuy.constraints import ConstraintNormalizer, ConstraintSet
from smartbuy.contracts.quantities import extract_numeric_requirements
from smartbuy.domain_packs import LoadedDomainPack

if TYPE_CHECKING:
    from smartbuy.constraint_proposals import ConstraintResolution


@dataclass(frozen=True)
class RequirementCoverage:
    obligations: list[dict[str, Any]]

    @property
    def complete(self) -> bool:
        return all(item["resolved"] for item in self.obligations)

    def public(self) -> dict[str, Any]:
        return {"version": "input-requirement-coverage-v1", "complete": self.complete,
                "obligations": self.obligations}


def _bound(item: Any, constraints: ConstraintSet) -> bool:
    values = constraints.active(hard_only=True, supported_only=True)
    expected = item.operator.value if hasattr(item.operator, "value") else item.operator
    for actual in values:
        if actual.field != item.field:
            continue
        if actual.operator.value == expected and actual.normalized_value == item.value:
            return True
        if expected in {"gte", "lte"} and actual.operator.value == "range":
            index = 0 if expected == "gte" else 1
            if actual.normalized_value[index] == item.value:
                return True
    if expected == "range":
        return all(any(
            actual.field == item.field and actual.operator.value == operator
            and actual.normalized_value == value
            for actual in values
        ) for operator, value in zip(("gte", "lte"), item.value))
    return False


def _validated_supersession(item: Any, query: str, constraints: ConstraintSet, resolution: ConstraintResolution | None) -> bool:
    """A cancelled/overridden obligation remains auditable, but is no longer active."""
    if resolution is None:
        return False
    def signature(operator, value):
        return json.dumps([operator, value], ensure_ascii=False, sort_keys=True)

    reachable = {signature(item.operator, item.value)}
    proposals = {proposal.proposal_id: proposal for proposal in resolution.proposals}
    for delta in resolution.diff:
        proposal = proposals.get(delta.proposal_id)
        if proposal is None or proposal.field != item.field or proposal.status.value != "supported":
            continue
        span = proposal.source_span
        if span is None or query[span.start:span.end] != span.text:
            continue
        if not any(
            before.get("field") == item.field
            and signature(before.get("operator"), before.get("normalized_value")) in reachable
            for before in delta.before
        ):
            continue
        if proposal.action.value == "cancel":
            if item.field in constraints.cancelled_fields and not any(actual.field == item.field for actual in constraints.active(hard_only=True)):
                return True
        elif proposal.action.value == "override" and _bound(SimpleNamespace(field=proposal.field, operator=proposal.operator, value=proposal.normalized_value), constraints):
            return True
        reachable.update(
            signature(after.get("operator"), after.get("normalized_value"))
            for after in delta.after if after.get("field") == item.field
        )
    return False


def _explicit_hard_field_obligations(query: str, constraints: ConstraintSet, pack: LoadedDomainPack) -> list[dict[str, Any]]:
    """Retain unrecognized fields in narrow, explicit imperative clauses.

    This is a conservative boundary for '必须/硬性要求/must', not a general
    natural-language interpreter. Whole-query source text is not field proof.
    """
    obligations = []
    # Keep the complete subject/predicate clause: cutting at '必须' loses
    # '分辨率' in '分辨率必须为…'. Chinese aliases are not ASCII words and
    # must also match directly after a number (e.g. '4K分辨率').
    for match in re.finditer(r"[^，,；;。！？!?\n]+", query):
        body = match.group(0)
        imperative = re.search(r"(?:必须|硬性要求|\bmust\b)\s*", body, re.I)
        if not imperative:
            continue
        if re.match(r"(?:给出|列出|展示|解释|比较|对比|核验|保持|保留|返回)", body[imperative.end():]):
            continue
        mentioned = set()
        for field_id, definition in pack.fields.items():
            if any(
                _mentions_term(body, term)
                for term in {field_id, definition.label, *definition.aliases} if term
            ):
                mentioned.add(field_id)
        if mentioned:
            # Numeric completeness is checked with exact quantities above.
            unresolved = {
                field for field in mentioned
                if pack.fields[field].data_type.value not in {"number", "integer"}
                and not any(
                    item.field == field and item.provenance.value == "current_input"
                    for item in constraints.active(hard_only=True, supported_only=True)
                )
                and field not in {"product_id", "model_id", "model_name", "family_id", "configuration_id", "region"}
            }
        else:
            unresolved = {"unknown"}
        for field in sorted(unresolved):
            obligations.append({
                "field": field, "operator": None, "value": None, "unit": None,
                "source_text": match.group(0), "span_start": match.start(), "span_end": match.end(),
                "resolved": False, "reason": "unresolved_explicit_requirement",
            })
    return obligations


def _mentions_term(text: str, term: str) -> bool:
    pattern = re.escape(term)
    if term.isascii():
        pattern = rf"(?<![A-Za-z0-9_]){pattern}(?![A-Za-z0-9_])"
    return bool(re.search(pattern, text, re.I))


def clarification_obligations(query: str, pack: LoadedDomainPack) -> list[dict[str, Any]]:
    """Unresolved process/qualitative requirements cannot mean 'no constraints'.

    No model or catalog values are consulted. Numeric evidence in another field
    cannot resolve a qualitative bound. An explicit ask-first instruction is
    retained even when an otherwise valid threshold has already been supplied.
    """
    from smartbuy.decision_core.query_semantics import analyze_trusted_query_intent

    signals = analyze_trusted_query_intent(query)
    if signals.ask_first:
        return [{"field": "confirmation", "operator": None, "value": None, "unit": None,
                 "source_text": query, "span_start": 0, "span_end": len(query),
                 "resolved": False, "reason": "explicit_confirmation_required"}]
    if signals.task_type in {"fact", "comparison"}:
        return []
    pattern = re.compile(
        r"(?:(?:不能|不得|不宜|不应|不要|别)\s*太\s*(?:大|小|宽|窄|重|轻|高|低|贵|慢)|"
        r"(?:宽|窄|大|小|重|轻|高|低|贵|便宜|快|慢|强|好|久)(?:一点|一些)|"
        r"(?:阈值|上限|下限|限制).*?(?:没确定|未定|待定|还没量))"
    )
    quantities = extract_numeric_requirements(
        query, pack, implicit_operators=ConstraintNormalizer.IMPLICIT_NUMERIC_OPERATORS,
        implicit_unit_fields={"display_size_inch", "refresh_rate_hz"},
    )
    resolved_fields = {item.field for item in quantities if item.resolved}
    output = [
        item for item in _explicit_hard_field_obligations(query, ConstraintSet(), pack)
        if item["field"] == "unknown"
    ]
    for clause in re.finditer(r"[^，,；;。！？!?\n]+", query):
        text = clause.group(0)
        if not pattern.search(text):
            continue
        if re.search(r"偏好|最好|希望|更喜欢", text) and not re.search(r"必须|不能|不得|硬性", text):
            continue
        fields = {
            field for field, definition in pack.fields.items()
            if any(_mentions_term(text, term) for term in {field, definition.label, *definition.aliases} if term)
        }
        # Unknown objects are not guessed from a model or from unrelated digits.
        unresolved = fields - resolved_fields if fields else {"unknown"}
        for field in sorted(unresolved):
            output.append({"field": field, "operator": None, "value": None, "unit": None,
                           "source_text": text, "span_start": clause.start(), "span_end": clause.end(),
                           "resolved": False, "reason": "qualitative_threshold_missing"})
    return output


def audit_requirement_coverage(
    query: str, constraints: ConstraintSet, pack: LoadedDomainPack, *, purchase: bool,
    resolution: ConstraintResolution | None = None,
) -> RequirementCoverage:
    """Every explicit numeric obligation must survive into the effective set.

    Fact/comparison fields are not purchase constraints. Unresolved original
    input is retained as a public obligation; it is never silently discarded or
    replaced by an unvalidated model value. The Checker remains unchanged.
    """
    if not purchase:
        return RequirementCoverage([])
    obligations = clarification_obligations(query, pack)
    implicit_operators = dict(ConstraintNormalizer.IMPLICIT_NUMERIC_OPERATORS)
    for item in extract_numeric_requirements(
        query, pack, implicit_operators=implicit_operators,
        implicit_unit_fields={"display_size_inch", "refresh_rate_hz"},
    ):
        record = asdict(item)
        record["resolved"] = item.resolved and _bound(item, constraints)
        if item.resolved and not record["resolved"] and _validated_supersession(item, query, constraints, resolution):
            record["resolved"] = True
            record["superseded"] = True
            record["reason"] = "validated_override_or_cancel"
        if item.resolved and not record["resolved"]:
            record["reason"] = "explicit_requirement_missing_from_constraint_set"
        obligations.append(record)
    obligations.extend(_explicit_hard_field_obligations(query, constraints, pack))
    return RequirementCoverage(obligations)
