"""SmartBuy API, SSE and upstream WebUI integration smoke tests."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from smartbuy.api.router import router, set_smartbuy_agent
from smartbuy.domain import DecisionReport
from smartbuy.memory import LongTermPreferenceStore


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class StubAgent:
    def __init__(self, memory_path):
        self.preference_memory = LongTermPreferenceStore(memory_path)

    async def run(self, query, *, session_id=None, user_id=None, use_long_term_memory=False, event_callback=None):
        if event_callback:
            await event_callback(
                {
                    "type": "tool_observation",
                    "trace": {
                        "tool": "kb_search",
                        "arguments_summary": {"query_summary": "脱敏查询"},
                        "status": "success",
                        "result_summary": "命中 1 条证据。",
                        "next_action": "生成报告。",
                    },
                }
            )
            await event_callback(
                {
                    "type": "constraint_check_started",
                    "verifier_version": "smartbuy-constraint-checker-v1",
                    "candidate_pool_count": 1,
                }
            )
            await event_callback(
                {
                    "type": "constraint_check_completed",
                    "verification": {
                        "verifier_version": "smartbuy-constraint-checker-v1",
                        "eligible_model_ids": ["dell-u2723qe-cn"],
                        "candidates": [],
                        "degraded": False,
                    },
                }
            )
        return DecisionReport(
            request_summary=query,
            tools_used=["kb_search"],
            stop_reason="证据已核验。",
            abstained=False,
        )


def app_with_stub(tmp_path):
    app = FastAPI()
    app.include_router(router)
    set_smartbuy_agent(StubAgent(tmp_path / "preferences.json"))
    return app


def test_non_stream_and_memory_lifecycle(tmp_path):
    client = TestClient(app_with_stub(tmp_path))
    response = client.post(
        "/api/smartbuy/chat",
        json={"query": "U2723QE 分辨率？", "stream": False, "session_id": "s1"},
    )
    assert response.status_code == 200
    assert response.json()["report"]["tools_used"] == ["kb_search"]
    rejected = client.put(
        "/api/smartbuy/memory/u1",
        json={"preferences": {"display_size_inch": 27}, "explicitly_confirmed": False},
    )
    assert rejected.status_code == 422
    saved = client.put(
        "/api/smartbuy/memory/u1",
        json={"preferences": {"display_size_inch": 27}, "explicitly_confirmed": True},
    )
    assert saved.json()["preferences"] == {"display_size_inch": 27}
    disabled = client.post("/api/smartbuy/memory/u1/enabled", json={"enabled": False})
    assert disabled.json()["enabled"] is False
    deleted = client.request("DELETE", "/api/smartbuy/memory/u1", json={"fields": None})
    assert deleted.json()["preferences"] == {}


def test_sse_contains_public_tool_cards_and_markdown(tmp_path):
    client = TestClient(app_with_stub(tmp_path))
    response = client.post(
        "/api/smartbuy/chat",
        json={"query": "简单事实", "stream": True, "session_id": "s1"},
    )
    assert response.status_code == 200
    assert '"type": "tool_call"' in response.text
    assert '"type": "tool_output"' in response.text
    assert '"type": "constraint_check_started"' in response.text
    assert '"type": "constraint_check_completed"' in response.text
    assert '"type": "done"' in response.text
    assert "SmartBuy 消费决策报告" in response.text
    assert "Authorization" not in response.text


def test_upstream_webui_is_wired_to_smartbuy_endpoint():
    javascript = (
        PROJECT_ROOT / "vendor/youtu-rag/frontend/rag_webui/assets/js/components/chat.js"
    ).read_text(encoding="utf-8")
    html = (PROJECT_ROOT / "vendor/youtu-rag/frontend/rag_webui/pages/chat.html").read_text(encoding="utf-8")
    assert "/api/smartbuy/chat" in javascript
    assert "tool_call" in javascript and "tool_output" in javascript
    assert "constraint_check_started" in javascript
    assert "constraint_check_completed" in javascript
    assert 'id="smartbuy-mode"' in html
