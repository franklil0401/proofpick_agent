"""Fail-closed Product Pack loader and deterministic entity alignment."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from smartbuy.data.derive import evidence_rows
from smartbuy.data.loader import CATALOG_PATH, load_catalog, stable_json_hash
from smartbuy.domain_packs import DomainPackLoader, DomainPackValidationError, LoadedDomainPack
from smartbuy.product_packs.models import (
    NORMALIZER_VERSION,
    PRODUCT_PACK_SCHEMA_VERSION,
    ProductPackDocument,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = Path(__file__).with_name("schema") / "product-pack-v1.schema.json"
DEFAULT_DOMAIN_PACK = PROJECT_ROOT / "smartbuy" / "domain_packs" / "monitor"
MAX_PACK_BYTES = 1_000_000
PRODUCT_ATTRIBUTE_FIELDS = {
    "display_size_inch",
    "resolution",
    "refresh_rate_hz",
    "panel_type",
    "is_oled",
    "has_usb_c",
    "usb_c_video",
    "usb_c_power_delivery_w",
    "stand_adjustment",
    "width_mm",
    "weight_kg",
    "warranty",
    "release_date",
}
IDENTITY_EVIDENCE_FIELDS = {"model_id", "brand", "model_name", "region"}
POSITIVE_FIELDS = {
    "display_size_inch",
    "refresh_rate_hz",
    "usb_c_power_delivery_w",
    "width_mm",
    "weight_kg",
}


class ProductPackValidationError(RuntimeError):
    """Sanitized validation failure; Pack content is never embedded in the message."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("duplicate JSON key")
        output[key] = value
    return output


def _iso(value: str, *, field: str) -> str:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ProductPackValidationError(f"invalid ISO timestamp: {field}") from exc
    return value


def source_content_hash(source: dict[str, Any]) -> str:
    capture = {
        "source_id": source["source_id"],
        "uri": str(source["uri"]),
        "accessed_at": source["accessed_at"],
        "governed_summary": source["governed_summary"],
    }
    canonical = json.dumps(capture, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LoadedProductPack:
    document: ProductPackDocument
    normalized_products: tuple[dict[str, Any], ...]
    normalized_evidence: tuple[dict[str, Any], ...]
    fingerprint: str
    domain_pack: LoadedDomainPack


class ProductPackLoader:
    def __init__(
        self,
        *,
        domain_pack_path: Path = DEFAULT_DOMAIN_PACK,
        base_catalog_path: Path = CATALOG_PATH,
    ) -> None:
        self.domain_pack_path = Path(domain_pack_path)
        self.base_catalog_path = Path(base_catalog_path)

    def load(self, path: Path | str) -> LoadedProductPack:
        pack_path = Path(path).resolve()
        if not pack_path.is_file() or pack_path.name != "pack.json":
            raise ProductPackValidationError("Product Pack must be a pack.json file")
        if pack_path.stat().st_size > MAX_PACK_BYTES:
            raise ProductPackValidationError("Product Pack exceeds the size limit")
        try:
            payload = json.loads(
                pack_path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_pairs,
            )
            document = ProductPackDocument.model_validate(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, ValidationError) as exc:
            raise ProductPackValidationError("Product Pack JSON or schema is invalid") from exc
        self._validate_schema_file()
        _iso(document.created_at, field="created_at")
        try:
            domain_pack = DomainPackLoader().load(self.domain_pack_path)
        except DomainPackValidationError as exc:
            raise ProductPackValidationError("referenced Domain Pack is unavailable") from exc
        try:
            if document.domain_id != domain_pack.domain_id:
                raise ProductPackValidationError("Product Pack domain differs from Domain Pack")
            normalized_products = self._normalize_products(document, domain_pack)
            normalized_evidence = self._validate_relations(
                document,
                normalized_products,
                domain_pack,
            )
        except DomainPackValidationError as exc:
            raise ProductPackValidationError(
                "Product Pack field, value, or unit is invalid"
            ) from exc
        self._validate_base(document, normalized_products)
        semantic = {
            "document": document.model_dump(mode="json"),
            "normalized_products": normalized_products,
            "normalized_evidence": normalized_evidence,
            "normalizer_version": NORMALIZER_VERSION,
        }
        return LoadedProductPack(
            document=document,
            normalized_products=tuple(normalized_products),
            normalized_evidence=tuple(normalized_evidence),
            fingerprint=stable_json_hash(semantic),
            domain_pack=domain_pack,
        )

    @staticmethod
    def _validate_schema_file() -> None:
        try:
            schema = json.loads(DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductPackValidationError("Product Pack JSON Schema is unavailable") from exc
        if schema.get("$id") != "https://proofpick.local/schema/product-pack-v1.json":
            raise ProductPackValidationError("Product Pack JSON Schema identity is invalid")
        if schema.get("properties", {}).get("schema_version", {}).get("const") != (
            PRODUCT_PACK_SCHEMA_VERSION
        ):
            raise ProductPackValidationError("Product Pack JSON Schema version is incompatible")

    def _normalize_products(
        self,
        document: ProductPackDocument,
        domain_pack: LoadedDomainPack,
    ) -> list[dict[str, Any]]:
        if document.compatibility.domain_pack_version != domain_pack.version:
            raise ProductPackValidationError("Product Pack and Domain Pack versions differ")
        if document.base_data_version not in domain_pack.pack.manifest.data_versions:
            raise ProductPackValidationError("Product Pack base version is not Domain Pack compatible")
        policy = domain_pack.pack.policies["product_pack"]
        attribute_fields = set(policy.get("attribute_fields", PRODUCT_ATTRIBUTE_FIELDS))
        positive_fields = set(policy.get("positive_fields", POSITIVE_FIELDS))
        date_fields = set(policy.get("date_fields", {"release_date"}))
        output: list[dict[str, Any]] = []
        product_ids: set[str] = set()
        identity_keys: set[tuple[str, str, str]] = set()
        aliases: dict[str, str] = {}
        for product in document.products:
            if product.product_id in product_ids:
                raise ProductPackValidationError("duplicate product_id")
            product_ids.add(product.product_id)
            identity = (product.product_id, product.market, product.variant_key)
            if identity in identity_keys:
                raise ProductPackValidationError("duplicate product identity")
            identity_keys.add(identity)
            brand = domain_pack.normalize_value("brand", product.brand)
            market = domain_pack.normalize_value("region", product.market)
            if market != product.market:
                raise ProductPackValidationError("product market is not canonical")
            tokens = [product.product_id, product.canonical_name, *product.aliases]
            for token in tokens:
                key = token.strip().casefold()
                if not key or (key in aliases and aliases[key] != product.product_id):
                    raise ProductPackValidationError("ambiguous product alias")
                aliases[key] = product.product_id
            if set(product.attributes) != attribute_fields:
                raise ProductPackValidationError("product attribute set is incomplete or unsupported")
            attributes: dict[str, Any] = {}
            for field_id, attribute in product.attributes.items():
                value = attribute.value
                if isinstance(value, str) and value.strip().casefold() in {"", "unknown", "未知"}:
                    raise ProductPackValidationError("unknown values must use JSON null")
                normalized = domain_pack.normalize_value(field_id, value, unit=attribute.unit)
                if field_id in positive_fields and normalized is not None and normalized <= 0:
                    raise ProductPackValidationError("numeric product values must be positive")
                if field_id in date_fields and normalized is not None:
                    _iso(normalized, field=field_id)
                attributes[field_id] = normalized
            output.append(
                {
                    "product_id": product.product_id,
                    "domain_id": document.domain_id,
                    "model_id": product.product_id,
                    "brand": brand,
                    "model_name": product.canonical_name,
                    "region": product.market,
                    **attributes,
                    "official_source_id": product.official_source_ids[0],
                    "source_updated_at": "",
                    "variant_key": product.variant_key,
                    "aliases": list(product.aliases),
                    "status": product.status,
                }
            )
        return output

    def _validate_relations(
        self,
        document: ProductPackDocument,
        products: list[dict[str, Any]],
        domain_pack: LoadedDomainPack,
    ) -> list[dict[str, Any]]:
        policy = domain_pack.pack.policies["product_pack"]
        attribute_fields = set(policy.get("attribute_fields", PRODUCT_ATTRIBUTE_FIELDS))
        identity_evidence_fields = set(
            policy.get("identity_evidence_fields", IDENTITY_EVIDENCE_FIELDS)
        )
        identity_value_map = policy.get(
            "identity_value_map",
            {
                "model_id": "model_id",
                "brand": "brand",
                "model_name": "model_name",
                "region": "region",
            },
        )
        source_field_permissions = policy.get("source_field_permissions")
        product_by_id = {item["model_id"]: item for item in products}
        source_by_id: dict[str, Any] = {}
        for source in document.sources:
            if source.source_id in source_by_id:
                raise ProductPackValidationError("duplicate source_id")
            product = product_by_id.get(source.product_id)
            if product is None:
                raise ProductPackValidationError("source references an unknown product")
            if source.market != product["region"] or source.variant_key != product["variant_key"]:
                raise ProductPackValidationError("source region or variant does not match product")
            if source.redistribution_status not in {
                "redistributable",
                "metadata_and_summary_only",
            }:
                raise ProductPackValidationError("source redistribution status is not publishable")
            if not str(source.uri).startswith("https://"):
                raise ProductPackValidationError("source URI must use public HTTPS")
            _iso(source.accessed_at, field="source.accessed_at")
            if source.published_at is not None:
                _iso(source.published_at, field="source.published_at")
            if source.tested_at is not None:
                _iso(source.tested_at, field="source.tested_at")
            if source.source_type in {"professional_measurement", "subjective_review"}:
                if source.is_official:
                    raise ProductPackValidationError(
                        "review or measurement source cannot claim official status"
                    )
            raw = source.model_dump(mode="json")
            if source.content_hash != source_content_hash(raw):
                raise ProductPackValidationError("source governed capture hash does not match")
            source_by_id[source.source_id] = source
        if (
            document.license.redistribution_status == "redistributable"
            and any(
                source.redistribution_status != "redistributable"
                for source in document.sources
            )
        ):
            raise ProductPackValidationError(
                "Pack redistribution status exceeds a source permission"
            )
        for product_input in document.products:
            if any(source_id not in source_by_id for source_id in product_input.official_source_ids):
                raise ProductPackValidationError("official source reference is missing")
            if any(not source_by_id[item].is_official for item in product_input.official_source_ids):
                raise ProductPackValidationError("official source reference is not official")
            product_by_id[product_input.product_id]["source_updated_at"] = max(
                source_by_id[item].accessed_at[:10] for item in product_input.official_source_ids
            )
        evidence_ids: set[str] = set()
        coverage: dict[str, set[str]] = {item["model_id"]: set() for item in products}
        evidence_by_field: dict[tuple[str, str], list[Any]] = {}
        normalized_rows: list[dict[str, Any]] = []
        for evidence in document.evidence:
            if evidence.evidence_id in evidence_ids:
                raise ProductPackValidationError("duplicate evidence_id")
            evidence_ids.add(evidence.evidence_id)
            product = product_by_id.get(evidence.product_id)
            source = source_by_id.get(evidence.source_id)
            if product is None or source is None:
                raise ProductPackValidationError("evidence foreign key is invalid")
            if (
                evidence.market != product["region"]
                or evidence.market != source.market
                or evidence.variant_key != product["variant_key"]
                or evidence.variant_key != source.variant_key
                or evidence.source_version != source.source_version
            ):
                raise ProductPackValidationError("evidence identity, region, or version differs")
            _iso(evidence.observed_at, field="evidence.observed_at")
            if evidence.effective_at is not None:
                _iso(evidence.effective_at, field="evidence.effective_at")
            expected = {
                field_id: product.get(source_key)
                for field_id, source_key in identity_value_map.items()
            }.get(evidence.field_id, product.get(evidence.field_id))
            if expected is None:
                raise ProductPackValidationError("null fields must not have governed evidence")
            if source_field_permissions is not None:
                allowed_fields = source_field_permissions.get(source.source_type, [])
                if evidence.field_id not in allowed_fields:
                    raise ProductPackValidationError(
                        "source type is not permitted for the evidence field"
                    )
            normalized = domain_pack.normalize_value(
                evidence.field_id,
                evidence.normalized_value,
                unit=evidence.unit,
            )
            if stable_json_hash(normalized) != stable_json_hash(expected):
                raise ProductPackValidationError("evidence value does not match normalized product field")
            coverage[evidence.product_id].add(evidence.field_id)
            evidence_by_field.setdefault(
                (evidence.product_id, evidence.field_id), []
            ).append(evidence)
            normalized_rows.append(
                {
                    **evidence.model_dump(mode="json"),
                    "normalized_value": normalized,
                    "normalizer_version": NORMALIZER_VERSION,
                }
            )
        for product in products:
            required = identity_evidence_fields | {
                field_id
                for field_id in attribute_fields
                if product[field_id] is not None
            }
            if coverage[product["model_id"]] != required:
                raise ProductPackValidationError("every non-null product field needs exactly governed evidence")
        for records in evidence_by_field.values():
            if len(records) > 1:
                groups = {item.conflict_group for item in records}
                if None in groups or len(groups) != 1:
                    raise ProductPackValidationError(
                        "duplicate field evidence requires one explicit conflict group"
                    )
        observation_ids: set[str] = set()
        for observation in document.observations:
            if observation.observation_id in observation_ids:
                raise ProductPackValidationError("duplicate observation_id")
            observation_ids.add(observation.observation_id)
            if observation.product_id not in product_by_id or observation.source_id not in source_by_id:
                raise ProductPackValidationError("observation foreign key is invalid")
            if observation.market != product_by_id[observation.product_id]["region"]:
                raise ProductPackValidationError("observation market differs from product")
            source = source_by_id[observation.source_id]
            if source.product_id != observation.product_id:
                raise ProductPackValidationError("observation source belongs to another product")
            if not str(observation.uri).startswith("https://"):
                raise ProductPackValidationError("observation URI must use public HTTPS")
            _iso(observation.observed_at, field="observation.observed_at")
        return normalized_rows

    def _validate_base(
        self,
        document: ProductPackDocument,
        normalized_products: list[dict[str, Any]],
    ) -> None:
        domain_pack = DomainPackLoader().load(self.domain_pack_path)
        policy = domain_pack.pack.policies["product_pack"]
        if policy.get("base_mode", "v1_catalog") == "standalone":
            if document.base_data_version != policy.get("base_data_version"):
                raise ProductPackValidationError("standalone base data version differs")
            if document.data_version == document.base_data_version:
                raise ProductPackValidationError("Product Pack must create a new data version")
            expected = policy.get("counts", {})
            if len(normalized_products) != expected.get("products"):
                raise ProductPackValidationError("standalone product count differs from policy")
            if len({item["brand"] for item in normalized_products}) != expected.get("brands"):
                raise ProductPackValidationError("standalone brand count differs from policy")
            if len(document.sources) != expected.get("sources"):
                raise ProductPackValidationError("standalone source count differs from policy")
            if len(document.evidence) != expected.get("evidence"):
                raise ProductPackValidationError("standalone evidence count differs from policy")
            return
        catalog_bytes = self.base_catalog_path.read_bytes()
        actual_hash = hashlib.sha256(catalog_bytes).hexdigest()
        if actual_hash != policy["catalog_sha256"]:
            raise ProductPackValidationError("frozen base catalog hash differs")
        catalog = load_catalog(self.base_catalog_path)
        if document.data_version == catalog.data_version:
            raise ProductPackValidationError("Product Pack must create a new data version")
        if document.base_data_version != catalog.data_version:
            raise ProductPackValidationError("base data version differs from frozen catalog")
        base_ids = {item["model_id"] for item in catalog.products}
        base_source_ids = {item["source_id"] for item in catalog.source_records}
        base_evidence_ids = {item["evidence_id"] for item in evidence_rows(catalog)}
        base_observation_ids = {
            item["observation_id"] for item in catalog.price_observations
        }
        if any(item.source_id in base_source_ids for item in document.sources):
            raise ProductPackValidationError("Product Pack source_id collides with frozen V1 data")
        if any(item.evidence_id in base_evidence_ids for item in document.evidence):
            raise ProductPackValidationError(
                "Product Pack evidence_id collides with frozen V1 data"
            )
        if any(
            item.observation_id in base_observation_ids
            for item in document.observations
        ):
            raise ProductPackValidationError(
                "Product Pack observation_id collides with frozen V1 data"
            )
        base_aliases = {
            token.casefold()
            for product in catalog.products
            for token in (product["model_id"], product["model_name"])
        }
        for product in normalized_products:
            if product["model_id"] in base_ids:
                raise ProductPackValidationError("Product Pack duplicates a frozen V1 model_id")
            tokens = [product["model_id"], product["model_name"], *product["aliases"]]
            if any(token.strip().casefold() in base_aliases for token in tokens):
                raise ProductPackValidationError("Product Pack alias collides with frozen V1 data")
