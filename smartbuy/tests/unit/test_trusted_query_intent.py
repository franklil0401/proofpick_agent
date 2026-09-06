"""Synthetic, offline regressions for full-clause intent negation."""

from __future__ import annotations

import pytest

from smartbuy.decision_core.intent import QueryUnderstandingEngine
from smartbuy.domain_packs import DEFAULT_MONITOR_PACK, DomainPackLoader
from smartbuy.identity import ProductScopeResolutionStatus, ProductScopeType, QueryIntent, ResolvedProductScope


def _scope(*, compare=False):
    return ResolvedProductScope(
        domain_id="monitor", scope_type=(ProductScopeType.EXPLICIT_COMPARISON if compare else ProductScopeType.EXACT_CONFIGURATION),
        product_ids=["fictional-ax100", "fictional-ax200"] if compare else ["fictional-ax100"],
        resolution_status=ProductScopeResolutionStatus.RESOLVED,
        resolution_reason="fictional_registry", data_version="fictional-v1",
    )


@pytest.fixture
def understanding():
    return QueryUnderstandingEngine(DomainPackLoader().load(DEFAULT_MONITOR_PACK))


@pytest.mark.parametrize("query", [
    "核验 AX100 的刷新率，不要把核验对象当作推荐商品。",
    "只查 AX100 的尺寸，不需要根据这次参数核对的对象再向我推荐商品。",
    "只核实 AX100 的接口，不得把出现的产品写为筛选后的推荐对象。",
    "不是让你推荐商品，而是核验 AX100 的供电。",
    "查询 AX100 的宽度，不要比较其他产品。",
])
def test_fact_query_keeps_negated_purchase_or_comparison_out_of_intent(understanding, query):
    result = understanding.analyze(query, _scope())
    assert result.intent == QueryIntent.EXACT_FACT_VERIFICATION


@pytest.mark.parametrize("query", [
    "只比较 AX100 和 AX200 的参数，不要把对象当作推荐商品。",
    "对比 AX100 和 AX200，不要根据出现的参数、尺寸或价格把任何对象当成推荐商品。",
    "只比较参数，不需要在核验完成以后给这些商品加上筛选结果或推荐标签。",
])
def test_comparison_with_unbounded_negative_clause_remains_comparison(understanding, query):
    assert understanding.analyze(query, _scope(compare=True)).intent == QueryIntent.EXPLICIT_COMPARISON


@pytest.mark.parametrize("query", [
    "先筛选宽度最多 600mm 的产品，再比较刷新率。",
    "推荐非 OLED 产品并对比接口。",
    "先挑选预算内的设备，然后比较尺寸。",
    "请筛选宽度最多 600mm 的型号，不要把结果改成只比较参数。",
])
def test_positive_purchase_request_is_not_erased_by_comparison(understanding, query):
    assert understanding.analyze(query, _scope(compare=True)).intent == QueryIntent.RECOMMENDATION_FILTER


@pytest.mark.parametrize("query", [
    "比较 AX100 和 AX200 的尺寸，但先问我桌面可以多宽。",
    "先向我确认用途，再筛选 AX100 与 AX200。",
    "请先澄清地区，然后再比较这两台设备。",
])
def test_explicit_ask_first_precedes_comparison_and_filter(understanding, query):
    result = understanding.analyze(query, _scope(compare=True))
    assert result.intent == QueryIntent.CLARIFICATION_REQUIRED
    assert result.clarification_reason == "explicit_clarification_language"


@pytest.mark.parametrize("query, expected", [
    ("只比较参数，不要把这些展示出来的对象当作任何购买推荐。", "comparison"),
    ("只核验尺寸，不需要使用这份核验结果来为我推荐产品。", "fact"),
    ("筛选预算内的设备，再比较参数。", "filter"),
    ("请先问我用途，再比较参数。", "clarification"),
    ("不要先问用途，直接比较参数。", "comparison"),
    ("不限制地区，推荐宽度不超过 600mm 的设备。", "filter"),
    ("无需把参数比较变成推荐，但请筛选符合预算的产品。", "filter"),
    ("比较参数，我不希望你参考这些数字、喜好或默认条件向我推荐任何型号。", "comparison"),
    ("只核验接口。我不希望这份核验记录被用于购买推荐。", "fact"),
    ("先说明差别然后推荐满足预算的产品。", "filter"),
])
def test_shared_semantics_is_usable_without_catalog_or_business_modules(query, expected):
    from smartbuy.decision_core.query_semantics import analyze_trusted_query_intent

    assert analyze_trusted_query_intent(query).task_type == expected


@pytest.mark.parametrize("query, expected", [
    ("只比较 AX100 和 AX200 参数；不要把这些对象，尤其是参数接近的条目，标成推荐商品。", "comparison"),
    ("只核验 AX100 的接口。我不希望你把出现的对象，包括参数齐全的条目，当作选购建议。", "fact"),
    ("不要把已经列出的对象，尤其参数接近的条目，标成推荐商品；但请筛选宽度最多600mm的设备。", "filter"),
    ("不要 OLED，请筛选预算内的设备再比较接口。", "filter"),
    ("不要把这些对象当作推荐商品，请只比较参数。", "comparison"),
    ("只核验接口；不要把这些对象，尤其是参数存在差异的条目，标成推荐商品。", "fact"),
])
def test_parenthetical_clause_does_not_end_unfinished_negative_action(query, expected):
    from smartbuy.decision_core.query_semantics import analyze_trusted_query_intent

    assert analyze_trusted_query_intent(query).task_type == expected
