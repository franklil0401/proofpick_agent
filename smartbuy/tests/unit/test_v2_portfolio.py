from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from smartbuy.api.portfolio_runtime import PortfolioRuntimeManager
from smartbuy.portfolio import load_demo_bundle
from smartbuy.portfolio.dynamic_facts import assess_dynamic_observation
from smartbuy.scripts.verify_v2_9a_demos import run


ROOT = Path(__file__).resolve().parents[3]


def test_portfolio_bundle_covers_five_demos_three_domains_and_modes() -> None:
    bundle = load_demo_bundle()
    assert len(bundle.demos) == 5
    assert {item.domain_id for item in bundle.demos} == {"monitor", "laptop", "headphone"}
    assert {item.mode for item in bundle.demos} == {"trusted", "open"}
    assert all(item.trace and item.run_evidence for item in bundle.demos)
    assert all(
        candidate.checker_status != "eligible"
        for demo in bundle.demos
        if demo.mode == "open"
        for candidate in demo.candidates
    )


def test_five_demo_contracts_verify_without_api_calls() -> None:
    result = run()
    assert (result["passed"], result["total"]) == (5, 5)
    assert result["api_calls"] == 0
    assert result["estimated_cost_cny"] == 0


def test_dynamic_observation_is_current_only_inside_ttl() -> None:
    record = {
        "model_id": "test-product",
        "region": "CN",
        "currency": "CNY",
        "price_cny": 1999,
        "stock_status": "available",
        "url": "https://example.com/product",
        "observed_at": "2026-09-04T00:00:00Z",
    }
    current = assess_dynamic_observation(
        record,
        as_of=datetime(2026, 9, 4, 12, tzinfo=UTC),
        ttl=timedelta(hours=24),
    )
    assert current.status == "verified_observation" and current.price == 1999
    stale = assess_dynamic_observation(
        record,
        as_of=datetime(2026, 9, 6, tzinfo=UTC),
        ttl=timedelta(hours=24),
    )
    assert stale.status == "unknown" and stale.price is None and stale.expired
    assert stale.eligible_for_trusted_checker is False


def test_dynamic_observation_rejects_cross_currency_and_non_http() -> None:
    base = {
        "model_id": "test-product",
        "region": "US",
        "price_cny": 1,
        "observed_at": "2026-09-04T00:00:00Z",
    }
    with pytest.raises(ValueError, match="cross-currency"):
        assess_dynamic_observation(
            {**base, "currency": "USD", "url": "https://example.com"},
            as_of=datetime(2026, 9, 4, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="HTTP"):
        assess_dynamic_observation(
            {**base, "currency": "CNY", "url": "file:///private/cache"},
            as_of=datetime(2026, 9, 4, tzinfo=UTC),
        )


def test_portfolio_ui_has_required_public_states_and_no_secret_values() -> None:
    html = (ROOT / "vendor/youtu-rag/frontend/rag_webui/app.html").read_text(encoding="utf-8")
    script = (ROOT / "vendor/youtu-rag/frontend/rag_webui/assets/js/components/portfolio.js").read_text(encoding="utf-8")
    combined = html + script
    for term in (
        "monitor", "laptop", "headphone", "trusted", "open", "online_unavailable",
        "Constraint Checker", "Decision Ranker", "Memory", "固定脱敏回放",
    ):
        assert term.casefold() in combined.casefold()
    assert "Qianwen_api_key" not in combined
    assert "ZhiPu_api_key" not in combined
    assert "Authorization" not in combined


def test_portfolio_runtime_is_default_off(monkeypatch) -> None:
    monkeypatch.delenv("PROOFPICK_DOMAIN_AGENT_ENABLED", raising=False)
    assert PortfolioRuntimeManager.enabled() is False
    with pytest.raises(RuntimeError, match="domain_agent_disabled"):
        PortfolioRuntimeManager().get("laptop")


def test_replay_json_is_valid_json_and_contains_no_absolute_private_path() -> None:
    path = ROOT / "vendor/youtu-rag/frontend/rag_webui/assets/data/proofpick-demos.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False)
    assert len(payload["demos"]) == 5
    assert "C:\\Users\\" not in serialized
    assert "E:\\Agent_project" not in serialized
