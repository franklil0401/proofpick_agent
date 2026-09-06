"""Public report authority comes from user intent, not an upstream task label."""

import pytest

from smartbuy.agent.reporting import build_report
from smartbuy.domain import AgentState, ConstraintSpec, UserRequirements


@pytest.mark.parametrize("query, expected", [
    ("请比较虚构 Alpha 和 Beta 的宽度，不要把比较对象当成推荐商品。", "comparison"),
    ("只核验虚构 Alpha 的宽度，不要帮我筛选或者推荐购买。", "fact"),
])
def test_wrong_purchase_label_cannot_grant_recommendation_authority(query, expected):
    state = AgentState(
        session_id="report-guard", query=query,
        requirements=UserRequirements(summary="incorrect upstream label", task_type="filter",
                                      hard_constraints=[ConstraintSpec(field="width_mm", operator="lte", value=600)],
                                      required_fields=["width_mm"]),
        candidate_pool_rows={"alpha-cn": {"model_id": "alpha-cn", "region": "CN"}},
    )
    report = build_report(state, latency_ms=0, usage={})
    assert report.task_type == expected
    assert report.recommended_model_ids == []
    assert report.hard_constraints == []
    assert all(not item.eligible for item in report.candidates)
    assert report.usage["intent_guard"] == "original_input_overrides_purchase_label"
    assert state.requirements.task_type == "filter", "The guard must not mutate prior tool/Checker records"


def test_ask_first_cannot_be_reported_as_all_catalog_eligible():
    state = AgentState(session_id="report-guard", query="先向我确认重量上限，之后再推荐。")
    report = build_report(state, latency_ms=0, usage={})
    assert report.clarification_state.value == "pending"
    assert report.pending_questions
    assert report.abstained and not report.recommended_model_ids
