"""Deterministic metamorphic coverage for the category-neutral decision core."""

from __future__ import annotations

import itertools
from copy import deepcopy
from pathlib import Path

import pytest

from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.decision_core.canonical import CanonicalValueNormalizer
from smartbuy.decision_core.delta import ConstraintDeltaAction, ConstraintDeltaResolver
from smartbuy.decision_core.intent import QueryUnderstandingEngine
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.domain_packs.evaluator import DomainConstraintEvaluator
from smartbuy.identity import (
    ProductIdentityResolver,
    ProductScopeType,
    QueryIntent,
    evidence_identity_status,
)
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.tools.domain import DomainReadonlyRepository


ROOT = Path(__file__).resolve().parents[3]
DOMAIN_PACK = ROOT / "smartbuy" / "domain_packs" / "laptop"
PRODUCT_PACK = ROOT / "smartbuy" / "product_packs" / "examples" / "laptop-v1" / "pack.json"


@pytest.fixture(scope="module")
def runtime(tmp_path_factory: pytest.TempPathFactory):
    pack = DomainPackLoader().load(DOMAIN_PACK)
    manager = DomainProductPackManager(
        tmp_path_factory.mktemp("decision-core") / "data",
        domain_pack_path=DOMAIN_PACK,
    )
    snapshot = manager.publish(manager.stage(PRODUCT_PACK).data_version)
    products = DomainReadonlyRepository(snapshot, pack).load()
    resolver = ProductIdentityResolver(
        domain_id=pack.domain_id,
        data_version=snapshot.data_version,
    )
    return pack, products, resolver


def _fullwidth(value: str) -> str:
    return "".join(chr(ord(char) + 0xFEE0) if 0x21 <= ord(char) <= 0x7E else char for char in value)


def test_at_least_500_generated_transformations_preserve_invariants(runtime) -> None:
    pack, products, resolver = runtime
    configurations = sorted(
        (str(item["attributes"]["configuration_id"]), product_id)
        for product_id, item in products.items()
    )
    checked = 0

    wrappers = (
        "核验 {value} 的规格",
        "请查 {value}。",
        "SKU：{value}",
        "  核验  {value}  ",
    )
    for configuration, product_id in configurations:
        for transformed in (
            configuration,
            configuration.lower(),
            configuration.upper(),
            _fullwidth(configuration),
        ):
            for wrapper in wrappers:
                scope = resolver.resolve(wrapper.format(value=transformed), products)
                assert scope.scope_type == ProductScopeType.EXACT_CONFIGURATION
                assert scope.product_ids == [product_id]
                checked += 1

    for (left, left_id), (right, right_id) in itertools.combinations(configurations, 2):
        scope = resolver.resolve(f"比较 {left} 和 {right}", products)
        assert scope.scope_type == ProductScopeType.EXPLICIT_COMPARISON
        assert set(scope.product_ids) == {left_id, right_id}
        checked += 1

    for left, left_id in configurations:
        for right, right_id in configurations:
            if left_id == right_id:
                continue
            scope = resolver.resolve(f"只看 {left}，不要 {right}", products)
            assert scope.product_ids == [left_id]
            assert right_id not in scope.product_ids
            assert set(scope.product_ids) <= {left_id}
            checked += 1

    storage = pack.fields["storage_gb"]
    weight = pack.fields["weight_kg"]
    memory = pack.fields["memory_gb"]
    for value in range(1, 41):
        assert CanonicalValueNormalizer.equivalent(
            storage, value, value * 1024, left_unit="TB", right_unit="GB"
        )
        assert CanonicalValueNormalizer.equivalent(
            weight, value / 10, value * 100, left_unit="kg", right_unit="g"
        )
        assert CanonicalValueNormalizer.equivalent(memory, value, float(value))
        checked += 3

    evaluator = DomainConstraintEvaluator(pack)
    base_constraints = [
        {"field": "memory_gb", "operator": "gte", "value": 16, "unit": "GB"},
        {"field": "storage_gb", "operator": "gte", "value": 512, "unit": "GB"},
        {"field": "weight_kg", "operator": "lte", "value": 3, "unit": "kg"},
    ]
    for product in products.values():
        evidence_fields = {item["field_id"] for item in product["evidence"]}
        baseline = evaluator.evaluate(
            product["attributes"], base_constraints, evidenced_fields=evidence_fields
        )
        for permutation in itertools.permutations(base_constraints):
            result = evaluator.evaluate(
                product["attributes"], permutation, evidenced_fields=evidence_fields
            )
            assert result[1] == baseline[1]
            assert {item.field_id: item.state for item in result[0]} == {
                item.field_id: item.state for item in baseline[0]
            }
            checked += 1

    for product in products.values():
        for row in product["evidence"][:10]:
            valid, reason = evidence_identity_status(product, row, field=row["field_id"])
            assert valid and reason == "identity_bound"
            wrong_region = deepcopy(row)
            wrong_region["region"] = "__other_region__"
            assert evidence_identity_status(
                product, wrong_region, field=row["field_id"]
            ) == (False, "region_mismatch_only")
            wrong_configuration = deepcopy(row)
            wrong_configuration["variant_key"] = "__other_configuration__"
            assert evidence_identity_status(
                product, wrong_configuration, field=row["field_id"]
            ) == (False, "identity_mismatch")
            checked += 3

    assert checked >= 500


@pytest.mark.asyncio
async def test_fact_filter_comparison_and_constraint_delta_are_separate(runtime) -> None:
    pack, products, resolver = runtime
    configurations = sorted(
        str(item["attributes"]["configuration_id"]) for item in products.values()
    )
    left, right = configurations[:2]
    understanding = QueryUnderstandingEngine(pack)

    fact_query = f"{left} 的内存是多少"
    fact_scope = resolver.resolve(fact_query, products)
    fact = understanding.analyze(fact_query, fact_scope)
    assert fact.intent == QueryIntent.EXACT_FACT_VERIFICATION
    assert fact.requested_fields == ["memory_gb"]

    filter_query = "想要内存至少 32GB 的电脑"
    filter_scope = resolver.resolve(filter_query, products)
    filtered = understanding.analyze(filter_query, filter_scope)
    assert filtered.intent == QueryIntent.RECOMMENDATION_FILTER
    resolution = await NaturalConstraintEngine(pack).resolve(filter_query, source_turn=1)
    assert {
        item.field
        for item in resolution.constraint_set.active()
        if item.provenance.value == "current_input"
    } == {"memory_gb"}

    comparison_query = f"比较 {left} 和 {right} 的内存与重量"
    comparison_scope = resolver.resolve(comparison_query, products)
    comparison = understanding.analyze(comparison_query, comparison_scope)
    assert comparison.intent == QueryIntent.EXPLICIT_COMPARISON
    assert set(comparison.requested_fields) == {"memory_gb", "weight_kg"}
    assert len(comparison_scope.product_ids) == 2

    updated = await NaturalConstraintEngine(pack).resolve(
        "固态原先想要 2T，改成最低 1T，以后一个要求为准。",
        source_turn=2,
    )
    active = [
        item for item in updated.constraint_set.active()
        if item.provenance.value == "current_input"
    ]
    assert len(active) == 1
    assert active[0].field == "storage_gb"
    assert active[0].normalized_value == 1024
    assert active[0].operator.value == "gte"
    deltas = ConstraintDeltaResolver.from_resolution(updated)
    assert deltas[-1].action == ConstraintDeltaAction.REPLACE


@pytest.mark.asyncio
async def test_unique_pack_unit_can_bind_a_numeric_constraint_without_field_label(runtime) -> None:
    pack, _products, _resolver = runtime
    resolution = await NaturalConstraintEngine(pack).resolve(
        "从目录里找机身不重于 1200g 的配置",
        source_turn=1,
    )
    active = [
        item for item in resolution.constraint_set.active()
        if item.provenance.value == "current_input"
    ]
    assert len(active) == 1
    assert active[0].field == "weight_kg"
    assert active[0].operator.value == "lte"
    assert active[0].normalized_value == 1.2


def test_scope_language_does_not_become_requested_upgradeability(runtime) -> None:
    pack, products, resolver = runtime
    configuration = "21YW0042US"
    query = f"{configuration} 属于哪个地区、内存多大？不要扩展到其他配置。"
    scope = resolver.resolve(query, products)
    understanding = QueryUnderstandingEngine(pack).analyze(query, scope)
    assert understanding.intent == QueryIntent.EXACT_FACT_VERIFICATION
    assert set(understanding.requested_fields) == {"region", "memory_gb"}
