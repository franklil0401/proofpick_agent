"""V2-1D domain-neutral contracts and Monitor Domain Pack validation."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from smartbuy.contracts import (
    Candidate,
    Constraint,
    ConstraintOperator,
    ConstraintProvenance,
    ConstraintStrength,
    FieldState,
)
from smartbuy.domain_packs import (
    DEFAULT_MONITOR_PACK,
    DomainPackLoader,
    DomainPackSettings,
    DomainPackValidationError,
)
from smartbuy.domain_packs.v1_adapter import V1CompatibilityAdapter


ROOT = Path(__file__).resolve().parents[3]


def test_monitor_pack_manifest_schema_and_policy_boundaries_are_valid():
    loaded = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
    assert loaded.domain_id == "monitor"
    assert loaded.version == "1.0.0"
    assert len(loaded.fields) == 23
    assert {key for key, value in loaded.fields.items() if value.constraint_enabled} == {
        "price_cny", "display_size_inch", "resolution", "refresh_rate_hz", "is_oled",
        "has_usb_c", "usb_c_video", "usb_c_power_delivery_w", "width_mm", "brand",
        "stand_adjustment", "region",
    }
    assert loaded.pack.policies["checker"]["fail_closed"] is True
    assert loaded.pack.policies["report"]["schema_version"] == "smartbuy-decision-v3"


@pytest.mark.parametrize(
    ("field", "value", "unit", "expected"),
    [
        ("分辨率", "4K", None, "3840x2160"),
        ("品牌", "戴尔", None, "Dell"),
        ("机身宽", 61.2, "cm", 612.0),
        ("供电功率", 90, "W", 90.0),
        ("是否oled", "false", None, False),
    ],
)
def test_field_alias_unit_and_value_normalization(field, value, unit, expected):
    loaded = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
    assert loaded.normalize_value(field, value, unit=unit) == expected


def test_unsupported_field_and_operator_are_rejected():
    loaded = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
    with pytest.raises(DomainPackValidationError, match="unsupported domain field"):
        loaded.canonical_field("battery_capacity_mah")
    with pytest.raises(DomainPackValidationError, match="not allowed"):
        loaded.validate_operator("is_oled", "gte")


def _copy_pack(tmp_path: Path) -> Path:
    target = tmp_path / "monitor"
    shutil.copytree(DEFAULT_MONITOR_PACK, target)
    return target


def test_missing_corrupt_and_extra_pack_files_fail_closed(tmp_path):
    missing = _copy_pack(tmp_path / "missing")
    (missing / "fields.json").unlink()
    with pytest.raises(DomainPackValidationError, match="file set"):
        DomainPackLoader().load(missing)

    corrupt = _copy_pack(tmp_path / "corrupt")
    (corrupt / "policies.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(DomainPackValidationError, match="invalid pack JSON"):
        DomainPackLoader().load(corrupt)

    extra = _copy_pack(tmp_path / "extra")
    (extra / "plugin.py").write_text("raise RuntimeError('must never load')", encoding="utf-8")
    with pytest.raises(DomainPackValidationError, match="file set"):
        DomainPackLoader().load(extra)


def test_incompatible_pack_version_fails_closed(tmp_path):
    target = _copy_pack(tmp_path)
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["compatible_loader_versions"] = ["99.0.0"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DomainPackValidationError, match="incompatible domain pack loader"):
        DomainPackLoader().load(target)


def test_unknown_and_conflict_can_never_become_eligible():
    for state, field in [(FieldState.UNKNOWN, "width_mm"), (FieldState.CONFLICT, "usb_c_video")]:
        with pytest.raises(ValidationError, match="eligible"):
            Candidate(
                product_id="fixture-monitor",
                overall_state=state,
                eligible=True,
                unknown_fields=[field] if state == FieldState.UNKNOWN else [],
                conflict_fields=[field] if state == FieldState.CONFLICT else [],
                checker_version="fixture-v1",
            )


def test_llm_constraint_proposal_cannot_self_activate():
    with pytest.raises(ValidationError, match="cannot self-validate"):
        Constraint(
            field="price_cny",
            operator=ConstraintOperator.LTE,
            normalized_value=3000,
            unit="CNY",
            strength=ConstraintStrength.HARD,
            provenance=ConstraintProvenance.CURRENT_INPUT,
            source_text="预算 3000 元",
            source_turn=1,
            confidence=0.9,
            proposed_by="llm",
            supported=True,
            active=True,
        )


def test_all_twelve_v1_products_map_without_data_change():
    adapter = V1CompatibilityAdapter(DomainPackLoader().load(DEFAULT_MONITOR_PACK))
    products = adapter.products_from_v1()
    assert len(products) == 12
    assert {item.product_id for item in products} == {
        row["model_id"] for row in adapter.catalog.products
    }
    for generic, original in zip(products, adapter.catalog.products, strict=True):
        assert generic.brand == original["brand"]
        assert generic.model_name == original["model_name"]
        assert generic.region == original["region"]
        assert generic.attributes["resolution"] == original["resolution"]


def test_frozen_catalog_and_evaluation_hashes_are_unchanged():
    expected = {
        "smartbuy/data/catalog/monitors_v1.json": "b50fd4818575747dab00ffe922ea9720b3a7196e1a5162c0494cd6454a04210a",
        "smartbuy/eval/cases.jsonl": "85cdc9286e389e936fd6e2256216e4b60ec57b4dd450b268a58ab37f56bd4032",
        "smartbuy/eval/stage4_cases.jsonl": "a25c8852887096d91da6758f64d69bd1e69bb30a413425a77883de03cea77a0f",
        "smartbuy/eval/stage5_natural_cases.jsonl": "27f6470af07c1844bbbc4e3a7280a0529d1782aa91c6dce2e36a66700d537400",
        "smartbuy/eval/stage6_natural_cases.jsonl": "6082ac83d72441fedf7ac3083a3c53f31d538ca54216f2cf99d3a9de5068e0ef",
    }
    actual = {
        relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        for relative in expected
    }
    assert actual == expected


def test_feature_flag_defaults_off_and_rejects_ambiguous_value(monkeypatch):
    monkeypatch.delenv("PROOFPICK_DOMAIN_PACK_ENABLED", raising=False)
    assert DomainPackSettings.from_environment().enabled is False
    monkeypatch.setenv("PROOFPICK_DOMAIN_PACK_ENABLED", "auto")
    with pytest.raises(ValueError, match="true or false"):
        DomainPackSettings.from_environment()
