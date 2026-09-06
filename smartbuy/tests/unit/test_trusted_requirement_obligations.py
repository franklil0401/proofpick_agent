"""Raw-input obligations, not catalog- or independent-case-specific rules."""

import pytest

from smartbuy.constraints import ConstraintNormalizer, ConstraintSet
from smartbuy.decision_core.requirements import audit_requirement_coverage
from smartbuy.domain_packs import DomainPackRegistry


@pytest.mark.parametrize("query", [
    "筛选分辨率必须为5120x2880，供电至少90W的显示器。",
    "分辨率必须为3840x2160；筛选刷新率至少100Hz的显示器。",
    "帮我筛选：必须为4K分辨率，而且刷新率至少100Hz。",
])
def test_resolved_subject_before_or_after_must_is_not_lost(query):
    pack = DomainPackRegistry().load("monitor")
    actual = ConstraintNormalizer().build(query, source_turn=1)
    assert audit_requirement_coverage(query, actual, pack, purchase=True).complete


@pytest.mark.parametrize("query", [
    "筛选分辨率必须为5120x2880的显示器。",
    "筛选显示器，必须支持光子接口。",
    "筛选显示器，刷新率至少144Hz，宽度不能太大。",
    "筛选显示器，宽度最多610毫米，但我先确认上限才能开始。请先问我。",
])
def test_unresolved_or_explicit_confirmation_cannot_be_an_empty_complete_set(query):
    coverage = audit_requirement_coverage(query, ConstraintSet(), DomainPackRegistry().load("monitor"), purchase=True)
    assert not coverage.complete
    assert any(not item["resolved"] for item in coverage.obligations)


def test_fact_fields_are_not_purchase_obligations():
    coverage = audit_requirement_coverage(
        "只核验X710的分辨率和是否支持光子接口，不做购买推荐。",
        ConstraintSet(), DomainPackRegistry().load("monitor"), purchase=False,
    )
    assert coverage.complete and not coverage.obligations


@pytest.mark.parametrize("memory_source", ["session", "preference"])
def test_old_value_cannot_resolve_a_new_undefined_requirement(memory_source):
    normalizer = ConstraintNormalizer()
    old = normalizer.build("分辨率4K", source_turn=1)
    query = "刷新率至少144Hz，分辨率必须满足新的要求。"
    constraints = normalizer.build(
        query, source_turn=2, previous=old if memory_source == "session" else None,
        preferences={"resolution": "3840x2160"} if memory_source == "preference" else {},
    )
    coverage = audit_requirement_coverage(query, constraints, DomainPackRegistry().load("monitor"), purchase=True)
    assert not coverage.complete
    assert any(item["field"] == "resolution" and not item["resolved"] for item in coverage.obligations)
