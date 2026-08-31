"""Strict, data-only Domain Pack loader.

Pack files are JSON data.  The loader never imports Python named by a pack and
rejects missing, extra, duplicate, incompatible, or path-escaping content.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from smartbuy.contracts import CONTRACT_VERSION, ConstraintOperator, DomainPack, DomainPackManifest
from smartbuy.contracts.models import FieldDataType, FieldDefinition


LOADER_VERSION = "1.0.0"
MANIFEST_SCHEMA_VERSION = "1.0.0"
DEFAULT_MONITOR_PACK = Path(__file__).resolve().parent / "monitor"
_ALLOWED_FILES = frozenset({"manifest.json", "fields.json", "policies.json"})
_MAX_FILE_BYTES = 256_000


class DomainPackValidationError(RuntimeError):
    """Public fail-closed error without embedding pack content."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("duplicate JSON key")
        output[key] = value
    return output


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise DomainPackValidationError(f"required pack file missing: {path.name}")
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise DomainPackValidationError(f"pack file exceeds size limit: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise DomainPackValidationError(f"invalid pack JSON: {path.name}") from exc


class LoadedDomainPack:
    """Validated immutable pack plus deterministic normalization helpers."""

    def __init__(self, pack: DomainPack):
        self.pack = pack
        self.fields = {item.field_id: item for item in pack.fields}
        self.aliases: dict[str, str] = {}
        for item in pack.fields:
            self.aliases[item.field_id.casefold()] = item.field_id
            for alias in item.aliases:
                self.aliases[alias.casefold()] = item.field_id

    @property
    def domain_id(self) -> str:
        return self.pack.manifest.domain_id

    @property
    def version(self) -> str:
        return self.pack.manifest.domain_pack_version

    @property
    def fingerprint(self) -> str:
        return self.pack.fingerprint

    def canonical_field(self, value: str) -> str:
        field_id = self.aliases.get(value.strip().casefold())
        if field_id is None:
            raise DomainPackValidationError("unsupported domain field")
        return field_id

    def validate_operator(self, field_id: str, operator: str | ConstraintOperator) -> ConstraintOperator:
        canonical = self.canonical_field(field_id)
        try:
            parsed = operator if isinstance(operator, ConstraintOperator) else ConstraintOperator(operator)
        except ValueError as exc:
            raise DomainPackValidationError("unsupported constraint operator") from exc
        if parsed not in self.fields[canonical].allowed_operators:
            raise DomainPackValidationError("operator is not allowed for field")
        return parsed

    def normalize_value(self, field_id: str, value: Any, *, unit: str | None = None) -> Any:
        definition = self.fields[self.canonical_field(field_id)]
        if value is None:
            if definition.nullable:
                return None
            raise DomainPackValidationError("null is not allowed for field")
        if unit:
            if unit == definition.unit:
                factor = 1.0
            else:
                factor = definition.accepted_units.get(unit.casefold())
                if factor is None:
                    raise DomainPackValidationError("unsupported field unit")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise DomainPackValidationError("unit conversion requires numeric value")
            value = value * factor
        if isinstance(value, str):
            token = value.strip()
            value = definition.value_aliases.get(token.casefold(), token)
        value = self._coerce(definition, value)
        if definition.enum_values and value not in definition.enum_values:
            raise DomainPackValidationError("value is outside field enumeration")
        return value

    @staticmethod
    def _coerce(definition: FieldDefinition, value: Any) -> Any:
        kind = definition.data_type
        if kind == FieldDataType.BOOLEAN:
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.casefold() in {"true", "false"}:
                return value.casefold() == "true"
            raise DomainPackValidationError("invalid boolean value")
        if kind == FieldDataType.NUMBER:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
            raise DomainPackValidationError("invalid numeric value")
        if kind == FieldDataType.INTEGER:
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            raise DomainPackValidationError("invalid integer value")
        if kind == FieldDataType.STRING_LIST:
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise DomainPackValidationError("invalid string-list value")
            return value
        if not isinstance(value, str):
            raise DomainPackValidationError("invalid string value")
        return value


class DomainPackLoader:
    def load(self, root: Path) -> LoadedDomainPack:
        root = root.resolve()
        if not root.is_dir():
            raise DomainPackValidationError("domain pack directory is missing")
        actual_files = {item.name for item in root.iterdir() if item.is_file()}
        if actual_files != _ALLOWED_FILES:
            raise DomainPackValidationError("domain pack file set is invalid")
        try:
            manifest = DomainPackManifest.model_validate(_read_json(root / "manifest.json"))
            raw_fields = _read_json(root / "fields.json")
            policies = _read_json(root / "policies.json")
            fields = [FieldDefinition.model_validate(item) for item in raw_fields]
        except (ValidationError, TypeError) as exc:
            raise DomainPackValidationError("domain pack schema validation failed") from exc
        self._validate_manifest(manifest)
        self._validate_files(root, manifest)
        self._validate_fields(fields)
        self._validate_policies(manifest, fields, policies)
        canonical = json.dumps(
            {
                "manifest": manifest.model_dump(mode="json"),
                "fields": [item.model_dump(mode="json") for item in fields],
                "policies": policies,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        pack = DomainPack(
            manifest=manifest,
            fields=fields,
            policies=policies,
            fingerprint=hashlib.sha256(canonical).hexdigest(),
        )
        return LoadedDomainPack(pack)

    @staticmethod
    def _validate_manifest(manifest: DomainPackManifest) -> None:
        if manifest.manifest_schema_version != MANIFEST_SCHEMA_VERSION:
            raise DomainPackValidationError("incompatible manifest schema version")
        if CONTRACT_VERSION not in manifest.contract_versions:
            raise DomainPackValidationError("incompatible domain contract version")
        if LOADER_VERSION not in manifest.compatible_loader_versions:
            raise DomainPackValidationError("incompatible domain pack loader version")
        if not manifest.data_versions:
            raise DomainPackValidationError("domain pack declares no data version")

    @staticmethod
    def _validate_files(root: Path, manifest: DomainPackManifest) -> None:
        expected = {"fields": "fields.json", "policies": "policies.json"}
        if manifest.files != expected:
            raise DomainPackValidationError("manifest file mapping is invalid")
        for relative in manifest.files.values():
            candidate = (root / relative).resolve()
            if candidate.parent != root or candidate.name not in _ALLOWED_FILES:
                raise DomainPackValidationError("pack file path escapes its root")

    @staticmethod
    def _validate_fields(fields: list[FieldDefinition]) -> None:
        if not fields:
            raise DomainPackValidationError("domain pack has no fields")
        field_ids = [item.field_id for item in fields]
        if len(field_ids) != len(set(field_ids)):
            raise DomainPackValidationError("duplicate field id")
        aliases: dict[str, str] = {}
        for item in fields:
            for alias in [item.field_id, *item.aliases]:
                key = alias.casefold()
                if key in aliases and aliases[key] != item.field_id:
                    raise DomainPackValidationError("ambiguous field alias")
                aliases[key] = item.field_id

    @staticmethod
    def _validate_policies(
        manifest: DomainPackManifest,
        fields: list[FieldDefinition],
        policies: Any,
    ) -> None:
        if not isinstance(policies, dict):
            raise DomainPackValidationError("policies must be an object")
        required = {"source_priority", "checker", "ranking", "memory", "report", "product_pack", "eval_fixtures"}
        if set(policies) != required:
            raise DomainPackValidationError("domain policy sections are invalid")
        field_ids = {item.field_id for item in fields}
        source_priority = policies["source_priority"]
        if not isinstance(source_priority, dict) or not source_priority or not all(
            isinstance(key, str) and isinstance(value, int)
            for key, value in source_priority.items()
        ):
            raise DomainPackValidationError("source priority policy is invalid")
        checker = policies["checker"]
        if checker.get("fail_closed") is not True or checker.get("implementation") != "smartbuy.constraints.verifier":
            raise DomainPackValidationError("checker policy does not preserve the V1 gate")
        supported = set(checker.get("supported_fields", []))
        declared = {item.field_id for item in fields if item.constraint_enabled}
        if supported != declared or not supported <= field_ids:
            raise DomainPackValidationError("checker fields disagree with field definitions")
        memory_keys = policies["memory"].get("allowed_keys", {})
        if set(memory_keys) != {
            "budget_min_cny", "budget_max_cny", "display_size_inch", "resolution",
            "min_refresh_rate_hz", "exclude_oled", "excluded_brands", "primary_use",
        }:
            raise DomainPackValidationError("memory policy does not preserve the V1 whitelist")
        if not set(memory_keys.values()) <= field_ids:
            raise DomainPackValidationError("memory policy references an unknown field")
        ranking = policies["ranking"]
        if (
            ranking.get("implementation") != "smartbuy.agent.ranking"
            or ranking.get("hard_constraints_may_change_eligibility") is not False
        ):
            raise DomainPackValidationError("ranking policy can alter deterministic eligibility")
        if policies["report"].get("schema_version") != "smartbuy-decision-v3":
            raise DomainPackValidationError("report schema is not V1 compatible")
        if set(policies["report"].get("states", [])) != {
            "matched", "not_matched", "unknown", "conflict"
        }:
            raise DomainPackValidationError("report field states are incomplete")
        product_pack = policies["product_pack"]
        data_version = product_pack.get("data_version")
        if (
            data_version not in product_pack.get("compatible_data_versions", [])
            or data_version not in manifest.data_versions
        ):
            raise DomainPackValidationError("product pack data version is incompatible")
        counts = product_pack.get("counts", {})
        if set(counts) != {"products", "brands", "sources", "evidence"} or not all(
            isinstance(value, int) and value >= 0 for value in counts.values()
        ):
            raise DomainPackValidationError("product pack counts are invalid")
        for fixture in policies["eval_fixtures"].values():
            if (
                not isinstance(fixture, dict)
                or not isinstance(fixture.get("path"), str)
                or not isinstance(fixture.get("case_count"), int)
                or fixture["case_count"] < 1
                or not isinstance(fixture.get("sha256"), str)
                or len(fixture["sha256"]) != 64
            ):
                raise DomainPackValidationError("evaluation fixture policy is invalid")
