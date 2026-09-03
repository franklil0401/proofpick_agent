"""Domain-neutral, deterministic constraint evaluation from pack declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from smartbuy.contracts import ConstraintOperator, FieldState
from smartbuy.domain_packs.loader import LoadedDomainPack
from smartbuy.decision_core.canonical import CanonicalValueNormalizer


@dataclass(frozen=True)
class ConstraintDecision:
    field_id: str
    state: FieldState
    actual_value: Any
    expected_value: Any
    reason: str


def _compare(
    actual: Any,
    operator: ConstraintOperator,
    expected: Any,
    *,
    value_order: dict[str, int] | None = None,
    definition: Any | None = None,
) -> bool:
    if value_order and actual in value_order:
        actual = value_order[actual]
        if operator == ConstraintOperator.RANGE:
            expected = tuple(value_order[item] for item in expected)
        elif operator in {ConstraintOperator.IN, ConstraintOperator.NOT_IN}:
            expected = [value_order[item] for item in expected]
        else:
            expected = value_order[expected]
        # Ordered string values have already been converted to their declared
        # ordinal representation.  Re-validating those integers as strings
        # would reject an otherwise valid comparison.
        definition = None
    if operator == ConstraintOperator.EQ:
        if definition is not None:
            return CanonicalValueNormalizer.equivalent(definition, actual, expected)
        return actual == expected
    if definition is not None and definition.data_type.value in {"number", "integer"}:
        actual = CanonicalValueNormalizer.normalize(definition, actual).value
        if operator == ConstraintOperator.RANGE:
            expected = tuple(
                CanonicalValueNormalizer.normalize(definition, item).value for item in expected
            )
        elif operator in {ConstraintOperator.IN, ConstraintOperator.NOT_IN}:
            expected = [
                CanonicalValueNormalizer.normalize(definition, item).value for item in expected
            ]
        else:
            expected = CanonicalValueNormalizer.normalize(definition, expected).value
    if operator == ConstraintOperator.LTE:
        return actual <= expected
    if operator == ConstraintOperator.GTE:
        return actual >= expected
    if operator == ConstraintOperator.RANGE:
        return expected[0] <= actual <= expected[1]
    if operator == ConstraintOperator.IN:
        return actual in expected
    if operator == ConstraintOperator.NOT_IN:
        return actual not in expected
    if operator == ConstraintOperator.CONTAINS_ALL:
        return set(expected) <= set(actual)
    raise ValueError("unsupported deterministic operator")


class DomainConstraintEvaluator:
    """Evaluates only declared fields and never grants eligibility on missing evidence."""

    def __init__(self, domain_pack: LoadedDomainPack) -> None:
        self.domain_pack = domain_pack

    def _normalize_expected(
        self,
        field_id: str,
        operator: ConstraintOperator,
        value: Any,
        unit: str | None,
    ) -> Any:
        if operator == ConstraintOperator.RANGE:
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise ValueError("range operator requires exactly two values")
            return tuple(
                self.domain_pack.normalize_value(field_id, item, unit=unit)
                for item in value
            )
        if operator in {ConstraintOperator.IN, ConstraintOperator.NOT_IN}:
            if not isinstance(value, (list, tuple, set)) or not value:
                raise ValueError("set operator requires one or more values")
            return [
                self.domain_pack.normalize_value(field_id, item, unit=unit)
                for item in value
            ]
        return self.domain_pack.normalize_value(field_id, value, unit=unit)

    def evaluate(
        self,
        attributes: dict[str, Any],
        constraints: Iterable[dict[str, Any]],
        *,
        evidenced_fields: set[str],
    ) -> tuple[list[ConstraintDecision], bool]:
        decisions: list[ConstraintDecision] = []
        for item in constraints:
            field_id = self.domain_pack.canonical_field(str(item["field"]))
            operator = self.domain_pack.validate_operator(field_id, str(item["operator"]))
            expected = self._normalize_expected(
                field_id, operator, item.get("value"), item.get("unit")
            )
            actual = attributes.get(field_id)
            if field_id not in evidenced_fields or actual is None:
                decisions.append(
                    ConstraintDecision(
                        field_id, FieldState.UNKNOWN, actual, expected, "missing_governed_evidence"
                    )
                )
                continue
            matched = _compare(
                actual,
                operator,
                expected,
                value_order=self.domain_pack.pack.policies["checker"]
                .get("value_order", {})
                .get(field_id),
                definition=self.domain_pack.fields[field_id],
            )
            decisions.append(
                ConstraintDecision(
                    field_id,
                    FieldState.MATCHED if matched else FieldState.NOT_MATCHED,
                    actual,
                    expected,
                    "deterministic_comparison",
                )
            )
        return decisions, bool(decisions) and all(
            item.state == FieldState.MATCHED for item in decisions
        )
