"""Synthetic development regressions for bounded and optional requirements."""

import pytest

from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.constraints import ConstraintNormalizer
from smartbuy.contracts.modality import optional_requirement_spans
from smartbuy.contracts.quantities import extract_numeric_requirements
from smartbuy.domain_packs.loader import DEFAULT_MONITOR_PACK, DomainPackLoader


def _hard(query, previous=None):
    return ConstraintNormalizer().build(query, source_turn=2 if previous else 1, previous=previous).active(hard_only=True)


@pytest.mark.parametrize("query,operator,value", [
    ("最多27英寸", "lte", 27), ("尺寸不超过 27 英寸", "lte", 27),
    ("至多二十七英寸", "lte", 27), ("27英寸以下", "lte", 27),
    ("至少 24.5 英寸", "gte", 24.5), ("27英寸以上", "gte", 27),
    ("24到27英寸", "range", [24, 27]), ("27英寸", "eq", 27),
])
def test_size_bounds_use_shared_field_unit_contract(query, operator, value):
    result = [item for item in _hard(query) if item.field == "display_size_inch"]
    assert len(result) == 1
    assert result[0].operator.value == operator
    assert result[0].normalized_value == value
    assert result[0].unit == "inch"
    assert result[0].source_text in query


@pytest.mark.asyncio
@pytest.mark.parametrize("query,operator,value", [
    ("最多27英寸", "lte", 27), ("尺寸不超过 27 英寸", "lte", 27),
    ("至多二十七英寸", "lte", 27), ("27英寸以下", "lte", 27),
    ("至少 24.5 英寸", "gte", 24.5), ("27英寸以上", "gte", 27),
    ("24到27英寸", "range", [24, 27]), ("27英寸", "eq", 27),
])
async def test_proposal_size_bounds_reuse_same_numeric_contract(query, operator, value):
    engine = NaturalConstraintEngine(DomainPackLoader().load(DEFAULT_MONITOR_PACK))
    result = await engine.resolve(query, source_turn=1)
    size = [item for item in result.constraint_set.active(hard_only=True) if item.field == "display_size_inch"]
    assert len(size) == 1
    assert (size[0].operator.value, size[0].normalized_value, size[0].unit) == (operator, value, "inch")
    assert result.provider_calls == 0


@pytest.mark.parametrize("query", [
    "没有 USB-C 也可以", "USB-C 可有可无", "USB-C 不强求", "USB-C 有没有都行",
    "无 Type-C 也行", "Type C 可以没有",
])
def test_optional_interface_is_neither_positive_nor_negative_hard_constraint(query):
    assert not [item for item in _hard(query) if item.field == "has_usb_c"]


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["没有 USB-C 也可以", "USB-C 不强求", "USB-C 有没有都行"])
async def test_optional_interface_cancels_previous_engine_hard_requirement(query):
    engine = NaturalConstraintEngine(DomainPackLoader().load(DEFAULT_MONITOR_PACK))
    first = await engine.resolve("需要 USB-C 接口", source_turn=1)
    assert any(item.field == "has_usb_c" for item in first.constraint_set.active(hard_only=True))
    result = await engine.resolve(query, source_turn=2, previous=first.constraint_set)
    assert not [item for item in result.constraint_set.active(hard_only=True) if item.field == "has_usb_c"]
    assert any(diff.field == "has_usb_c" and diff.action.value == "cancel" for diff in result.diff)
    assert result.provider_calls == 0


def test_optional_interface_cancels_legacy_memory_without_cancelling_other_requirements():
    old = ConstraintNormalizer().build("需要 USB-C 接口，刷新率至少144Hz", source_turn=1)
    result = _hard("没有USB-C也可以，但刷新率至少165Hz，尺寸最多27英寸", previous=old)
    values = {item.field: (item.operator.value, item.normalized_value) for item in result}
    assert values == {"refresh_rate_hz": ("gte", 165), "display_size_inch": ("lte", 27)}


@pytest.mark.parametrize("query", ["需要 USB-C 视频输入", "支持 USB-C 视频", "需要 Type-C 传视频"])
def test_video_requirement_does_not_invent_an_independent_interface_hard_constraint(query):
    constraints = _hard(query)
    assert {item.field: item.normalized_value for item in constraints} == {"usb_c_video": True}


def test_separate_explicit_interface_requirement_remains_hard():
    constraints = _hard("需要USB-C接口，而且需要USB-C视频输入")
    assert {item.field: item.normalized_value for item in constraints} == {"has_usb_c": True, "usb_c_video": True}


@pytest.mark.parametrize("query,value", [
    ("必须有 USB-C 接口", True), ("不要 USB-C 接口", False),
    ("不要不带 USB-C 的", True),
])
def test_optional_fix_does_not_reverse_clear_interface_requirement(query, value):
    values = [item.normalized_value for item in _hard(query) if item.field == "has_usb_c"]
    assert values == [value]


def test_quantity_inventory_and_normalizer_agree_on_multiple_bounded_fields():
    query = "尺寸最多27英寸，机身宽度最多61厘米，刷新率至少144Hz"
    pack = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
    inventory = extract_numeric_requirements(
        query, pack, field_ids={"display_size_inch", "width_mm", "refresh_rate_hz"},
        implicit_operators=ConstraintNormalizer.IMPLICIT_NUMERIC_OPERATORS,
        implicit_unit_fields={"display_size_inch", "refresh_rate_hz"},
    )
    expected = {("display_size_inch", "lte", 27), ("width_mm", "lte", 610), ("refresh_rate_hz", "gte", 144)}
    assert {(item.field, item.operator, item.value) for item in inventory} == expected
    assert {(item.field, item.operator.value, item.normalized_value) for item in _hard(query)} == expected
    assert all(query[item.span_start:item.span_end] == item.source_text for item in inventory)


@pytest.mark.parametrize("query,expected", [
    ("没有USB-C也可以，但必须有USB-C接口", [True]),
    ("必须有USB-C接口，但没有USB-C也可以", []),
])
def test_later_explicit_interface_modality_overrides_earlier_requirement(query, expected):
    assert [item.normalized_value for item in _hard(query) if item.field == "has_usb_c"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("query,expected", [
    ("没有USB-C也可以，但必须有USB-C接口", [True]),
    ("必须有USB-C接口，但没有USB-C也可以", []),
])
async def test_engine_later_explicit_interface_modality_overrides_earlier_requirement(query, expected):
    result = await NaturalConstraintEngine(DomainPackLoader().load(DEFAULT_MONITOR_PACK)).resolve(query, source_turn=1)
    assert [item.normalized_value for item in result.constraint_set.active(hard_only=True) if item.field == "has_usb_c"] == expected


@pytest.mark.parametrize("query", ["没有USB-C视频也可以", "USB-C 视频输入不强求"])
def test_optional_video_capability_is_not_activated_as_hard_field(query):
    assert not [item for item in _hard(query) if item.field in {"usb_c_video", "has_usb_c"}]


def test_negative_video_does_not_infer_positive_interface_preference():
    result = ConstraintNormalizer().build("不要USB-C视频输入", source_turn=1)
    assert not [item for item in result.active() if item.field == "has_usb_c"]
    assert [(item.field, item.normalized_value) for item in result.active(hard_only=True)] == [("usb_c_video", False)]


def test_shared_inch_unit_with_explicit_width_never_creates_display_size():
    result = _hard("机身宽度最多24 inch")
    assert [(item.field, item.operator.value, item.normalized_value) for item in result] == [("width_mm", "lte", 609.6)]


@pytest.mark.parametrize("query", ["尺寸小于27英寸", "尺寸最多27掌宽", "尺寸28到24英寸"])
def test_unresolved_size_bounds_are_not_silently_accepted_as_exact_size(query):
    size = [item for item in _hard(query) if item.field == "display_size_inch"]
    assert size
    assert all(not item.supported and item.ambiguous and item.normalized_value is None for item in size)


def test_optional_span_is_alias_driven_and_does_not_cross_other_field_clause():
    query = "没有光子接口也可以，但同步功能必须具备；光子接口不强求。"
    spans = optional_requirement_spans(query, ["光子接口"])
    assert [query[start:end] for start, end in spans] == ["没有光子接口也可以", "光子接口不强求"]
    assert optional_requirement_spans(query, ["同步功能"]) == []


def test_optional_video_does_not_cancel_separate_explicit_interface_requirement():
    constraints = _hard("需要USB-C接口，但USB-C视频不强求，刷新率至少144Hz")
    assert {item.field: item.normalized_value for item in constraints} == {"has_usb_c": True, "refresh_rate_hz": 144}


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["没有USB-C视频也可以", "USB-C 视频输入不强求"])
async def test_optional_video_engine_current_and_inherited_prerequisite_are_not_hard(query):
    engine = NaturalConstraintEngine(DomainPackLoader().load(DEFAULT_MONITOR_PACK))
    current = await engine.resolve(query, source_turn=1)
    assert not current.constraint_set.active(hard_only=True)
    old = await engine.resolve("需要USB-C视频输入", source_turn=1)
    assert {item.field for item in old.constraint_set.active(hard_only=True)} == {"has_usb_c", "usb_c_video"}
    updated = await engine.resolve(query, source_turn=2, previous=old.constraint_set)
    assert not updated.constraint_set.active(hard_only=True)
    assert updated.provider_calls == 0


@pytest.mark.asyncio
async def test_optional_video_engine_preserves_independent_inherited_interface():
    engine = NaturalConstraintEngine(DomainPackLoader().load(DEFAULT_MONITOR_PACK))
    old = await engine.resolve("需要USB-C接口", source_turn=1)
    updated = await engine.resolve("USB-C视频不强求", source_turn=2, previous=old.constraint_set)
    assert {item.field: item.normalized_value for item in updated.constraint_set.active(hard_only=True)} == {"has_usb_c": True}


@pytest.mark.asyncio
async def test_later_explicit_video_requirement_overrides_earlier_optional_capability():
    query = "USB-C视频不强求，但现在必须支持USB-C视频输入"
    expected = _hard(query)
    assert {item.field: item.normalized_value for item in expected} == {"usb_c_video": True}
    engine = NaturalConstraintEngine(DomainPackLoader().load(DEFAULT_MONITOR_PACK))
    result = await engine.resolve(query, source_turn=1)
    assert any(item.field == "usb_c_video" and item.normalized_value is True for item in result.constraint_set.active(hard_only=True))
