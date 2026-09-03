"""V2-6C-R1 deterministic product identity and candidate-scope contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from smartbuy.domain.models import CandidateDecision, ConstraintStatus, DecisionReport, EvidenceReference
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.identity import (
    ProductIdentityMismatch,
    ProductIdentityResolver,
    ProductScopeResolutionStatus,
    ProductScopeType,
    evidence_identity_status,
    require_product_in_scope,
)
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)


ROOT = Path(__file__).resolve().parents[3]


def _product(
    product_id: str,
    configuration_id: str,
    part_number: str,
    region: str,
    *,
    family_id: str = "acme-orbit-14",
    panel_type: str = "IPS",
    aliases: list[str] | None = None,
) -> dict:
    family_label = "Nova 16" if "nova" in family_id else "Orbit 14"
    return {
        "product_id": product_id,
        "domain_id": "computer",
        "brand": "Acme",
        "model_name": f"Acme {family_label} ({configuration_id})",
        "region": region,
        "variant_key": configuration_id.casefold(),
        "aliases": aliases or [],
        "attributes": {
            "family_id": family_id,
            "configuration_id": configuration_id,
            "part_number": part_number,
            "panel_type": panel_type,
        },
        "evidence": [],
    }


@pytest.fixture
def products() -> dict[str, dict]:
    rows = [
        _product("acme-orbit-a1-us", "A1-CFG", "SKU-A1", "US", panel_type="OLED", aliases=["orbit-oled-us"]),
        _product("acme-orbit-a2-ca", "A2-CFG", "SKU-A2", "CA", aliases=["orbit-ips-ca"]),
        _product("acme-orbit-a3-us", "A3-CFG", "SKU-A3", "US", aliases=["orbit-ips-us"]),
        _product(
            "acme-nova-n1-de",
            "N1-CFG",
            "SKU-N1",
            "DE",
            family_id="acme-nova-16",
            aliases=["nova-workstation-de"],
        ),
    ]
    return {row["product_id"]: row for row in rows}


@pytest.fixture
def resolver() -> ProductIdentityResolver:
    return ProductIdentityResolver(
        domain_id="computer",
        data_version="computer-data-v1",
        index_version="computer-index-v1",
    )


@pytest.mark.parametrize(
    ("query", "expected_id", "expected_quote"),
    [
        ("核验 A1-CFG 的规格", "acme-orbit-a1-us", "A1-CFG"),
        ("SKU SKU-A2 属于哪里", "acme-orbit-a2-ca", "SKU-A2"),
        ("核验 acme-orbit-a3-us", "acme-orbit-a3-us", "acme-orbit-a3-us"),
        ("orbit-oled-us 的配置", "acme-orbit-a1-us", "orbit-oled-us"),
        ("ACME ORBIT 14 (A2-CFG) 的规格", "acme-orbit-a2-ca", "A2-CFG"),
        ("请看 a3-cfg。", "acme-orbit-a3-us", "a3-cfg"),
    ],
)
def test_exact_identity_priority_and_spans(
    resolver: ProductIdentityResolver,
    products: dict[str, dict],
    query: str,
    expected_id: str,
    expected_quote: str,
) -> None:
    scope = resolver.resolve(query, products)
    assert scope.scope_type == ProductScopeType.EXACT_CONFIGURATION
    assert scope.product_ids == [expected_id]
    assert scope.mentioned_quotes == [expected_quote]
    mention = scope.mentions[0]
    assert query[mention.span_start:mention.span_end] == expected_quote


@pytest.mark.parametrize(
    "query",
    [
        "A1-CFGX 不是 A1-CFG",
        "XA1-CFG 不应匹配",
        "SKU-A11 不应匹配 SKU-A1",
        "acme-orbit-a1-usa 不应匹配产品 ID",
    ],
)
def test_shared_prefix_never_grants_configuration_identity(
    resolver: ProductIdentityResolver,
    products: dict[str, dict],
    query: str,
) -> None:
    scope = resolver.resolve(query, products)
    assert scope.product_ids != ["acme-orbit-a1-us"]


@pytest.mark.parametrize(
    ("query", "scope_type", "count", "clarification"),
    [
        ("Orbit 14 有哪些规格？", ProductScopeType.AMBIGUOUS_PRODUCT_SCOPE, 3, True),
        ("筛选 Orbit 14 配置", ProductScopeType.PRODUCT_FAMILY, 3, False),
        ("比较 Orbit 14 的配置", ProductScopeType.EXPLICIT_COMPARISON, 3, False),
        ("Orbit 14 美国 OLED 配置是哪一个？", ProductScopeType.EXACT_CONFIGURATION, 1, False),
        ("Orbit 14 哪一个配置？", ProductScopeType.AMBIGUOUS_PRODUCT_SCOPE, 3, True),
    ],
)
def test_family_semantics_are_explicit(
    resolver: ProductIdentityResolver,
    products: dict[str, dict],
    query: str,
    scope_type: ProductScopeType,
    count: int,
    clarification: bool,
) -> None:
    scope = resolver.resolve(query, products)
    assert scope.scope_type == scope_type
    assert len(scope.product_ids) == count
    assert scope.clarification_required is clarification


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("比较 A1-CFG 与 A2-CFG", {"acme-orbit-a1-us", "acme-orbit-a2-ca"}),
        ("不要把 SKU-A1 和 SKU-A3 混成一个配置", {"acme-orbit-a1-us", "acme-orbit-a3-us"}),
        ("A1-CFG 是否等同于 A3-CFG", {"acme-orbit-a1-us", "acme-orbit-a3-us"}),
    ],
)
def test_explicit_comparison_contains_only_named_configurations(
    resolver: ProductIdentityResolver,
    products: dict[str, dict],
    query: str,
    expected: set[str],
) -> None:
    scope = resolver.resolve(query, products)
    assert scope.scope_type == ProductScopeType.EXPLICIT_COMPARISON
    assert set(scope.product_ids) == expected


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "仅核对 A1-CFG 的规格，A2-CFG、A3-CFG 都不要混进来。",
            {"acme-orbit-a1-us"},
        ),
        (
            "SKU-A1 属于什么地区？不要扩展到其他 Orbit 配置。",
            {"acme-orbit-a1-us"},
        ),
        (
            "A2-CFG 仅接受 CA 资料并排除 US 地区证据。",
            {"acme-orbit-a2-ca"},
        ),
        (
            "核验 A1-CFG；A2-CFG 即使值相同也不能作为 A1-CFG 的事实。",
            {"acme-orbit-a1-us"},
        ),
        (
            "只把 A1-CFG、A2-CFG 放进比较范围，A3-CFG 明确排除。",
            {"acme-orbit-a1-us", "acme-orbit-a2-ca"},
        ),
    ],
)
def test_exclusion_phrases_never_reverse_the_primary_reference(
    resolver: ProductIdentityResolver,
    products: dict[str, dict],
    query: str,
    expected: set[str],
) -> None:
    scope = resolver.resolve(query, products)
    assert set(scope.product_ids) == expected
    assert not set(scope.product_ids) & set(scope.exclude_product_ids)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("筛选内存足够的电脑", {"acme-orbit-a1-us", "acme-orbit-a2-ca", "acme-orbit-a3-us", "acme-nova-n1-de"}),
        ("只接受 US 配置", {"acme-orbit-a1-us", "acme-orbit-a3-us"}),
        ("只接受 US，不接受 CA 或 DE", {"acme-orbit-a1-us", "acme-orbit-a3-us"}),
        ("筛选 Orbit 系列的 US 配置", {"acme-orbit-a1-us", "acme-orbit-a3-us"}),
    ],
)
def test_catalog_filters_use_exact_pack_literals_and_regions(
    resolver: ProductIdentityResolver,
    products: dict[str, dict],
    query: str,
    expected: set[str],
) -> None:
    scope = resolver.resolve(query, products)
    assert scope.scope_type == ProductScopeType.CATALOG_FILTER
    assert set(scope.product_ids) == expected


@pytest.mark.parametrize(
    "query",
    [
        "型号 ZX-9999 的接口是什么？",
        "配置号 UNKNOWN-42 的重量是多少？",
        "SKU MISSING-100 是否有货？",
    ],
)
def test_unknown_identity_enters_open_scope_without_local_substitution(
    resolver: ProductIdentityResolver,
    products: dict[str, dict],
    query: str,
) -> None:
    scope = resolver.resolve(query, products)
    assert scope.scope_type == ProductScopeType.OPEN_UNKNOWN_PRODUCT
    assert scope.resolution_status == ProductScopeResolutionStatus.OPEN_REQUIRED
    assert scope.product_ids == []


def _scope(resolver: ProductIdentityResolver, products: dict[str, dict]):
    return resolver.resolve("核验 A1-CFG", products)


def test_scope_permits_only_resolved_product(
    resolver: ProductIdentityResolver, products: dict[str, dict]
) -> None:
    scope = _scope(resolver, products)
    assert scope.permits("acme-orbit-a1-us")
    assert not scope.permits("acme-orbit-a2-ca")


def test_scope_rejects_wrong_data_version(
    resolver: ProductIdentityResolver, products: dict[str, dict]
) -> None:
    with pytest.raises(ValueError, match="runtime identity mismatch"):
        _scope(resolver, products).assert_runtime(
            domain_id="computer", data_version="other-data"
        )


def test_scope_rejects_wrong_index_version(
    resolver: ProductIdentityResolver, products: dict[str, dict]
) -> None:
    with pytest.raises(ValueError, match="index identity mismatch"):
        _scope(resolver, products).assert_runtime(
            domain_id="computer",
            data_version="computer-data-v1",
            index_version="other-index",
        )


def test_scope_guard_rejects_out_of_scope_product(
    resolver: ProductIdentityResolver, products: dict[str, dict]
) -> None:
    with pytest.raises(ProductIdentityMismatch, match="outside"):
        require_product_in_scope(
            products["acme-orbit-a2-ca"],
            _scope(resolver, products),
            data_version="computer-data-v1",
        )


@pytest.mark.parametrize(
    ("updates", "field", "valid", "reason"),
    [
        ({}, "panel_type", True, "identity_bound"),
        ({"field_id": "memory_gb"}, "panel_type", False, "field_mismatch"),
        ({"region": "CA"}, "panel_type", False, "region_mismatch_only"),
        ({"variant_key": "a2-cfg"}, "panel_type", False, "identity_mismatch"),
        ({"source_id": ""}, "panel_type", False, "source_untraceable"),
    ],
)
def test_evidence_closure_is_fail_closed(
    products: dict[str, dict],
    updates: dict,
    field: str,
    valid: bool,
    reason: str,
) -> None:
    evidence = {
        "evidence_id": "ev-1",
        "source_id": "src-1",
        "field_id": "panel_type",
        "region": "US",
        "variant_key": "a1-cfg",
    }
    evidence.update(updates)
    assert evidence_identity_status(
        products["acme-orbit-a1-us"], evidence, field=field
    ) == (valid, reason)


def test_scope_fingerprint_is_deterministic(
    resolver: ProductIdentityResolver, products: dict[str, dict]
) -> None:
    first = _scope(resolver, products)
    second = _scope(resolver, products)
    assert first.fingerprint == second.fingerprint


def test_scope_serialization_preserves_identity_contract(
    resolver: ProductIdentityResolver, products: dict[str, dict]
) -> None:
    payload = _scope(resolver, products).model_dump(mode="json")
    assert payload["domain_id"] == "computer"
    assert payload["configuration_ids"] == ["A1-CFG"]
    assert payload["regions"] == ["US"]
    assert payload["data_version"] == "computer-data-v1"
    assert payload["index_version"] == "computer-index-v1"


def _laptop_repository(tmp_path):
    domain_path = ROOT / "smartbuy" / "domain_packs" / "laptop"
    pack_path = ROOT / "smartbuy" / "product_packs" / "examples" / "laptop-v1" / "pack.json"
    pack = DomainPackLoader().load(domain_path)
    manager = DomainProductPackManager(tmp_path / "data", domain_pack_path=domain_path)
    snapshot = manager.publish(manager.stage(pack_path).data_version)
    return DomainReadonlyRepository(snapshot, pack)


def test_domain_tools_reject_candidate_pool_expansion(tmp_path) -> None:
    repository = _laptop_repository(tmp_path)
    products = repository.load()
    scope = ProductIdentityResolver(
        domain_id="laptop", data_version=repository.snapshot.data_version
    ).resolve("比较 H7606WI 和 H7606WX", products)
    constraints = [{"field": "gpu_vram_gb", "operator": "gte", "value": 8, "unit": "GB"}]
    queried = DomainProductQueryTool(repository).run(constraints, scope=scope)
    assert {row["product_id"] for row in queried.data["rows"]} == set(scope.product_ids)
    leaked = DomainConstraintCheckerTool(repository).run(
        constraints,
        candidate_ids=[*scope.product_ids, "asus-proart-p16-h7606ww-cn"],
        scope=scope,
    )
    assert leaked.status == "failed" and leaked.data["fail_closed"] is True


def test_evidence_tool_rejects_out_of_scope_identity(tmp_path) -> None:
    repository = _laptop_repository(tmp_path)
    products = repository.load()
    scope = ProductIdentityResolver(
        domain_id="laptop", data_version=repository.snapshot.data_version
    ).resolve("核验 H7606WI", products)
    result = DomainEvidenceCheckTool(repository).run(
        "asus-proart-p16-h7606wx-cn",
        [{"field": "gpu_vram_gb", "operator": "eq", "value": 16, "unit": "GB"}],
        scope=scope,
    )
    assert result.status == "failed" and result.error_code == "product_unavailable"


def test_public_identity_envelopes_reject_model_product_mismatch() -> None:
    common = {
        "source_id": "src-1",
        "source_url": "https://example.invalid/source",
        "source_type": "official",
        "model_id": "product-a",
        "product_id": "product-b",
        "region": "US",
    }
    with pytest.raises(ValidationError, match="product identity"):
        EvidenceReference.model_validate(common)
    with pytest.raises(ValidationError, match="product identity"):
        CandidateDecision(
            model_id="product-a",
            product_id="product-b",
            overall_status=ConstraintStatus.UNKNOWN,
        )
    resolver = ProductIdentityResolver(
        domain_id="computer", data_version="computer-data-v1"
    )
    product = _product("acme-orbit-a1-us", "A1-CFG", "SKU-A1", "US")
    scope = resolver.resolve("核验 A1-CFG", {product["product_id"]: product})
    with pytest.raises(ValidationError, match="expands the resolved product scope"):
        DecisionReport(
            request_summary="malicious report expansion",
            product_scope=scope,
            candidates=[
                CandidateDecision(
                    model_id="outside-product",
                    overall_status=ConstraintStatus.UNKNOWN,
                )
            ],
            stop_reason="blocked",
        )


def test_resolver_rejects_monitor_laptop_catalog_mix(
    resolver: ProductIdentityResolver, products: dict[str, dict]
) -> None:
    mixed = {key: dict(value) for key, value in products.items()}
    mixed["acme-nova-n1-de"]["domain_id"] = "monitor"
    with pytest.raises(ValueError, match="crosses domain boundary"):
        resolver.resolve("筛选设备", mixed)
