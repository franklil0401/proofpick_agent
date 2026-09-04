"""V2-9C regressions for intent, identity scope and evidence closure."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from smartbuy.agent import DomainDecisionAgent, PurchaseDecisionAgent
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.constraints import CandidateConstraintVerifier, ConstraintNormalizer
from smartbuy.db.build_database import build_database
from smartbuy.decision_core.intent import QueryUnderstandingEngine
from smartbuy.domain import UserRequirements
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.identity import ProductIdentityResolver, ProductScopeType, QueryIntent
from smartbuy.memory import DomainPreferenceMemoryStore
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)


ROOT = Path(__file__).resolve().parents[3]


def _domain_agent(tmp_path: Path, domain_id: str) -> DomainDecisionAgent:
    domain_path = ROOT / "smartbuy" / "domain_packs" / domain_id
    product_path = (
        ROOT / "smartbuy" / "product_packs" / "examples" / f"{domain_id}-v1" / "pack.json"
    )
    pack = DomainPackLoader().load(domain_path)
    manager = DomainProductPackManager(tmp_path / "data", domain_pack_path=domain_path)
    snapshot = manager.publish(manager.stage(product_path).data_version)
    repository = DomainReadonlyRepository(snapshot, pack)
    return DomainDecisionAgent(
        pack,
        repository,
        DomainProductQueryTool(repository),
        DomainEvidenceCheckTool(repository),
        DomainConstraintCheckerTool(repository),
        NaturalConstraintEngine(pack),
        DomainPreferenceMemoryStore(tmp_path / "memory", pack),
    )


def _identity(agent: DomainDecisionAgent, query: str):
    products = agent.repository.load()
    aliases = {
        field_id: {
            **definition.value_aliases,
            **{value: value for value in definition.enum_values},
        }
        for field_id, definition in agent.pack.fields.items()
        if definition.value_aliases or definition.enum_values
    }
    scope = ProductIdentityResolver(
        domain_id=agent.pack.domain_id,
        data_version=agent.repository.snapshot.data_version,
        qualifier_aliases=aliases,
    ).resolve(query, products)
    return scope, QueryUnderstandingEngine(agent.pack).analyze(query, scope)


@pytest.mark.asyncio
async def test_fact_fields_do_not_become_purchase_constraints(tmp_path: Path) -> None:
    agent = _domain_agent(tmp_path, "headphone")
    report = await agent.run("QCUE2-BLACK-US 的防水等级与降噪续航请给证据。")
    assert report.query_intent == QueryIntent.EXACT_FACT_VERIFICATION
    assert report.constraint_set.active(hard_only=True, supported_only=True) == []
    assert {(item.model_id, item.field) for item in report.evidence} >= {
        ("bose-qc-ultra-earbuds-2g-black-us", "water_resistance"),
        ("bose-qc-ultra-earbuds-2g-black-us", "battery_hours_anc"),
    }


@pytest.mark.asyncio
async def test_comparison_keeps_all_products_and_field_evidence(tmp_path: Path) -> None:
    agent = _domain_agent(tmp_path, "headphone")
    cases = [
        (
            "Bose Ultra 二代头戴与 QC 二代头戴的续航和空间音频有何不同？",
            {"bose-qc-headphones-2g-black-us", "bose-qc-ultra-headphones-2g-black-us"},
            {"battery_hours", "spatial_audio"},
        ),
        (
            "对比 Nova Pro Wireless 的 PS 与 Xbox 两个配置支持的平台。",
            {
                "steelseries-arctis-nova-pro-wireless-ps-us",
                "steelseries-arctis-nova-pro-wireless-xbox-us",
            },
            {"supported_platforms", "configuration_id"},
        ),
    ]
    for query, expected_products, expected_fields in cases:
        report = await agent.run(query)
        assert report.query_intent == QueryIntent.EXPLICIT_COMPARISON
        assert set(report.product_scope.product_ids) == expected_products
        assert report.constraint_set.active(hard_only=True, supported_only=True) == []
        evidence = {(item.model_id, item.field) for item in report.evidence}
        assert expected_products == {item[0] for item in evidence if item[1] in expected_fields}
        assert all((product_id, field) in evidence for product_id in expected_products for field in expected_fields)


@pytest.mark.asyncio
async def test_ambiguous_identity_and_threshold_stop_before_tools(tmp_path: Path) -> None:
    laptop = _domain_agent(tmp_path / "laptop", "laptop")
    headphone = _domain_agent(tmp_path / "headphone", "headphone")
    for agent, query in (
        (laptop, "XPS 13 的屏幕怎么样？"),
        (headphone, "Sony XM5 戴着舒服吗？"),
        (headphone, "我只想要续航久一点的耳机。"),
        (headphone, "Nova Pro Wireless 哪个版本适合我？"),
    ):
        report = await agent.run(query)
        assert report.clarification_state.value == "pending"
        assert report.tool_call_count == 0
        assert report.usage["provider_calls"] == 0
        assert report.recommended_model_ids == []


@pytest.mark.asyncio
async def test_unknown_product_remains_fail_closed_before_tools(tmp_path: Path) -> None:
    agent = _domain_agent(tmp_path, "headphone")
    report = await agent.run("核验目录外型号 ZX-9999 耳机的续航。")
    assert report.product_scope.resolution_status.value == "open_required"
    assert report.abstained is True
    assert report.tool_call_count == 0
    assert report.usage["provider_calls"] == 0
    assert report.usage["result_status"] == "insufficient_evidence"


@pytest.mark.asyncio
async def test_family_filter_can_return_multiple_valid_configurations(tmp_path: Path) -> None:
    agent = _domain_agent(tmp_path, "laptop")
    report = await agent.run("中国版 H7606 要 4TB 存储，并且显存至少 16GB。")
    assert set(report.recommended_model_ids) == {
        "asus-proart-p16-h7606ww-cn",
        "asus-proart-p16-h7606wx-cn",
    }
    assert report.product_scope.scope_type in {
        ProductScopeType.PRODUCT_FAMILY,
        ProductScopeType.EXACT_CONFIGURATION,
    }
    assert set(report.recommended_model_ids) <= set(report.product_scope.product_ids)


@pytest.mark.asyncio
async def test_pack_enabled_fields_are_enforced_by_checker(tmp_path: Path) -> None:
    agent = _domain_agent(tmp_path, "laptop")
    oled = await agent.run("美国版 XPS 13：OLED、内存不少于 32GB。")
    assert oled.recommended_model_ids == ["dell-xps13-9350-usexchcto9350lnl06-us"]
    assert oled.constraint_verification.candidates[0].unsupported_constraints == []
    israel = await agent.run("以色列地区、Windows 11 Pro、存储至少 1TB 的笔记本。")
    assert set(israel.recommended_model_ids) == {
        "hp-elitebook-840-g11-9g0c0et-il",
        "hp-zbook-firefly14-g11-98n14et-il",
    }


@pytest.mark.asyncio
async def test_wireless_is_not_chinese_negation(tmp_path: Path) -> None:
    agent = _domain_agent(tmp_path, "headphone")
    report = await agent.run("美国版、兼容 PS5，并且要带无线接收器。")
    active = {
        item.field: item.normalized_value
        for item in report.constraint_set.active(hard_only=True, supported_only=True)
    }
    assert active["wireless_dongle"] is True
    assert set(report.recommended_model_ids) == {
        "logitech-astro-a50x-black-us",
        "sony-inzone-h9-white-us",
        "steelseries-arctis-nova-7p-black-us",
        "steelseries-arctis-nova-pro-wireless-ps-us",
        "steelseries-arctis-nova-pro-wireless-xbox-us",
    }


def test_monitor_pack_independent_filters_and_clarification(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite"
    build_database(database)
    verifier = CandidateConstraintVerifier(database)
    queries = {
        "桌面只能放宽度 610mm 以内的中国版显示器。": {
            "asus-pg27aqdm-cn", "benq-ex2710u-cn", "lg-27gs95qe-b-cn"
        },
        "中国版、重量最多 6kg，而且 USB-C 必须能传视频。": {
            "asus-pa279crv-cn", "asus-pa27jcv-cn", "lg-27up850k-w-cn"
        },
        "中国大陆版里只要 5120×2880 分辨率。": {"asus-pa27jcv-cn"},
        "找中国版 IPS Black 面板的显示器。": {
            "dell-u2723qe-cn", "dell-u2724d-cn"
        },
        "美国版、27 英寸、4K，并要求 USB-C 供电至少 65W。": set(),
        # The only structured candidate retains the audited 60W/65W
        # governed conflict and therefore remains fail-closed.
    }

    with sqlite3.connect(database) as connection:
        pool = [row[0] for row in connection.execute("SELECT model_id FROM products")]
    for query, expected in queries.items():
        constraints = ConstraintNormalizer().build(query, source_turn=1)
        result = verifier.verify_candidates(constraints, pool)
        assert set(result.eligible_model_ids) == expected
        if "美国版" in query:
            benq = next(item for item in result.candidates if item.model_id == "benq-pd2705u-us")
            assert benq.conflict_fields == ["usb_c_power_delivery_w"]

    assert PurchaseDecisionAgent._infer_task_type(
        "只查 G2724D 中国版：刷新率和是否带 USB-C。", "filter"
    ) == "fact"


@pytest.mark.asyncio
async def test_pack_driven_compound_negation_and_numeric_version(tmp_path: Path) -> None:
    agent = _domain_agent(tmp_path, "headphone")
    report = await agent.run(
        "美国版头戴式耳机，不带主动降噪，但需要无线接收器，蓝牙版本至少 5.4。"
    )
    active = {
        item.field: (item.operator.value, item.normalized_value)
        for item in report.constraint_set.active(hard_only=True, supported_only=True)
    }
    assert active["active_noise_cancellation"] == ("eq", False)
    assert active["wireless_dongle"] == ("eq", True)
    assert active["bluetooth_version"] == ("gte", 5.4)
    assert "bluetooth" not in active
    assert "wearing_style" not in active


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("domain_id", "query"),
    [
        ("laptop", "给我一台性能强一点的笔记本。"),
        ("headphone", "我想要通话好一点的耳机。"),
    ],
)
async def test_qualitative_request_without_threshold_pauses_before_tools(
    tmp_path: Path, domain_id: str, query: str
) -> None:
    report = await _domain_agent(tmp_path, domain_id).run(query)
    assert report.clarification_state == "pending"
    assert report.tool_call_count == 0
    assert report.recommended_model_ids == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("domain_id", "query", "expected", "required_pairs"),
    [
        (
            "laptop",
            "美国版 XPS 13 OLED 与 FHD+ 配置的系统、分辨率和内存对比。",
            {
                "dell-xps13-9350-usexchcto9350lnl06-us",
                "dell-xps13-9350-usexcpcto9350lnl04-us",
            },
            {"operating_system", "resolution", "memory_gb"},
        ),
        (
            "headphone",
            "Bose Ultra 二代头戴和耳塞的形态、续航对比。",
            {
                "bose-qc-ultra-headphones-2g-black-us",
                "bose-qc-ultra-earbuds-2g-black-us",
            },
            {"form_factor", "battery_hours"},
        ),
        (
            "headphone",
            "Nova 7P 与 Nova Pro Wireless PS 版的降噪和续航有何不同？",
            {
                "steelseries-arctis-nova-7p-black-us",
                "steelseries-arctis-nova-pro-wireless-ps-us",
            },
            {"active_noise_cancellation", "battery_hours"},
        ),
    ],
)
async def test_comparison_scope_and_requested_field_evidence_are_closed(
    tmp_path: Path,
    domain_id: str,
    query: str,
    expected: set[str],
    required_pairs: set[str],
) -> None:
    report = await _domain_agent(tmp_path, domain_id).run(query)
    assert report.query_intent == QueryIntent.EXPLICIT_COMPARISON
    assert set(report.product_scope.product_ids) == expected
    evidence = {(item.model_id, item.field) for item in report.evidence}
    assert all((product_id, field) in evidence for product_id in expected for field in required_pairs)
    assert report.recommended_model_ids == []


def test_monitor_legacy_adapter_keeps_width_and_explicit_resolution() -> None:
    requirements = PurchaseDecisionAgent._augment_requirements(
        "中国版 2560×1440 显示器，机身宽度必须在 610mm 以内。",
        UserRequirements(summary="monitor", task_type="filter"),
    )
    active = {item.field: item.value for item in requirements.hard_constraints}
    assert active["resolution"] == "2560x1440"
    assert active["width_mm"] == 610.0
