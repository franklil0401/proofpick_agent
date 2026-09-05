"""Development regression for exact-source, Pack-governed numeric requirements."""

import pytest

from smartbuy.constraints import ConstraintNormalizer
from smartbuy.contracts.quantities import extract_numeric_requirements
from smartbuy.domain_packs.loader import DEFAULT_MONITOR_PACK, DomainPackLoader, LoadedDomainPack


def _constraints(query):
    return ConstraintNormalizer().build(query, source_turn=1).active(hard_only=True)


@pytest.mark.parametrize("amount, unit", [(610, "毫米"), (610, "mm"), (61, "厘米"), (61, "cm"), (60.95, "厘米")])
def test_width_units_and_decimal_limit_share_canonical_contract(amount, unit):
    query = f"选择合规显示器，刷新率至少144Hz，机身宽度最多{amount}{unit}。"
    actual = {item.field: item for item in _constraints(query)}
    assert set(actual) == {"refresh_rate_hz", "width_mm"}
    width = actual["width_mm"]
    assert width.operator.value == "lte"
    assert width.normalized_value == (float(amount) * 10 if unit in {"厘米", "cm"} else float(amount))
    assert width.unit == "mm"
    assert width.source_text in query
    assert actual["refresh_rate_hz"].source_text in query


def test_width_range_preserves_both_bounds_and_original_text():
    query = "选择宽度600毫米至61厘米、刷新率至少165赫兹的显示器。"
    actual = {item.field: item for item in _constraints(query)}
    assert actual["width_mm"].operator.value == "range"
    assert actual["width_mm"].normalized_value == [600.0, 610.0]
    assert actual["refresh_rate_hz"].normalized_value == 165.0
    assert all(item.source_text in query for item in actual.values())


def test_repeated_width_bounds_are_not_silently_discarded():
    query = "机身宽度至少600毫米，机身宽度最多610毫米，刷新率至少144Hz。"
    actual = _constraints(query)
    width = [item for item in actual if item.field == "width_mm"]
    assert {(item.operator.value, item.normalized_value) for item in width} == {("gte", 600.0), ("lte", 610.0)}


def test_unrecognized_explicit_width_unit_remains_unresolved():
    actual = _constraints("刷新率至少144Hz，机身宽度最多61掌宽。")
    width = [item for item in actual if item.field == "width_mm"]
    assert len(width) == 1
    assert width[0].ambiguous and not width[0].supported
    assert width[0].normalized_value is None


def test_width_cancellation_still_wins_over_inherited_value():
    old = ConstraintNormalizer().build("机身宽度最多610毫米", source_turn=1)
    result = ConstraintNormalizer().build("取消宽度限制，刷新率至少144Hz", source_turn=2, previous=old)
    assert {item.field for item in result.active(hard_only=True)} == {"refresh_rate_hz"}


@pytest.mark.parametrize("query", [
    "刷新率至少144Hz且机身宽度最多610毫米。",
    "刷新率至少144赫兹，机身宽度最多61厘米。",
    "🧪 刷新率至少 144 Hz；机身宽度最多 610 mm。",
    "机身宽度最多610mm以内，刷新率至少144Hz。",
])
def test_shared_contract_preserves_all_constraints_and_raw_spans(query):
    pack = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
    actual = extract_numeric_requirements(query, pack, field_ids={"width_mm", "refresh_rate_hz"})
    assert len(actual) == 2
    assert all(item.resolved for item in actual)
    assert {(item.field, item.operator, item.value) for item in actual} == {
        ("width_mm", "lte", 610.0), ("refresh_rate_hz", "gte", 144.0),
    }
    assert all(query[item.span_start:item.span_end] == item.source_text for item in actual)


@pytest.mark.parametrize("query", [
    "机身宽度最多半米。",
    "机身宽度最多610furlong。",
    "机身宽度窄一点。",
    "机身宽度最多610mm且最少某个下限。",
])
def test_explicit_unresolved_numeric_obligation_survives_inventory(query):
    pack = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
    actual = extract_numeric_requirements(query, pack)
    assert any(item.field == "width_mm" and not item.resolved for item in actual)


def test_contract_uses_fictional_field_and_units_without_product_rules():
    pack = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
    field = pack.fields["width_mm"].model_copy(update={
        "field_id": "clearance_mm", "label": "安装净距", "aliases": ["净距"],
    })
    fictional = LoadedDomainPack(pack.pack.model_copy(update={"fields": [field]}))
    query = "对样机 NOVA-OMEGA-42，要求安装净距最多60.95厘米。"
    actual = extract_numeric_requirements(query, fictional)
    assert len(actual) == 1
    assert actual[0].field == "clearance_mm"
    assert actual[0].value == 609.5
    assert actual[0].source_text in query


def test_fact_field_mentions_and_soft_preferences_do_not_become_hard_inventory():
    pack = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
    assert extract_numeric_requirements("样机的宽度是多少毫米，刷新率是多少赫兹？", pack) == []
    assert extract_numeric_requirements("偏好宽度610mm左右", pack) == []
    assert extract_numeric_requirements("偏好宽度610mm", pack) == []
    approximate = extract_numeric_requirements("宽度最多610mm左右", pack)
    assert len(approximate) == 1 and not approximate[0].resolved


def test_coverage_shares_legacy_implicit_budget_and_width_operators():
    from smartbuy.decision_core.requirements import audit_requirement_coverage

    pack = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
    query = "预算3000元，机身宽度61厘米，刷新率至少144Hz。"
    constraints = ConstraintNormalizer().build(query, source_turn=1)
    coverage = audit_requirement_coverage(query, constraints, pack, purchase=True)
    assert coverage.complete
    assert {(item["field"], item["operator"]) for item in coverage.obligations} == {
        ("price_cny", "lte"), ("width_mm", "lte"), ("refresh_rate_hz", "gte"),
    }


def test_carry_forward_second_bound_and_signed_value_are_not_silently_changed():
    pack = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
    actual = extract_numeric_requirements("机身宽度最多610mm且最少600mm。", pack)
    assert {(item.operator, item.value) for item in actual} == {("lte", 610.0), ("gte", 600.0)}
    signed = extract_numeric_requirements("机身宽度最多-10mm。", pack)
    assert len(signed) == 1 and signed[0].value == -10.0
