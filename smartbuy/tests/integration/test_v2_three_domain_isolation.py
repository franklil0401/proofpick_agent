"""V2-8 three-domain contract, data and hardcoding isolation gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smartbuy.domain_packs import DomainPackRegistry, DomainPackValidationError
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.tools.domain import DomainReadonlyRepository


ROOT = Path(__file__).resolve().parents[3]
DOMAIN_ROOT = ROOT / "smartbuy" / "domain_packs"
HEADPHONE_DOMAIN = DOMAIN_ROOT / "headphone"
LAPTOP_DOMAIN = DOMAIN_ROOT / "laptop"
HEADPHONE_PACK = ROOT / "smartbuy" / "product_packs" / "examples" / "headphone-v1" / "pack.json"
LAPTOP_PACK = ROOT / "smartbuy" / "product_packs" / "examples" / "laptop-v1" / "pack.json"


def test_three_domains_reject_each_others_unique_fields() -> None:
    registry = DomainPackRegistry(DOMAIN_ROOT)
    packs = {name: registry.load(name) for name in ("monitor", "laptop", "headphone")}
    unique = {
        "monitor": "usb_c_power_delivery_w",
        "laptop": "gpu_vram_gb",
        "headphone": "supported_codecs",
    }
    for owner, field in unique.items():
        assert packs[owner].canonical_field(field) == field
        for other, pack in packs.items():
            if other != owner:
                with pytest.raises(DomainPackValidationError, match="unsupported"):
                    pack.canonical_field(field)


def test_product_data_and_evidence_cannot_cross_domain_boundary(tmp_path: Path) -> None:
    registry = DomainPackRegistry(DOMAIN_ROOT)
    headphone_manager = DomainProductPackManager(
        tmp_path / "headphone", domain_pack_path=HEADPHONE_DOMAIN
    )
    headphone = headphone_manager.publish(
        headphone_manager.stage(HEADPHONE_PACK).data_version
    )
    laptop_manager = DomainProductPackManager(
        tmp_path / "laptop", domain_pack_path=LAPTOP_DOMAIN
    )
    laptop = laptop_manager.publish(laptop_manager.stage(LAPTOP_PACK).data_version)
    assert headphone.manifest["domain_id"] == "headphone"
    assert laptop.manifest["domain_id"] == "laptop"
    assert headphone.data_version != laptop.data_version
    with pytest.raises(Exception, match="domain and data differ"):
        DomainReadonlyRepository(headphone, registry.load("laptop"))
    with pytest.raises(Exception, match="domain and data differ"):
        DomainReadonlyRepository(laptop, registry.load("headphone"))


def test_all_recorded_headphone_recommendations_respect_safety_gates() -> None:
    result = json.loads(
        (ROOT / "smartbuy/eval/results/v2_8_headphone_engineering_regression_after_fix.json")
        .read_text(encoding="utf-8")
    )
    metrics = result["metrics"]
    assert metrics["explicit_violation_recommendations"] == 0
    assert metrics["subjective_hard_fact_overrides"] == 0
    assert metrics["wrong_configuration_recommendations"] == 0
    assert metrics["wrong_region_recommendations"] == 0
    assert metrics["scope_leakage"] == 0
    assert metrics["checker_leakage"] == 0
    assert metrics["report_leakage"] == 0
    assert metrics["unknown_overclaims"] == 0


def test_shared_production_modules_contain_no_headphone_special_cases() -> None:
    roots = [
        ROOT / "smartbuy" / "agent",
        ROOT / "smartbuy" / "tools",
        ROOT / "smartbuy" / "constraints",
        ROOT / "smartbuy" / "ranking",
        ROOT / "smartbuy" / "memory",
        ROOT / "smartbuy" / "orchestration",
        ROOT / "smartbuy" / "retrieval",
    ]
    forbidden = {
        "WH-1000XM5",
        "G735-WHITE-US",
        "headphone-e2e-",
        "supported_codecs",
        "battery_hours_anc",
        "SteelSeries",
    }
    findings: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            content = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in content:
                    findings.append(f"{path.relative_to(ROOT)}:{token}")
    assert findings == []
