"""V2-8 Headphone Domain/Product Pack governance tests (offline)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from smartbuy.domain_packs import DomainConstraintEvaluator, DomainPackRegistry
from smartbuy.product_packs import DomainProductPackManager, ProductPackLoader, ProductPackValidationError


ROOT = Path(__file__).resolve().parents[3]
HEADPHONE_DOMAIN = ROOT / "smartbuy" / "domain_packs" / "headphone"
HEADPHONE_PACK = ROOT / "smartbuy" / "product_packs" / "examples" / "headphone-v1" / "pack.json"


def _payload() -> dict:
    return json.loads(HEADPHONE_PACK.read_text(encoding="utf-8"))


def _write_pack(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_registry_loads_three_isolated_domains() -> None:
    registry = DomainPackRegistry(ROOT / "smartbuy" / "domain_packs")
    assert {"monitor", "laptop", "headphone"} <= set(registry.list())
    headphone = registry.load("headphone")
    assert len(headphone.fields) == 38
    assert headphone.canonical_field("耳机类型") == "form_factor"
    assert headphone.canonical_field("LDAC") == "supported_codecs"
    assert headphone.normalize_value("重量", 0.25, unit="kg") == 250
    assert "cpu_model" not in headphone.fields
    assert "usb_c_power_delivery_w" not in headphone.fields


def test_headphone_product_pack_has_exact_identity_and_three_source_tiers() -> None:
    loaded = ProductPackLoader(domain_pack_path=HEADPHONE_DOMAIN).load(HEADPHONE_PACK)
    assert len(loaded.normalized_products) == 12
    assert len({item["brand"] for item in loaded.normalized_products}) == 4
    assert len({(item["model_id"], item["region"], item["configuration_id"]) for item in loaded.normalized_products}) == 12
    assert len(loaded.document.sources) == 20
    assert len(loaded.normalized_evidence) == 336
    assert {item.source_type for item in loaded.document.sources} == {
        "official_spec", "professional_measurement", "subjective_review"
    }
    measurements = [item for item in loaded.document.sources if item.source_type == "professional_measurement"]
    assert len(measurements) == 4
    assert all(item.testing_organization and item.method_uri and item.tested_at for item in measurements)
    wh = [item for item in loaded.normalized_products if item["family_id"] == "sony-wh-1000xm5"]
    assert {(item["region"], item["configuration_id"]) for item in wh} == {
        ("US", "WH1000XM5-B-US"), ("CA", "WH1000XM5-B-CA")
    }


def test_subjective_evidence_is_soft_only_and_cannot_support_checker() -> None:
    loaded = ProductPackLoader(domain_pack_path=HEADPHONE_DOMAIN).load(HEADPHONE_PACK)
    policy = loaded.domain_pack.pack.policies
    subjective = set(policy["product_pack"]["source_field_permissions"]["subjective_review"])
    checker_hard_fields = set(policy["checker"]["hard_fields"])
    assert subjective == {"comfort_observation", "sound_signature", "call_quality_observation"}
    # These fields may be parsed as soft preference proposals, but the
    # deterministic Checker must never treat them as hard eligibility facts.
    assert subjective.isdisjoint(checker_hard_fields)
    assert all(
        row["field_id"] in subjective
        for row in loaded.normalized_evidence
        if next(source for source in loaded.document.sources if source.source_id == row["source_id"]).source_type
        == "subjective_review"
    )


def test_subjective_review_cannot_overwrite_official_hard_fact(tmp_path: Path) -> None:
    payload = _payload()
    product_id = "sony-wh-1000xm5-black-us"
    subjective_source = next(
        item["source_id"] for item in payload["sources"]
        if item["product_id"] == product_id and item["source_type"] == "subjective_review"
    )
    weight = next(
        item for item in payload["evidence"]
        if item["product_id"] == product_id and item["field_id"] == "weight_g"
    )
    weight["source_id"] = subjective_source
    source = next(item for item in payload["sources"] if item["source_id"] == subjective_source)
    weight["source_version"] = source["source_version"]
    with pytest.raises(ProductPackValidationError, match="not permitted"):
        ProductPackLoader(domain_pack_path=HEADPHONE_DOMAIN).load(_write_pack(tmp_path, payload))


def test_two_headphone_builds_are_identical_and_sqlite_valid(tmp_path: Path) -> None:
    first = DomainProductPackManager(tmp_path / "a", domain_pack_path=HEADPHONE_DOMAIN).stage(HEADPHONE_PACK)
    second = DomainProductPackManager(tmp_path / "b", domain_pack_path=HEADPHONE_DOMAIN).stage(HEADPHONE_PACK)
    assert first.manifest_hash == second.manifest_hash
    assert first.manifest["logical_data_sha256"] == second.manifest["logical_data_sha256"]
    assert first.manifest["artifact_sha256"] == second.manifest["artifact_sha256"]
    assert first.manifest["counts"] == {
        "products": 12,
        "product_attributes": 408,
        "source_records": 20,
        "evidence_records": 336,
        "price_observations": 0,
    }
    assert first.manifest["index"]["document_count"] == 12
    assert first.manifest["index"]["embedding_dimensions"] == 1024
    connection = sqlite3.connect(first.database_path)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_headphone_checker_is_pack_driven_and_unknown_fails_closed() -> None:
    loaded = ProductPackLoader(domain_pack_path=HEADPHONE_DOMAIN).load(HEADPHONE_PACK)
    product = next(item for item in loaded.normalized_products if item["configuration_id"] == "G735-WHITE-US")
    evidenced = {
        item["field_id"] for item in loaded.normalized_evidence if item["product_id"] == product["product_id"]
    }
    decisions, eligible = DomainConstraintEvaluator(loaded.domain_pack).evaluate(
        product,
        [
            {"field":"wireless_dongle","operator":"eq","value":True},
            {"field":"microphone","operator":"eq","value":True},
            {"field":"weight_g","operator":"lte","value":300,"unit":"g"},
        ],
        evidenced_fields=evidenced,
    )
    assert eligible and {item.state.value for item in decisions} == {"matched"}
    decisions, eligible = DomainConstraintEvaluator(loaded.domain_pack).evaluate(
        product,
        [{"field":"measured_latency_ms","operator":"lte","value":50,"unit":"ms"}],
        evidenced_fields=evidenced,
    )
    assert not eligible and decisions[0].state.value == "unknown"


def test_generic_runtime_does_not_embed_headphone_fields_or_models() -> None:
    paths = [
        ROOT / "smartbuy" / "agent" / "domain_agent.py",
        ROOT / "smartbuy" / "tools" / "domain.py",
        ROOT / "smartbuy" / "domain_packs" / "evaluator.py",
        ROOT / "smartbuy" / "ranking" / "ranker.py",
        ROOT / "smartbuy" / "memory" / "store.py",
    ]
    forbidden = {"supported_codecs", "battery_hours_anc", "WH-1000XM5", "G735-WHITE-US"}
    for path in paths:
        content = path.read_text(encoding="utf-8")
        assert not any(token in content for token in forbidden)
