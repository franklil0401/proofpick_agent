"""Offline, synthetic fact-completion regressions; no model or service calls."""

from types import SimpleNamespace

import pytest

from smartbuy.agent.fact_completion import (
    build_fact_completion,
    from_agent_state,
    missing_fact_fields,
)
from smartbuy.domain import ConstraintSpec, FieldAssessment, EvidenceReference
from smartbuy.identity import ResolvedProductScope


def _reference(product="合成-甲-CN", field="width_mm", value=610, **updates):
    data = {
        "model_id": product, "product_id": product, "field": field, "value": value,
        "evidence_id": "e-甲-width", "source_id": "s-甲", "source_url": "https://example.org/cn/spec",
        "source_type": "official_product", "region": "CN", "configuration_id": "甲-配置",
        "data_version": "synthetic-data-v1", "index_version": "synthetic-index-v1",
    }
    data.update(updates)
    return EvidenceReference(**data)


def _assessment(product="合成-甲-CN", field="width_mm", value=610, status="matched", **updates):
    data = {
        "field": field, "status": status, "actual_value": value, "reason": "真实工具字段结果",
        "evidence": [_reference(product, field, value)],
    }
    data.update(updates)
    return FieldAssessment(**data)


def _identity(**updates):
    data = {
        "region": "CN", "configuration_id": "甲-配置", "data_version": "synthetic-data-v1",
        "index_version": "synthetic-index-v1",
    }
    data.update(updates)
    return data


def _build(assessment, **kwargs):
    return build_fact_completion(
        ["合成-甲-CN"], ["width_mm"], {"合成-甲-CN": [assessment]},
        identities={"合成-甲-CN": _identity()}, **kwargs,
    )


def _scope(ids, *, scope_type="explicit_comparison"):
    return ResolvedProductScope(
        domain_id="synthetic", scope_type=scope_type, product_ids=ids,
        explicit_comparison=scope_type == "explicit_comparison",
        resolution_status="resolved", resolution_reason="synthetic identity fixture",
        data_version="synthetic-data-v1", index_version="synthetic-index-v1",
        regions=["CN"],
    )


def _state(**overrides):
    data = {
        "requirements": SimpleNamespace(required_fields=["width_mm"], excluded_model_ids=[]),
        "constraint_set": SimpleNamespace(active=lambda: [ConstraintSpec(field="region", value="CN")]),
        "product_scope": None, "candidate_pool_rows": {}, "candidate_rows": [],
        "assessments": {}, "kb_hits": [], "verified_fields": {},
    }
    data.update(overrides)
    return SimpleNamespace(**data)


@pytest.mark.parametrize("value", [610, 0, False])
def test_actual_bound_value_is_checked_even_when_zero_or_false(value):
    result = _build(_assessment(value=value))
    assert result["completion_status"] == "complete"
    assert result["checked_count"] == result["required_count"] == 1
    assert result["answer_sufficient"] is True
    assert result["matrix"][0]["status"] == "verified_value"
    assert result["matrix"][0]["actual_value"] == value
    assert result["matrix"][0]["evidence_ids"] == ["e-甲-width"]
    assert missing_fact_fields(result) == {}


def test_not_matched_can_still_be_a_verified_fact_without_recommending_anything():
    result = _build(_assessment(status="not_matched"))
    assert result["answer_sufficient"] is True
    assert result["matrix"][0]["status"] == "verified_value"
    assert "eligible" not in result


@pytest.mark.parametrize("value", [None, "", "   ", [], {}])
def test_known_fact_requires_actual_nonempty_value(value):
    result = _build(_assessment(value=value))
    assert result["matrix"][0]["status"] == "not_checked"
    assert not result["answer_sufficient"]


@pytest.mark.parametrize("update", [
    {"region": "US"}, {"region": ""}, {"configuration_id": "other"}, {"data_version": "v2"},
    {"index_version": "v2"}, {"model_id": "另一型号", "product_id": "另一型号"},
    {"field": "weight_kg"}, {"evidence_id": None}, {"source_id": ""}, {"source_url": ""},
])
def test_mismatched_or_incomplete_reference_cannot_complete_known_fact(update):
    result = _build(_assessment(evidence=[_reference(**update)]))
    assert result["matrix"][0]["status"] == "not_checked"
    assert result["checked_count"] == 0
    assert not result["answer_sufficient"]


def test_legacy_missing_optional_version_does_not_break_bound_field_evidence():
    result = _build(_assessment(evidence=[_reference(
        product_id=None, configuration_id=None, data_version=None, index_version=None,
    )]))
    assert result["answer_sufficient"] is True


@pytest.mark.parametrize("field,value", [
    ("configuration_id", "unattested-config"), ("family_id", "unattested-family"),
    ("domain_id", "unattested-domain"), ("data_version", "unattested-data"),
    ("index_version", "unattested-index"), ("region", "CN"),
])
def test_tool_identity_cannot_attest_metadata_missing_from_catalog(field, value):
    identity = _identity(**{field: None})
    result = build_fact_completion(
        ["合成-甲-CN"], ["width_mm"],
        {"合成-甲-CN": [_assessment(evidence=[_reference(**{field: value})])]},
        identities={"合成-甲-CN": identity},
    )
    cell = result["matrix"][0]
    assert cell["status"] == "not_checked"
    assert cell["reason"] == f"evidence_identity_unbound:{field}"
    assert not result["answer_sufficient"]


def test_known_runtime_version_does_not_certify_unattested_configuration():
    identity = _identity(configuration_id=None)
    result = build_fact_completion(
        ["合成-甲-CN"], ["width_mm"], {"合成-甲-CN": [_assessment()]},
        identities={"合成-甲-CN": identity},
    )
    assert result["matrix"][0]["reason"] == "evidence_identity_unbound:configuration_id"
    assert result["checked_count"] == 0


def test_unknown_is_a_checked_terminal_fact_not_a_missing_tool_call():
    result = _build(_assessment(status="unknown", value=None, evidence=[]))
    assert result["matrix"][0]["status"] == "verified_unknown"
    assert result["completion_status"] == "complete"
    assert result["checked_count"] == 1
    assert not result["answer_sufficient"]
    assert missing_fact_fields(result) == {}


def test_conflict_retains_values_and_both_refs_without_answer_sufficiency():
    result = _build(_assessment(
        status="conflict", value=[610, 620], evidence=[
            _reference(value=610), _reference(value=620, evidence_id="e-乙-width"),
        ],
    ))
    cell = result["matrix"][0]
    assert cell["status"] == "verified_conflict"
    assert cell["actual_value"] == [610, 620]
    assert cell["evidence_ids"] == ["e-甲-width", "e-乙-width"]
    assert result["checked_count"] == 1
    assert not result["answer_sufficient"]
    assert missing_fact_fields(result) == {}


def test_each_product_times_field_cell_must_have_a_real_assessment():
    result = build_fact_completion(
        ["合成-甲-CN", "合成-乙-CN"], ["width_mm", "weight_kg"],
        {"合成-甲-CN": [_assessment(), _assessment(field="unrequested")], "outside": [_assessment()]},
        identities={"合成-甲-CN": _identity(), "合成-乙-CN": _identity()},
    )
    assert result["required_count"] == 4
    assert result["checked_count"] == 1
    assert result["completion_status"] == "partial"
    assert missing_fact_fields(result) == {
        "合成-甲-CN": ["weight_kg"], "合成-乙-CN": ["width_mm", "weight_kg"],
    }


@pytest.mark.parametrize("status", ["tool_failed", "budget_exhausted"])
def test_failed_attempt_without_assessment_does_not_count_as_checked(status):
    result = build_fact_completion(
        ["合成-甲-CN"], ["width_mm"], {}, attempts={"合成-甲-CN": {"width_mm": status}},
    )
    assert result["matrix"][0]["status"] == status
    assert result["checked_count"] == 0
    assert result["completion_status"] == "incomplete"
    assert missing_fact_fields(result) == {"合成-甲-CN": ["width_mm"]}


def test_attempt_success_metadata_and_raw_dict_cannot_fabricate_assessment():
    result = build_fact_completion(
        ["合成-甲-CN"], ["width_mm"],
        {"合成-甲-CN": [{"field": "width_mm", "status": "matched", "actual_value": 610}]},
        attempts={"合成-甲-CN": {"width_mm": "verified_value"}},
    )
    assert result["checked_count"] == 0
    assert result["matrix"][0]["status"] == "not_checked"


def test_terminal_unknown_is_not_overwritten_by_success_metadata_or_later_value():
    result = build_fact_completion(
        ["合成-甲-CN"], ["width_mm"],
        {"合成-甲-CN": [_assessment(status="unknown", value=None, evidence=[]), _assessment()]},
        attempts={"合成-甲-CN": {"width_mm": "verified_value"}},
        identities={"合成-甲-CN": _identity()},
    )
    assert result["matrix"][0]["status"] == "verified_unknown"
    assert not result["answer_sufficient"]


def test_explicit_scope_includes_comparison_side_missing_from_all_tool_returns():
    state = _state(
        product_scope=_scope(["合成-甲-CN", "合成-乙-CN"]),
        candidate_pool_rows={"合成-甲-CN": _identity()},
        assessments={"合成-甲-CN": [_assessment()]},
    )
    result = from_agent_state(state)
    assert result["required_count"] == 2
    assert result["checked_count"] == 1
    assert missing_fact_fields(result) == {"合成-乙-CN": ["width_mm"]}


def test_catalog_scope_uses_observed_union_without_expanding_to_whole_catalog():
    state = _state(
        product_scope=_scope(["合成-甲-CN", "合成-乙-CN", "unobserved"], scope_type="catalog_filter"),
        candidate_pool_rows={"合成-甲-CN": _identity(), "outside": _identity()},
        candidate_rows=[{"model_id": "合成-乙-CN", **_identity()}],
        assessments={"outside": [_assessment(product="outside")]},
    )
    result = from_agent_state(state)
    assert {row["product_id"] for row in result["matrix"]} == {"合成-甲-CN", "合成-乙-CN"}


def test_no_scope_uses_all_observed_products_not_only_last_candidate_rows():
    state = _state(
        candidate_pool_rows={"pool": _identity()}, candidate_rows=[{"model_id": "row"}],
        assessments={"assessment-only": [_assessment(product="assessment-only")]},
    )
    result = from_agent_state(state)
    assert {row["product_id"] for row in result["matrix"]} == {"pool", "row", "assessment-only"}


def test_exclusions_and_scope_apply_even_when_outside_product_has_evidence():
    state = _state(
        product_scope=_scope(["合成-甲-CN", "合成-乙-CN"]),
        requirements=SimpleNamespace(required_fields=["width_mm"], excluded_model_ids=["合成-乙-CN"]),
        assessments={"合成-甲-CN": [_assessment()], "outside": [_assessment(product="outside")]},
    )
    assert [row["product_id"] for row in from_agent_state(state)["matrix"]] == ["合成-甲-CN"]


def test_requested_brand_region_remain_but_identity_markers_and_default_region_do_not():
    state = _state(
        requirements=SimpleNamespace(
            required_fields=["model_id", "model_name", "product_id", "configuration_id", "brand", "region"],
            excluded_model_ids=[],
        ), candidate_rows=[{"model_id": "合成-甲-CN"}],
    )
    result = from_agent_state(state)
    assert [row["field"] for row in result["matrix"]] == ["brand", "region"]
    state.requirements.required_fields = ["width_mm"]
    assert [row["field"] for row in from_agent_state(state)["matrix"]] == ["width_mm"]


def test_kb_hits_verified_field_metadata_and_candidate_values_do_not_close_cells():
    result = from_agent_state(_state(
        candidate_rows=[{"model_id": "合成-甲-CN", "width_mm": 610}],
        kb_hits=[_reference()], verified_fields={"合成-甲-CN": ["width_mm"]},
    ))
    assert result["checked_count"] == 0
    assert not result["answer_sufficient"]


def test_scope_runtime_identity_is_used_even_without_returned_candidate_metadata():
    state = _state(
        product_scope=_scope(["合成-甲-CN"], scope_type="exact_configuration"),
        assessments={"合成-甲-CN": [_assessment(evidence=[_reference(data_version="wrong")])]},
    )
    result = from_agent_state(state)
    assert result["checked_count"] == 0
    assert result["matrix"][0]["identity"]["data_version"] == "synthetic-data-v1"


def test_catalog_fact_identity_wins_over_wrong_region_in_kb_candidate_metadata():
    state = _state(
        candidate_pool_rows={"合成-甲-CN": _identity(region="US")},
        fact_identities={"合成-甲-CN": _identity(region="CN")},
        assessments={"合成-甲-CN": [_assessment(evidence=[_reference(region="US")])]},
    )
    result = from_agent_state(state)
    assert result["matrix"][0]["identity"]["region"] == "CN"
    assert result["checked_count"] == 0
    assert not result["answer_sufficient"]


def test_tool_rows_cannot_fill_unknown_catalog_identity_and_self_attest():
    identity = _identity()
    identity.pop("configuration_id")
    state = _state(
        candidate_pool_rows={"合成-甲-CN": _identity(configuration_id="spoof-config")},
        fact_identities={"合成-甲-CN": identity},
        assessments={"合成-甲-CN": [_assessment(evidence=[_reference(configuration_id="spoof-config")])]},
    )
    result = from_agent_state(state)
    assert "configuration_id" not in result["matrix"][0]["identity"]
    assert result["matrix"][0]["reason"] == "evidence_identity_unbound:configuration_id"
    assert result["checked_count"] == 0
    assert not result["answer_sufficient"]


def test_empty_authoritative_catalog_cannot_fall_back_to_tool_owned_identity():
    state = _state(
        candidate_pool_rows={"合成-甲-CN": _identity()}, fact_identities={},
        assessments={"合成-甲-CN": [_assessment()]},
    )
    result = from_agent_state(state)
    assert result["matrix"][0]["identity"] == {"product_id": "合成-甲-CN"}
    assert result["checked_count"] == 0
    assert not result["answer_sufficient"]


def test_none_authoritative_identity_preserves_standalone_legacy_report_compatibility():
    state = _state(
        candidate_pool_rows={"合成-甲-CN": _identity()}, fact_identities=None,
        assessments={"合成-甲-CN": [_assessment()]},
    )
    assert from_agent_state(state)["answer_sufficient"] is True


def test_legacy_none_identity_can_use_consistent_typed_assessment_identity_without_rows():
    state = _state(fact_identities=None, assessments={"合成-甲-CN": [_assessment()]})
    result = from_agent_state(state)
    assert result["answer_sufficient"] is True
    assert result["matrix"][0]["identity"]["configuration_id"] == "甲-配置"
    state.fact_identities = {}
    assert from_agent_state(state)["checked_count"] == 0


def test_legacy_none_identity_does_not_choose_one_of_conflicting_region_attestations():
    state = _state(fact_identities=None, assessments={"合成-甲-CN": [
        _assessment(), _assessment(evidence=[_reference(region="US")]),
    ]})
    result = from_agent_state(state)
    assert "region" not in result["matrix"][0]["identity"]
    assert result["checked_count"] == 0
    assert not result["answer_sufficient"]


def test_deterministic_scope_fields_cannot_be_deleted_or_expanded_by_llm_requirements():
    scope = _scope(["合成-甲-CN"], scope_type="exact_configuration").model_copy(
        update={"requested_fields": ["width_mm", "weight_kg"]},
    )
    state = _state(
        product_scope=scope,
        requirements=SimpleNamespace(required_fields=["width_mm", "invented"], excluded_model_ids=[]),
    )
    result = from_agent_state(state)
    assert [cell["field"] for cell in result["matrix"]] == ["width_mm", "weight_kg"]


def test_state_attempts_explain_missing_cell_but_do_not_override_real_unknown():
    state = _state(
        candidate_rows=[{"model_id": "合成-甲-CN"}],
        fact_check_attempts={"合成-甲-CN": {"width_mm": "budget_exhausted"}},
    )
    assert from_agent_state(state)["matrix"][0]["status"] == "budget_exhausted"
    state.assessments = {"合成-甲-CN": [_assessment(status="unknown", value=None, evidence=[])]}
    assert from_agent_state(state)["matrix"][0]["status"] == "verified_unknown"


def test_no_obligations_cannot_vacuously_claim_sufficient_answer():
    for ids, fields in [([], ["width_mm"]), (["合成-甲-CN"], [])]:
        result = build_fact_completion(ids, fields, {})
        assert result["required_count"] == 0
        assert result["completion_status"] == "incomplete"
        assert not result["answer_sufficient"]


def test_repeated_build_is_deterministic_and_deduplicates_same_cell_keys():
    kwargs = {"product_ids": ["合成-甲-CN", "合成-甲-CN"], "requested_fields": ["width_mm", "width_mm"],
              "assessments": {"合成-甲-CN": [_assessment()]}}
    assert build_fact_completion(**kwargs) == build_fact_completion(**kwargs)
    assert build_fact_completion(**kwargs)["required_count"] == 1
