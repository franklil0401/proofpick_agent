"""Development regressions for exact registry identity precedence (fictional data)."""

from __future__ import annotations

import pytest

from smartbuy.identity import ProductIdentityResolver, ProductScopeType


def _catalog():
    rows = []
    for token, region in (("Q123", "CN"), ("Q123", "US"), ("Q124", "CN")):
        product_id = f"axiom-prism-{token.lower()}-{region.lower()}"
        rows.append({
            "product_id": product_id, "domain_id": "monitor", "brand": "Axiom",
            "model_name": f"Axiom Prism {token}", "region": region,
            "variant_key": f"{token}-{region}", "aliases": [token],
            "attributes": {"family_id": "axiom-prism", "configuration_id": f"{token}-{region}"},
            "evidence": [],
        })
    return {row["product_id"]: row for row in rows}


def _resolve(query):
    return ProductIdentityResolver(domain_id="monitor", data_version="fictional-v1").resolve(
        query, _catalog()
    )


@pytest.mark.parametrize("query", [
    "核验 Axiom Prism Q123、CN、axiom-prism-q123-cn 的接口。",
    "Prism 的 axiom-prism-q123-cn 接口是什么？",
    "Prism Q123 CN 的接口是什么？",
    "Q123-CN 的接口是什么？",
    "核验 Q123、axiom-prism-q123-cn 的接口。",
    "Axiom Prism Q123 的 axiom-prism-q123-cn 接口是什么？",
])
def test_exact_registry_identity_overrides_shared_series(query):
    scope = _resolve(query)
    assert scope.scope_type == ProductScopeType.EXACT_CONFIGURATION
    assert scope.product_ids == ["axiom-prism-q123-cn"]
    assert not scope.clarification_required


@pytest.mark.parametrize("query", ["Prism 的接口是什么？", "Axiom Prism Q123 的接口是什么？"])
def test_shared_family_and_multiregion_model_need_clarification(query):
    scope = _resolve(query)
    assert scope.clarification_required
    assert all(not scope.permits(item) for item in scope.product_ids)


@pytest.mark.parametrize("query", [
    "核验 axiom-prism-q123-cn，美国版的接口。",
    "核验 axiom-prism-q123-cn，加拿大版的接口。",
    "核验 axiom-prism-q123-cn，配置 Q124-CN 的接口。",
    "核验 Axiom Prism Q124、axiom-prism-q123-cn 的接口。",
])
def test_conflicting_exact_identity_region_or_configuration_cannot_disambiguate(query):
    scope = _resolve(query)
    assert scope.clarification_required
    assert scope.resolution_reason == "conflicting_registry_identity"
    assert not any(scope.permits(item) for item in scope.product_ids)


def test_explicit_comparison_keeps_only_named_configurations():
    scope = _resolve("比较 Prism 的 axiom-prism-q123-cn 和 axiom-prism-q124-cn；排除 Q123-US。")
    assert set(scope.product_ids) == {"axiom-prism-q123-cn", "axiom-prism-q124-cn"}
    assert scope.scope_type == ProductScopeType.EXPLICIT_COMPARISON
    assert not scope.clarification_required


def test_shared_series_does_not_expand_explicit_comparison():
    scope = _resolve("比较 Prism 的 axiom-prism-q123-cn 和 axiom-prism-q124-cn 的接口。")
    assert set(scope.product_ids) == {"axiom-prism-q123-cn", "axiom-prism-q124-cn"}
    assert not scope.clarification_required


def test_legacy_catalog_adapter_reuses_exact_reference_contract():
    from smartbuy.identity import resolve_catalog_identity

    rows = [
        {"model_id": row["product_id"], "model_name": row["model_name"],
         "brand": row["brand"], "region": row["region"]}
        for row in _catalog().values()
    ]
    result = resolve_catalog_identity("Prism Q123、CN、axiom-prism-q123-cn 的接口", rows)
    assert result.product_ids == ["axiom-prism-q123-cn"]
    assert not result.clarification_required
    assert resolve_catalog_identity("Prism 的接口", rows).clarification_required
    assert resolve_catalog_identity("Q123 的接口", rows).clarification_required


@pytest.mark.parametrize("field", ["configuration_id", "part_number"])
def test_registry_identifier_shared_between_regions_is_not_silently_unique(field):
    catalog = _catalog()
    for product in catalog.values():
        if "q123" in product["product_id"]:
            product["attributes"][field] = "SHARED-X910"
    resolver = ProductIdentityResolver(domain_id="monitor", data_version="fictional-v1")
    unknown_region = resolver.resolve("核验 SHARED-X910 的接口", catalog)
    assert unknown_region.clarification_required
    explicit_region = resolver.resolve("核验 SHARED-X910 CN 的接口", catalog)
    assert explicit_region.product_ids == ["axiom-prism-q123-cn"]
    assert not explicit_region.clarification_required


@pytest.mark.parametrize("query", [
    "筛选 Axiom Prism Q124、product_id axiom-prism-q123-cn 的产品。",
    "筛选 Q124-CN、商品ID axiom-prism-q123-cn。",
])
def test_purchase_verb_does_not_hide_incompatible_identity_assertions(query):
    scope = _resolve(query)
    assert scope.clarification_required
    assert scope.resolution_reason == "conflicting_registry_identity"
    assert not any(scope.permits(item) for item in scope.product_ids)


def test_explicit_two_product_filter_keeps_union():
    scope = _resolve("筛选 axiom-prism-q123-cn 和 axiom-prism-q124-cn。")
    assert set(scope.product_ids) == {"axiom-prism-q123-cn", "axiom-prism-q124-cn"}
    assert not scope.clarification_required
