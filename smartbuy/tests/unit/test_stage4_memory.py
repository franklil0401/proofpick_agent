"""Session inheritance and explicit preference lifecycle tests."""

from __future__ import annotations

import pytest

from smartbuy.domain import AgentState, ConstraintSpec, UserRequirements
from smartbuy.memory import LongTermPreferenceStore, SessionMemoryStore


def test_same_session_inherits_and_overwrites_constraints():
    store = SessionMemoryStore()
    first = UserRequirements(
        summary="27 英寸，预算 3000",
        hard_constraints=[
            ConstraintSpec(field="display_size_inch", value=27),
            ConstraintSpec(field="price_cny", operator="lte", value=3000),
        ],
    )
    store.save(AgentState(session_id="s1", query="first", requirements=first, candidate_rows=[{"model_id": "a"}]))
    current = UserRequirements(
        summary="再便宜一点",
        hard_constraints=[ConstraintSpec(field="price_cny", operator="lte", value=2500)],
    )
    merged = store.merge_requirements(store.get("s1").requirements, current)
    assert {item.field: item.value for item in merged.hard_constraints} == {
        "display_size_inch": 27,
        "price_cny": 2500,
    }
    assert store.get("s1").candidate_rows == [{"model_id": "a"}]


def test_long_term_preferences_require_confirmation_and_support_lifecycle(tmp_path):
    store = LongTermPreferenceStore(tmp_path / "preferences.json")
    with pytest.raises(ValueError):
        store.upsert("u1", {"display_size_inch": 27}, explicitly_confirmed=False)
    saved = store.upsert(
        "u1",
        {"display_size_inch": 27, "excluded_brands": ["BrandX"], "primary_use": "办公"},
        explicitly_confirmed=True,
    )
    assert saved["preferences"]["display_size_inch"] == 27
    assert store.recall("u1", requested=False) == {}
    assert store.recall("u1", requested=True)["primary_use"] == "办公"
    store.upsert("u1", {"display_size_inch": 32}, explicitly_confirmed=True)
    assert store.view("u1")["preferences"]["display_size_inch"] == 32
    store.delete("u1", ["excluded_brands"])
    assert "excluded_brands" not in store.view("u1")["preferences"]
    store.set_enabled("u1", False)
    assert store.recall("u1", requested=True) == {}


def test_dynamic_product_state_cannot_enter_long_term_memory(tmp_path):
    store = LongTermPreferenceStore(tmp_path / "preferences.json")
    with pytest.raises(ValueError):
        store.upsert("u1", {"price_cny": 1999}, explicitly_confirmed=True)
    with pytest.raises(ValueError):
        store.upsert("u1", {"stock_status": "available"}, explicitly_confirmed=True)
