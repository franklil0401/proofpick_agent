"""Pack-driven canonical value representation with stable numeric semantics."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from smartbuy.contracts.models import FieldDataType, FieldDefinition


class CanonicalValueError(ValueError):
    """Raised when a value cannot be normalized by its field contract."""


def _text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().casefold().split())


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise CanonicalValueError("boolean is not a numeric value")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CanonicalValueError("invalid numeric value") from exc


@dataclass(frozen=True)
class CanonicalValue:
    """Comparable value whose numeric payload never depends on float equality."""

    field_id: str
    value: Any
    unit: str | None
    data_type: FieldDataType

    def stable_key(self) -> str:
        payload = self.value
        if isinstance(payload, Decimal):
            payload = format(payload.normalize(), "f")
        elif isinstance(payload, str):
            payload = _text(payload)
        elif isinstance(payload, tuple):
            payload = tuple(_text(item) if isinstance(item, str) else item for item in payload)
        return json.dumps(
            [self.field_id, self.data_type.value, self.unit, payload],
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    def to_native(self) -> Any:
        if isinstance(self.value, Decimal):
            if self.data_type == FieldDataType.INTEGER:
                return int(self.value)
            return float(self.value)
        if isinstance(self.value, tuple):
            return list(self.value)
        return self.value


class CanonicalValueNormalizer:
    """Normalize with only ``FieldDefinition`` data and unit factors."""

    @staticmethod
    def normalize(
        definition: FieldDefinition,
        value: Any,
        *,
        unit: str | None = None,
    ) -> CanonicalValue:
        if value is None:
            if definition.nullable:
                return CanonicalValue(
                    definition.field_id, None, definition.unit, definition.data_type
                )
            raise CanonicalValueError("null is not allowed for field")
        kind = definition.data_type
        if kind in {FieldDataType.NUMBER, FieldDataType.INTEGER}:
            number = _decimal(value)
            if unit:
                normalized_unit = _text(unit)
                canonical_unit = _text(definition.unit or "")
                if normalized_unit == canonical_unit:
                    factor = Decimal("1")
                else:
                    factors = {
                        _text(name): Decimal(str(multiplier))
                        for name, multiplier in definition.accepted_units.items()
                    }
                    if normalized_unit not in factors:
                        raise CanonicalValueError("unsupported field unit")
                    factor = factors[normalized_unit]
                number *= factor
            if kind == FieldDataType.INTEGER and number != number.to_integral_value():
                raise CanonicalValueError("integer field received fractional value")
            return CanonicalValue(definition.field_id, number, definition.unit, kind)
        if unit:
            raise CanonicalValueError("non-numeric field cannot carry a unit")
        if kind == FieldDataType.BOOLEAN:
            if isinstance(value, bool):
                parsed = value
            elif isinstance(value, str) and _text(value) in {
                "true", "false", "yes", "no", "是", "否", "有", "无",
            }:
                parsed = _text(value) in {"true", "yes", "是", "有"}
            else:
                raise CanonicalValueError("invalid boolean value")
            return CanonicalValue(definition.field_id, parsed, None, kind)
        if kind == FieldDataType.STRING_LIST:
            if not isinstance(value, (list, tuple)) or not all(
                isinstance(item, str) for item in value
            ):
                raise CanonicalValueError("invalid string-list value")
            aliases = {_text(key): target for key, target in definition.value_aliases.items()}
            normalized = tuple(
                aliases.get(_text(item), unicodedata.normalize("NFKC", item).strip())
                for item in value
            )
            return CanonicalValue(definition.field_id, normalized, None, kind)
        if not isinstance(value, str):
            raise CanonicalValueError("invalid string value")
        token = _text(value)
        aliases = {_text(key): target for key, target in definition.value_aliases.items()}
        parsed = aliases.get(token)
        if parsed is None and definition.enum_values:
            by_folded = {_text(item): item for item in definition.enum_values}
            parsed = by_folded.get(token)
        if parsed is None:
            parsed = unicodedata.normalize("NFKC", value).strip()
        if definition.enum_values and parsed not in definition.enum_values:
            raise CanonicalValueError("value is outside field enumeration")
        return CanonicalValue(definition.field_id, parsed, None, kind)

    @staticmethod
    def equivalent(
        definition: FieldDefinition,
        left: Any,
        right: Any,
        *,
        left_unit: str | None = None,
        right_unit: str | None = None,
    ) -> bool:
        return (
            CanonicalValueNormalizer.normalize(
                definition, left, unit=left_unit
            ).stable_key()
            == CanonicalValueNormalizer.normalize(
                definition, right, unit=right_unit
            ).stable_key()
        )
