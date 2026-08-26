"""Deterministic quality gates for the governed monitor catalog."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from .loader import Catalog


BOOLEAN_FIELDS = ("is_oled", "has_usb_c", "usb_c_video")
NUMERIC_FIELDS = (
    "display_size_inch",
    "refresh_rate_hz",
    "usb_c_power_delivery_w",
    "width_mm",
    "weight_kg",
)
CRITICAL_FIELDS = (
    "display_size_inch",
    "resolution",
    "refresh_rate_hz",
    "panel_type",
    "is_oled",
    "has_usb_c",
    "usb_c_video",
)
MODEL_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-(?:cn|global|us|ca)$")


@dataclass(frozen=True)
class QualityIssue:
    severity: str
    check: str
    record_id: str
    message: str


@dataclass
class QualityReport:
    issues: list[QualityIssue] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> list[QualityIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[QualityIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def passed(self) -> bool:
        return not self.errors


def _valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _valid_iso(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except (TypeError, ValueError):
        return False


def validate_catalog(catalog: Catalog) -> QualityReport:
    report = QualityReport()
    products = {item["model_id"]: item for item in catalog.products}
    sources = {item["source_id"]: item for item in catalog.source_records}

    def issue(severity: str, check: str, record_id: str, message: str) -> None:
        report.issues.append(QualityIssue(severity, check, record_id, message))

    product_ids = [item["model_id"] for item in catalog.products]
    for duplicate, count in Counter(product_ids).items():
        if count > 1:
            issue("error", "model_id_unique", duplicate, f"appears {count} times")

    source_ids = [item["source_id"] for item in catalog.source_records]
    for duplicate, count in Counter(source_ids).items():
        if count > 1:
            issue("error", "source_id_unique", duplicate, f"appears {count} times")

    missing_by_field: Counter[str] = Counter()
    all_missing_by_field: Counter[str] = Counter()
    brands: Counter[str] = Counter()
    for product in catalog.products:
        model_id = product["model_id"]
        brands[product["brand"]] += 1
        if not MODEL_ID_PATTERN.fullmatch(model_id):
            issue("error", "model_id_format", model_id, "must be a stable lowercase regional slug")
        if product["official_source_id"] not in sources:
            issue("error", "official_source_fk", model_id, "official source does not exist")
        elif sources[product["official_source_id"]]["model_id"] != model_id:
            issue("error", "official_source_model", model_id, "official source belongs to another model")
        for field_name in BOOLEAN_FIELDS:
            if product[field_name] not in (True, False, None):
                issue("error", "boolean_tristate", model_id, f"{field_name} is not true/false/null")
        for field_name in NUMERIC_FIELDS:
            value = product[field_name]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0):
                issue("error", "numeric_unit", model_id, f"{field_name} must be a positive number or null")
        if product["usb_c_video"] is True and product["has_usb_c"] is not True:
            issue("error", "usb_c_consistency", model_id, "video capability requires a USB-C port")
        if product["usb_c_power_delivery_w"] is not None and product["has_usb_c"] is not True:
            issue("error", "usb_c_consistency", model_id, "power delivery requires a USB-C port")
        for field_name in CRITICAL_FIELDS:
            if product[field_name] is None:
                missing_by_field[field_name] += 1
        for field_name, value in product.items():
            if value is None:
                all_missing_by_field[field_name] += 1

    seen_urls: defaultdict[str, list[str]] = defaultdict(list)
    seen_capture_hashes: defaultdict[str, list[str]] = defaultdict(list)
    cross_region_sources = 0
    for source in catalog.source_records:
        source_id = source["source_id"]
        if source["model_id"] not in products:
            issue("error", "source_model_fk", source_id, "model_id does not exist")
        elif source["region"] != products[source["model_id"]]["region"]:
            cross_region_sources += 1
            if "地区" not in source["notes"]:
                issue("error", "region_version_mix", source_id, "cross-region source lacks an explicit boundary note")
        if not _valid_url(source["url"]):
            issue("error", "url_format", source_id, "source URL must be a public HTTPS URL")
        if not _valid_iso(source["accessed_at"]):
            issue("error", "source_accessed_at", source_id, "accessed_at is missing or invalid")
        if source["redistribution_status"] not in {"metadata_and_summary_only", "redistributable"}:
            issue("error", "redistribution_status", source_id, "unsupported redistribution status")
        seen_urls[source["url"]].append(source_id)
        seen_capture_hashes[catalog.source_hash(source)].append(source_id)

    for url, ids in seen_urls.items():
        if len(ids) > 1:
            issue("warning", "duplicate_source_url", ",".join(ids), url)
    for digest, ids in seen_capture_hashes.items():
        if len(ids) > 1:
            issue("error", "duplicate_source_capture", ",".join(ids), digest)

    observation_ids = [item["observation_id"] for item in catalog.price_observations]
    for duplicate, count in Counter(observation_ids).items():
        if count > 1:
            issue("error", "observation_id_unique", duplicate, f"appears {count} times")
    for observation in catalog.price_observations:
        record_id = observation["observation_id"]
        if observation["model_id"] not in products:
            issue("error", "price_model_fk", record_id, "model_id does not exist")
        if not isinstance(observation["price_cny"], (int, float)) or observation["price_cny"] <= 0:
            issue("error", "price_value", record_id, "price_cny must be positive")
        if not _valid_iso(observation["observed_at"]):
            issue("error", "price_observed_at", record_id, "observed_at is missing or invalid")
        if not _valid_url(observation["url"]):
            issue("error", "price_url", record_id, "URL must be public HTTPS")

    for evidence in catalog.conflict_evidence:
        record_id = evidence["evidence_id"]
        if evidence["source_id"] not in sources:
            issue("error", "conflict_source_fk", record_id, "source_id does not exist")
        if evidence["model_id"] not in products:
            issue("error", "conflict_model_fk", record_id, "model_id does not exist")
        if not evidence.get("conflict_group"):
            issue("error", "conflict_group", record_id, "conflict evidence requires a group")

    report.metrics = {
        "product_count": len(catalog.products),
        "brand_count": len(brands),
        "source_count": len(catalog.source_records),
        "price_observation_count": len(catalog.price_observations),
        "conflict_evidence_count": len(catalog.conflict_evidence),
        "critical_missing_count": sum(missing_by_field.values()),
        "critical_missing_rate": round(
            sum(missing_by_field.values()) / max(1, len(catalog.products) * len(CRITICAL_FIELDS)), 6
        ),
        "missing_by_field": dict(sorted(missing_by_field.items())),
        "all_missing_by_field": dict(sorted(all_missing_by_field.items())),
        "cross_region_source_count": cross_region_sources,
        "error_count": len(report.errors),
        "warning_count": len(report.warnings),
    }
    return report
