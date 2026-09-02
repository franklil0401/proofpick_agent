"""V2-6A Laptop Domain/Product Pack isolation and offline acceptance tests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from smartbuy.constraint_proposals.engine import ConstraintProposalValidator
from smartbuy.constraint_proposals.models import ProposalSource, ProposalStatus
from smartbuy.domain_packs import (
    DomainConstraintEvaluator,
    DomainPackLoader,
    DomainPackRegistry,
    DomainPackValidationError,
)
from smartbuy.product_packs import (
    DomainProductPackManager,
    ProductPackLoader,
    ProductPackValidationError,
)


ROOT = Path(__file__).resolve().parents[3]
LAPTOP_DOMAIN = ROOT / "smartbuy" / "domain_packs" / "laptop"
MONITOR_DOMAIN = ROOT / "smartbuy" / "domain_packs" / "monitor"
LAPTOP_PACK = ROOT / "smartbuy" / "product_packs" / "examples" / "laptop-v1" / "pack.json"
LAPTOP_CASES = ROOT / "smartbuy" / "eval" / "v2_6a_laptop_cases.jsonl"
LAPTOP_CASES_SHA256 = "3dfcc0f442bda2b6b4d2e96814a8973b415b3d8c8b9b33235924982fa1758d34"


def _payload() -> dict:
    return json.loads(LAPTOP_PACK.read_text(encoding="utf-8"))


def _write_pack(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _raw(
    quote: str,
    field: str,
    value,
    *,
    operator: str = "eq",
    unit: str | None = None,
    strength: str = "hard",
    status: str = "supported",
    kind: str = "supported_constraint",
) -> dict:
    return {
        "proposal_kind": kind,
        "field": field,
        "operator": operator if status == "supported" else None,
        "value": value,
        "unit": unit,
        "strength": strength,
        "action": "add",
        "status": status,
        "quote": quote,
        "clarification_question": "请明确可接受的重量上限。" if status != "supported" else None,
        "confidence": 1.0,
    }


def test_registry_loads_two_isolated_data_only_domains() -> None:
    registry = DomainPackRegistry(ROOT / "smartbuy" / "domain_packs")
    assert {"monitor", "laptop"} <= set(registry.list())
    laptop = registry.load("laptop")
    monitor = registry.load("monitor")
    assert laptop.domain_id == "laptop" and monitor.domain_id == "monitor"
    assert "memory_gb" in laptop.fields and "memory_gb" not in monitor.fields
    assert "usb_c_power_delivery_w" in monitor.fields
    assert "usb_c_power_delivery_w" not in laptop.fields
    assert "min_memory_gb" in laptop.pack.policies["memory"]["allowed_keys"]
    assert "min_memory_gb" not in monitor.pack.policies["memory"]["allowed_keys"]
    assert "display_size_inch" not in laptop.pack.policies["memory"]["allowed_keys"]
    assert "memory_gb" in laptop.pack.policies["report"]["allowed_fields"]
    assert "usb_c_power_delivery_w" not in laptop.pack.policies["report"]["allowed_fields"]
    assert "memory_gb" not in monitor.pack.policies["report"].get("allowed_fields", [])
    with pytest.raises(DomainPackValidationError, match="unavailable"):
        registry.load("missing-domain")


def test_generic_v2_6a_modules_do_not_embed_laptop_business_fields() -> None:
    generic_paths = [
        ROOT / "smartbuy" / "domain_packs" / "registry.py",
        ROOT / "smartbuy" / "domain_packs" / "evaluator.py",
        ROOT / "smartbuy" / "product_packs" / "domain_builder.py",
        ROOT / "smartbuy" / "product_packs" / "domain_cli.py",
    ]
    forbidden = {
        "cpu_model", "gpu_model", "memory_gb", "storage_gb",
        "battery_wh", "thunderbolt", "usb_c_charging",
    }
    for path in generic_paths:
        content = path.read_text(encoding="utf-8")
        assert not (forbidden & set(content.replace('"', " ").replace("'", " ").split()))


def test_laptop_fields_units_aliases_operators_and_bounds_are_pack_driven() -> None:
    pack = DomainPackLoader().load(LAPTOP_DOMAIN)
    assert len(pack.fields) == 49
    assert pack.canonical_field("雷电") == "thunderbolt"
    assert pack.normalize_value("硬盘", 1, unit="TB") == 1024
    assert pack.normalize_value("重量", 1500, unit="g") == 1.5
    assert pack.normalize_value("分辨率", "2.5K") == "2560x1600"
    assert pack.validate_operator("memory_gb", "gte").value == "gte"
    with pytest.raises(DomainPackValidationError, match="operator"):
        pack.validate_operator("warranty", "eq")
    with pytest.raises(DomainPackValidationError, match="bounds"):
        pack.normalize_value("weight_kg", 200, unit="kg")


def test_laptop_product_pack_has_exact_configurations_and_governed_evidence() -> None:
    loaded = ProductPackLoader(domain_pack_path=LAPTOP_DOMAIN).load(LAPTOP_PACK)
    assert len(loaded.normalized_products) == 12
    assert len({item["brand"] for item in loaded.normalized_products}) == 4
    assert len({item["variant_key"] for item in loaded.normalized_products}) == 12
    assert len(loaded.normalized_evidence) == 406
    assert {
        item["region"] for item in loaded.normalized_products
    } >= {"US", "CA", "CN", "IL", "GLOBAL", "DE", "PH"}
    dell = [item for item in loaded.normalized_products if item["family_id"] == "dell-xps13-9350"]
    assert len(dell) == 3
    assert {(item["region"], item["configuration_id"]) for item in dell} == {
        ("US", "usexchcto9350lnl06"),
        ("CA", "caexchcto9350lnl02"),
        ("US", "usexcpcto9350lnl04"),
    }


def test_every_non_null_checker_field_has_field_level_evidence() -> None:
    loaded = ProductPackLoader(domain_pack_path=LAPTOP_DOMAIN).load(LAPTOP_PACK)
    checker_fields = set(loaded.domain_pack.pack.policies["checker"]["supported_fields"])
    evidence = {
        (item["product_id"], item["field_id"])
        for item in loaded.normalized_evidence
    }
    checked = 0
    for product in loaded.normalized_products:
        for field_id in checker_fields:
            value = {
                "product_id": product["product_id"], "brand": product["brand"],
                "model_name": product["model_name"], "region": product["region"],
            }.get(field_id, product.get(field_id))
            if value is not None:
                checked += 1
                assert (product["product_id"], field_id) in evidence
    assert checked >= 300


def test_two_independent_builds_are_identical_and_sqlite_is_valid(tmp_path: Path) -> None:
    first = DomainProductPackManager(tmp_path / "a", domain_pack_path=LAPTOP_DOMAIN).stage(LAPTOP_PACK)
    second = DomainProductPackManager(tmp_path / "b", domain_pack_path=LAPTOP_DOMAIN).stage(LAPTOP_PACK)
    assert first.manifest_hash == second.manifest_hash
    assert first.manifest["logical_data_sha256"] == second.manifest["logical_data_sha256"]
    assert first.manifest["artifact_sha256"] == second.manifest["artifact_sha256"]
    assert first.manifest["counts"] == {
        "products": 12,
        "product_attributes": 540,
        "source_records": 12,
        "evidence_records": 406,
        "price_observations": 0,
    }
    assert first.manifest["index"]["status"] == "documents_ready"
    assert first.manifest["index"]["embedding_dimensions"] == 1024
    vector_documents = [
        json.loads(line)
        for line in (first.root / "vector_documents.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(vector_documents) == 12
    assert all(item["metadata"]["domain_id"] == "laptop" for item in vector_documents)
    assert all("usb_c_power_delivery_w" not in item["content"] for item in vector_documents)
    with pytest.raises(ProductPackValidationError, match="unfinished index"):
        DomainProductPackManager.require_completed_index(first)
    connection = sqlite3.connect(first.database_path)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_publish_current_and_rollback_preserve_one_atomic_version(tmp_path: Path) -> None:
    manager = DomainProductPackManager(tmp_path / "runtime", domain_pack_path=LAPTOP_DOMAIN)
    staged = manager.stage(LAPTOP_PACK)
    published = manager.publish(staged.data_version)
    assert manager.current().manifest_hash == published.manifest_hash
    rolled_back = manager.rollback(published.data_version)
    assert rolled_back.manifest_hash == published.manifest_hash
    assert manager.list_versions() == [
        {
            "data_version": published.data_version,
            "manifest_hash": published.manifest_hash,
            "current": True,
        }
    ]


def test_failed_stage_does_not_pollute_published_version(tmp_path: Path) -> None:
    manager = DomainProductPackManager(tmp_path / "runtime", domain_pack_path=LAPTOP_DOMAIN)
    published = manager.publish(manager.stage(LAPTOP_PACK).data_version)
    payload = _payload()
    payload["products"].append(payload["products"][0])
    with pytest.raises(ProductPackValidationError):
        manager.stage(_write_pack(tmp_path, payload))
    current = manager.current()
    assert current.data_version == published.data_version
    assert current.manifest_hash == published.manifest_hash


@pytest.mark.parametrize("mutation", ["duplicate", "wrong_region", "missing_evidence", "retail_spec"])
def test_invalid_or_unlicensed_laptop_packs_fail_closed(tmp_path: Path, mutation: str) -> None:
    payload = _payload()
    if mutation == "duplicate":
        payload["products"].append(payload["products"][0])
    elif mutation == "wrong_region":
        payload["products"][0]["market"] = "CA"
    elif mutation == "missing_evidence":
        payload["evidence"] = payload["evidence"][:-1]
    elif mutation == "retail_spec":
        payload["sources"][0]["source_type"] = "public_retail"
    with pytest.raises(ProductPackValidationError):
        ProductPackLoader(domain_pack_path=LAPTOP_DOMAIN).load(_write_pack(tmp_path, payload))


def test_domain_evaluator_is_deterministic_and_fails_closed_on_unknown() -> None:
    loaded = ProductPackLoader(domain_pack_path=LAPTOP_DOMAIN).load(LAPTOP_PACK)
    product = next(item for item in loaded.normalized_products if item["configuration_id"] == "H7606WX")
    fields = {
        item["field_id"]
        for item in loaded.normalized_evidence
        if item["product_id"] == product["product_id"]
    }
    decisions, eligible = DomainConstraintEvaluator(loaded.domain_pack).evaluate(
        product,
        [
            {"field": "memory_gb", "operator": "gte", "value": 32, "unit": "GB"},
            {"field": "resolution", "operator": "gte", "value": "2.5K"},
            {"field": "usb4", "operator": "eq", "value": True},
        ],
        evidenced_fields=fields,
    )
    assert eligible and {item.state.value for item in decisions} == {"matched"}
    decisions, eligible = DomainConstraintEvaluator(loaded.domain_pack).evaluate(
        product,
        [
            {
                "field": "display_size_inch",
                "operator": "range",
                "value": [15, 17],
                "unit": "inch",
            }
        ],
        evidenced_fields=fields,
    )
    assert eligible and decisions[0].state.value == "matched"
    decisions, eligible = DomainConstraintEvaluator(loaded.domain_pack).evaluate(
        product,
        [{"field": "price_cny", "operator": "lte", "value": 8000, "unit": "CNY"}],
        evidenced_fields=fields,
    )
    assert not eligible and decisions[0].state.value == "unknown"


def test_ten_laptop_expressions_use_exact_quotes_and_pack_validation() -> None:
    validator = ConstraintProposalValidator(DomainPackLoader().load(LAPTOP_DOMAIN))
    cases = [
        ("想要 32G 内存，至少 1T 固态。", [_raw("32G 内存", "memory_gb", 32, operator="gte", unit="GB"), _raw("1T 固态", "storage_gb", 1, operator="gte", unit="TB")]),
        ("重量不要超过 1.5kg。", [_raw("不要超过 1.5kg", "weight_kg", 1.5, operator="lte", unit="kg")]),
        ("需要独显，但不要游戏本那么重。", [_raw("独显", "gpu_type", "discrete"), _raw("不要游戏本那么重", "weight_kg", None, status="needs_confirmation", kind="needs_clarification")]),
        ("必须能用 USB-C 充电。", [_raw("USB-C 充电", "usb_c_charging", True)]),
        ("最好有雷电接口。", [_raw("雷电接口", "thunderbolt", True, strength="soft")]),
        ("屏幕至少 2.5K。", [_raw("至少 2.5K", "resolution", "2.5K", operator="gte")]),
        ("主要写代码，偶尔做视频。", [_raw("写代码，偶尔做视频", "primary_use", ["coding", "video"], operator="contains_all", strength="soft")]),
        ("预算八千以内。", [_raw("八千以内", "price_cny", 8000, operator="lte", unit="CNY")]),
        ("内存最好可以升级。", [_raw("内存最好可以升级", "upgradeability", ["memory"], operator="contains_all", strength="soft")]),
        ("不要把美版配置当成国行。", [_raw("国行", "region", "CN")]),
    ]
    proposals = [
        validator.validate(text, raw, source=ProposalSource.LLM, source_turn=1)
        for text, raws in cases
        for raw in raws
    ]
    assert len(cases) == 10
    assert all(
        item.source_span is not None
        and item.source_span.text == item.source_quote
        for item in proposals
    )
    pending = [item for item in proposals if item.status == ProposalStatus.NEEDS_CONFIRMATION]
    assert len(pending) == 1 and not pending[0].active
    assert all(item.active for item in proposals if item.status == ProposalStatus.SUPPORTED)


def test_laptop_eval_fixture_is_frozen_and_well_partitioned() -> None:
    payload = LAPTOP_CASES.read_bytes()
    cases = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    assert hashlib.sha256(payload).hexdigest() == LAPTOP_CASES_SHA256
    assert len(cases) == len({item["case_id"] for item in cases}) == 30
    assert {item["split"] for item in cases} == {
        "regression", "holdout", "hard_negative", "clarification"
    }
    assert sum(item["category"] == "structured_filter" for item in cases) == 10
    assert sum(item["category"] == "similar_configuration" for item in cases) == 5
    assert sum(item["category"] == "region_configuration" for item in cases) == 5
    assert sum(item["category"] in {"unknown_evidence", "unsupported"} for item in cases) == 5
    assert sum(item["category"] == "natural_constraint" for item in cases) == 5


def test_monitor_and_v1_frozen_hashes_remain_unchanged() -> None:
    expected = {
        "smartbuy/data/catalog/monitors_v1.json": "b50fd4818575747dab00ffe922ea9720b3a7196e1a5162c0494cd6454a04210a",
        "smartbuy/eval/stage4_cases.jsonl": "a25c8852887096d91da6758f64d69bd1e69bb30a413425a77883de03cea77a0f",
        "smartbuy/eval/stage6_natural_cases.jsonl": "6082ac83d72441fedf7ac3083a3c53f31d538ca54216f2cf99d3a9de5068e0ef",
    }
    assert {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in expected
    } == expected
