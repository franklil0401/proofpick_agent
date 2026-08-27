"""ConstraintSet normalization, provenance precedence and ambiguity gates."""

from __future__ import annotations

from smartbuy.constraints import (
    ConstraintNormalizer,
    ConstraintOperator,
    ConstraintProvenance,
    ConstraintStrength,
)


def active_by_field(constraint_set, field):
    return [item for item in constraint_set.active() if item.field == field]


def test_aliases_units_negation_and_inclusive_operators():
    constraints = ConstraintNormalizer().build(
        "预算不超过 2500 元，27 英寸，至少 4K，不低于 120Hz，不要 OLED，"
        "需要 USB-C 视频和至少 90W 供电，机身宽度最多 61.2cm，并且支架可升降",
        source_turn=2,
    )
    values = {(item.field, item.operator.value): item.normalized_value for item in constraints.active()}
    assert values[("price_cny", "lte")] == 2500.0
    assert values[("display_size_inch", "eq")] == 27.0
    assert values[("resolution", "gte")] == "3840x2160"
    assert values[("refresh_rate_hz", "gte")] == 120.0
    assert values[("is_oled", "eq")] is False
    assert values[("has_usb_c", "eq")] is True
    assert values[("usb_c_video", "eq")] is True
    assert values[("usb_c_power_delivery_w", "gte")] == 90.0
    assert values[("width_mm", "lte")] == 612.0
    assert values[("stand_adjustment", "contains_all")] == ["高度"]
    assert all(item.provenance == ConstraintProvenance.CURRENT_INPUT for item in constraints.active(hard_only=True))


def test_resolution_aliases_and_vague_size_is_soft_and_ambiguous():
    constraints = ConstraintNormalizer().build("27寸左右，偏好 QHD / WQHD", source_turn=1)
    size = active_by_field(constraints, "display_size_inch")[0]
    resolution = active_by_field(constraints, "resolution")[0]
    assert size.hard_or_soft == ConstraintStrength.SOFT
    assert size.ambiguous is True
    assert resolution.normalized_value == "2560x1440"


def test_current_input_overrides_long_term_and_cancellation_disables_memory():
    normalizer = ConstraintNormalizer()
    current = normalizer.build(
        "这次我要 OLED，预算 3000 元",
        source_turn=3,
        preferences={"exclude_oled": True, "budget_max_cny": 2500},
    )
    oled = active_by_field(current, "is_oled")
    budget = active_by_field(current, "price_cny")
    assert [(item.normalized_value, item.provenance) for item in oled] == [
        (True, ConstraintProvenance.CURRENT_INPUT)
    ]
    assert [(item.normalized_value, item.provenance) for item in budget] == [
        (3000.0, ConstraintProvenance.CURRENT_INPUT)
    ]

    cancelled = normalizer.build(
        "品牌不限，预算不限",
        source_turn=4,
        preferences={"excluded_brands": ["Dell"], "budget_max_cny": 2500},
    )
    assert not active_by_field(cancelled, "brand")
    assert not active_by_field(cancelled, "price_cny")
    assert set(cancelled.cancelled_fields) == {"brand", "price_cny"}


def test_session_beats_long_term_but_current_beats_session():
    normalizer = ConstraintNormalizer()
    first = normalizer.build("预算 2800 元", source_turn=1)
    second = normalizer.build(
        "继续看看",
        source_turn=2,
        previous=first,
        preferences={"budget_max_cny": 2300},
    )
    active = active_by_field(second, "price_cny")
    assert [(item.normalized_value, item.provenance) for item in active] == [
        (2800.0, ConstraintProvenance.SESSION_CONFIRMED)
    ]
    third = normalizer.build("这次预算 2600 元", source_turn=3, previous=second)
    assert [(item.normalized_value, item.provenance) for item in active_by_field(third, "price_cny")] == [
        (2600.0, ConstraintProvenance.CURRENT_INPUT)
    ]


def test_model_cannot_invent_budget_brand_or_promote_soft_constraint():
    constraints = ConstraintNormalizer().build(
        "27寸左右，主要用于编程",
        source_turn=1,
        model_proposals=[
            {"field": "price_cny", "operator": "lte", "value": 2000},
            {"field": "brand", "operator": "not_in", "value": ["Dell"]},
            {"field": "display_size_inch", "operator": "eq", "value": 27},
        ],
    )
    assert not active_by_field(constraints, "price_cny")
    assert not active_by_field(constraints, "brand")
    size = active_by_field(constraints, "display_size_inch")[0]
    assert size.hard_or_soft == ConstraintStrength.SOFT
    assert set(constraints.rejected_model_constraints) == {
        "price_cny", "brand", "display_size_inch"
    }


def test_explicit_unsupported_constraint_is_not_silently_dropped():
    constraints = ConstraintNormalizer().build("必须有人脸识别摄像头", source_turn=1)
    active = [item for item in constraints.active(hard_only=True) if item.field != "region"]
    assert {item.field for item in active} == {"camera", "face_recognition"}
    assert all(item.supported is False for item in active)
    assert all(item.operator == ConstraintOperator.EQ for item in active)


def test_budget_change_and_stage6_unsupported_guarantee_are_normalized():
    normalizer = ConstraintNormalizer()
    first = normalizer.build("预算 3000 元", source_turn=1)
    changed = normalizer.build("预算改成 2500 元", source_turn=2, previous=first)
    budget = active_by_field(changed, "price_cny")
    assert [(item.normalized_value, item.provenance) for item in budget] == [
        (2500.0, ConstraintProvenance.CURRENT_INPUT)
    ]

    unsupported = normalizer.build("必须有终身零坏点保证", source_turn=1)
    fields = {item.field: item for item in unsupported.active(hard_only=True)}
    assert fields["lifetime_zero_dead_pixel_guarantee"].supported is False
