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
    for match in re.finditer(r"(?:必须|硬性要求|\bmust\b)\s*([^，,；;。！？!?\n]+)", query, re.I):
        body = match.group(1)
        if re.match(r"(?:给出|列出|展示|解释|比较|对比|核验|保持|保留|返回)", body):
            continue
        mentioned = set()
        for field_id, definition in pack.fields.items():
            if any(
                re.search(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", body, re.I)
                for term in {field_id, definition.label, *definition.aliases} if term
            ):
                mentioned.add(field_id)
        if mentioned:
            # Numeric completeness is checked with exact quantities above.
            unresolved = {
                field for field in mentioned
                if pack.fields[field].data_type.value not in {"number", "integer"}
                and not any(item.field == field for item in constraints.active(hard_only=True, supported_only=True))
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
    obligations = []
    implicit_operators = dict(ConstraintNormalizer.IMPLICIT_NUMERIC_OPERATORS)
    for item in extract_numeric_requirements(
        query, pack, implicit_operators=implicit_operators,
        implicit_unit_fields={"refresh_rate_hz"},
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
