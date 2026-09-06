"""Default Portfolio regressions for intent and zero-cost clarification.

Fictional products and developer-authored wording only. Real SQLite, Evidence
Check and Checker run behind the public API; the LLM and KB are offline fakes.
These are development regressions, not independent evaluation or holdout tasks.
"""

from __future__ import annotations

import pytest

from smartbuy.tests.integration import test_v2_9j_portfolio_contracts as shared_fixture
from smartbuy.tests.integration.test_fact_completion_portfolio import _script
from smartbuy.tests.integration.test_v2_9j_portfolio_contracts import MODEL_IDS, scripted_filter


@pytest.fixture(name="synthetic_database")
def _synthetic_database(tmp_path):
    return shared_fixture.synthetic_database.__wrapped__(tmp_path)


@pytest.fixture(name="portfolio_client")
def _portfolio_client(monkeypatch, tmp_path, synthetic_database):
    yield from shared_fixture.portfolio_client.__wrapped__(monkeypatch, tmp_path, synthetic_database)


def _request(client, query):
    response = client.post("/api/smartbuy/portfolio/run", json={
        "domain_id": "monitor", "mode": "trusted", "query": query,
    })
    assert response.status_code == 200
    return response.json()


def _assert_zero_cost_pause(payload, provider, sql, evidence):
    report = payload["report"]
    assert report["clarification_state"] == "pending"
    assert report["pending_questions"]
    assert report["abstained"] is True
    assert report["recommended_model_ids"] == []
    assert report["tool_call_count"] == 0
    assert provider.calls == 0, "Explicit clarification must precede even the first planning-model call"
    assert sql.received == []
    assert evidence.received == []
    assert not report["tools_used"]
    assert not any(item.get("eligible") for item in report["candidates"])


@pytest.mark.parametrize("query", [
    "先问我显示器机身宽度上限是多少，等我确认后再筛选。刷新率至少144Hz，现在不要推荐任何商品。",
    "在我回答可接受的宽度之前，不要筛选或推荐；请先问清宽度，刷新率最低144Hz。",
    "即使当前已有商品资料，也请先向我确认桌面允许的机身宽度，再找刷新率至少144Hz的显示器。",
    "显示器宽度最多610毫米，但先问我是否确认这个上限，收到确认后才能筛选144Hz以上的产品。",
])
def test_explicit_ask_before_filter_is_a_zero_cost_pause(portfolio_client, query):
    client, provider, sql, evidence = portfolio_client(scripted_filter())
    _assert_zero_cost_pause(_request(client, query), provider, sql, evidence)


@pytest.mark.parametrize("query", [
    "显示器刷新率至少144Hz，机身宽度窄一点，再筛选。",
    "预算3000元以内，机身重量轻一点，帮我筛选显示器。",
    "供电至少90W，屏幕尺寸大一点，找显示器。",
    "从已收录显示器中挑选刷新率至少144Hz的型号，而且机身不能太宽。",
    "给我找 Acme Orbit X410 的同类显示器，机身重量不要太重。",
])
def test_unresolved_qualitative_field_is_not_hidden_by_other_numbers(portfolio_client, query):
    client, provider, sql, evidence = portfolio_client(scripted_filter())
    _assert_zero_cost_pause(_request(client, query), provider, sql, evidence)


@pytest.mark.parametrize("instruction", [
    "只比较两者的机身宽度和刷新率。在当前这个阶段，我不希望你参考这些数字、品牌喜好或默认条件向我推荐任何型号。",
    "仅比较宽度和刷新率，并在比较表中说明是否达到144Hz；这不是购买条件，请不要根据表格、库存观察或者单次分数帮我挑选或推荐购买对象。",
    "请对比机身宽度和刷新率。不是让你把数据整理完成以后再替我选购或者推荐；只需要事实对照。",
])
def test_long_distance_no_recommendation_keeps_comparison_fields_out_of_checker(
    portfolio_client, instruction,
):
    models = MODEL_IDS[:2]
    client, provider, _, _ = portfolio_client(_script(models=models, comparison=True, sql=True, evidence=True))
    payload = _request(client, f"{models[0]} 与 {models[1]}。{instruction}")
    report = payload["report"]
    assert report["clarification_state"] != "pending"
    assert report["task_type"] == "comparison"
    assert report["recommended_model_ids"] == []
    assert not any(item.get("eligible") or item.get("recommendation_reason") for item in report["candidates"])
    active = [item for item in report["constraint_set"]["constraints"]
              if item["active"] and item["hard_or_soft"] == "hard"]
    assert not active, "A comparative threshold or requested field is not a buying condition"
    assert {item["model_id"] for item in report["candidates"]} == set(models)
    assert {(item["model_id"], field["field"]) for item in report["candidates"] for field in item["fields"]} >= {
        (model_id, field) for model_id in models for field in ("width_mm", "refresh_rate_hz")
    }
    assert provider.calls > 0


def test_old_enabled_memory_cannot_resolve_a_new_unspecified_hard_requirement(portfolio_client):
    client, provider, sql, evidence = portfolio_client(scripted_filter())
    shared_fixture.api._agent.preference_memory.upsert(
        "offline-memory-contract", {"resolution": "3840x2160"}, explicitly_confirmed=True,
    )
    response = client.post(
        "/api/smartbuy/portfolio/run",
        headers={"X-ProofPick-Identity": "offline-memory-contract"},
        json={
            "domain_id": "monitor", "mode": "trusted",
            "query": "刷新率至少144Hz，分辨率必须满足新的要求。",
            "user_id": "offline-memory-contract", "use_long_term_memory": True,
        },
    )
    assert response.status_code == 200
    _assert_zero_cost_pause(response.json(), provider, sql, evidence)
    assert shared_fixture.api._agent.preference_memory.view("offline-memory-contract")["preferences"] == {
        "resolution": "3840x2160",
    }, "Clarification must neither silently adopt nor erase the confirmed historical preference"


def test_no_hard_constraints_without_ask_first_is_not_forced_to_clarify(portfolio_client):
    client, provider, _, _ = portfolio_client(scripted_filter())
    report = _request(
        client, "请筛选已收录显示器，目前不设置任何硬约束，直接展示可核验的信息。",
    )["report"]
    assert report["clarification_state"] != "pending"
    assert provider.calls > 0
    assert not [item for item in report["constraint_set"]["constraints"]
                if item["active"] and item["hard_or_soft"] == "hard"]
