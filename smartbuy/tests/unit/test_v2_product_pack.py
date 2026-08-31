"""Product Pack schema, normalization, licensing, and temporary-ledger gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from smartbuy.product_packs import (
    ProductPackLoader,
    ProductPackRuntimeSettings,
    ProductPackValidationError,
    RequestEvidenceRecord,
    RequestEvidenceWorkspace,
    resolve_product_snapshot,
)
from smartbuy.product_packs.loader import DEFAULT_SCHEMA_PATH


EXAMPLE = (
    Path(__file__).resolve().parents[2]
    / "product_packs/examples/monitor-u2725qe-us/pack.json"
)


def _payload() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _write_pack(tmp_path: Path, payload: dict) -> Path:
    root = tmp_path / "pack"
    root.mkdir()
    path = root / "pack.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def test_json_schema_and_example_pack_are_versioned_and_valid():
    schema = json.loads(DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_payload())
    loaded = ProductPackLoader().load(EXAMPLE)
    assert loaded.document.schema_version == "1.0.0"
    assert loaded.document.compatibility.embedding_dimensions == 1024
    assert loaded.document.compatibility.embedding_model == "text-embedding-v4"
    assert len(loaded.normalized_products) == 1
    assert len(loaded.normalized_evidence) == 16


def test_model_brand_alias_region_variant_units_and_null_are_normalized():
    loaded = ProductPackLoader().load(EXAMPLE)
    product = loaded.normalized_products[0]
    assert product["model_id"] == "dell-u2725qe-us"
    assert product["brand"] == "Dell"
    assert product["region"] == "US"
    assert product["variant_key"] == "u2725qe-us-210-bqhr"
    assert product["width_mm"] == pytest.approx(612.394)
    assert product["release_date"] is None
    assert not [item for item in loaded.normalized_evidence if item["field_id"] == "release_date"]


@pytest.mark.parametrize(
    "mutation",
    [
        "invalid_unit",
        "duplicate_model",
        "wrong_region",
        "missing_source_evidence",
        "unknown_string",
        "restricted_source",
        "license_overclaim",
        "base_source_collision",
    ],
)
def test_invalid_product_packs_fail_closed(tmp_path, mutation):
    payload = _payload()
    if mutation == "invalid_unit":
        payload["products"][0]["attributes"]["width_mm"]["unit"] = "yard"
    elif mutation == "duplicate_model":
        payload["products"].append(payload["products"][0])
    elif mutation == "wrong_region":
        payload["products"][0]["market"] = "CN"
    elif mutation == "missing_source_evidence":
        payload["evidence"] = payload["evidence"][:-1]
    elif mutation == "unknown_string":
        payload["products"][0]["attributes"]["release_date"]["value"] = "unknown"
    elif mutation == "restricted_source":
        payload["sources"][0]["redistribution_status"] = "restricted"
    elif mutation == "license_overclaim":
        payload["license"]["redistribution_status"] = "redistributable"
    elif mutation == "base_source_collision":
        old_source = payload["sources"][0]["source_id"]
        new_source = "src-dell-u2723qe-cn-product"
        payload["sources"][0]["source_id"] = new_source
        payload["products"][0]["official_source_ids"] = [new_source]
        for evidence in payload["evidence"]:
            if evidence["source_id"] == old_source:
                evidence["source_id"] = new_source
    with pytest.raises(ProductPackValidationError):
        ProductPackLoader().load(_write_pack(tmp_path, payload))


def test_corrupt_pack_and_source_hash_are_rejected(tmp_path):
    root = tmp_path / "corrupt"
    root.mkdir()
    corrupt = root / "pack.json"
    corrupt.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ProductPackValidationError):
        ProductPackLoader().load(corrupt)
    payload = _payload()
    payload["sources"][0]["content_hash"] = "0" * 64
    with pytest.raises(ProductPackValidationError, match="capture hash"):
        ProductPackLoader().load(_write_pack(tmp_path, payload))


def test_request_evidence_is_external_temporary_and_never_auto_promoted(tmp_path):
    workspace = RequestEvidenceWorkspace(tmp_path / "request-evidence")
    record = RequestEvidenceRecord(
        request_id="request-1",
        evidence_id="temporary-1",
        source_id="source-candidate-1",
        product_id="dell-u2725qe-us",
        field_id="price_cny",
        raw_value="$699.99",
        normalized_value=699.99,
        unit="USD",
        snippet="请求级临时片段，仅用于后续人工治理。",
        source_uri="https://example.com/product",
        market="US",
        variant_key="u2725qe-us-210-bqhr",
        source_version="observed-page",
        observed_at="2026-08-31T00:00:00Z",
    )
    workspace.append(record)
    saved = workspace.read("request-1")
    assert len(saved) == 1
    assert saved[0].trust_state == "temporary"
    assert saved[0].promotion_status == "not_reviewed"
    with pytest.raises(ValueError, match="duplicate"):
        workspace.append(record)
    assert workspace.clear("request-1") is True
    assert workspace.read("request-1") == []


def test_product_pack_flag_defaults_off_and_is_strict(monkeypatch):
    monkeypatch.delenv("PROOFPICK_PRODUCT_PACK_ENABLED", raising=False)
    assert ProductPackRuntimeSettings.from_environment().enabled is False
    monkeypatch.setenv("PROOFPICK_PRODUCT_PACK_ENABLED", "true")
    assert ProductPackRuntimeSettings.from_environment().enabled is True
    monkeypatch.setenv("PROOFPICK_PRODUCT_PACK_ENABLED", "yes")
    with pytest.raises(ValueError, match="true or false"):
        ProductPackRuntimeSettings.from_environment()


def test_disabled_flag_does_not_touch_missing_or_invalid_runtime_root(tmp_path):
    settings = ProductPackRuntimeSettings(
        enabled=False,
        runtime_root=Path(__file__).resolve().parents[3],
    )
    assert resolve_product_snapshot(settings) is None
