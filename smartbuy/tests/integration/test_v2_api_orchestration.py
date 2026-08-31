"""V1-compatible SSE plus sanitized V2 orchestration event integration."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from smartbuy.api.router import router, set_smartbuy_orchestrator
from smartbuy.constraints import VerificationBatch
from smartbuy.domain import DecisionReport
from smartbuy.memory import LongTermPreferenceStore
from smartbuy.orchestration import OrchestratorKind, OrchestratorSelector, OrchestratorSettings, ReactOrchestrator
from smartbuy.orchestration.checkpoints import InMemoryCheckpointBackend
from smartbuy.orchestration.langgraph_adapter import LangGraphOrchestrator


class EventAgent:
    def __init__(self, tmp_path):
        self.preference_memory = LongTermPreferenceStore(tmp_path / "preferences.json")

    async def run(self, query, *, event_callback=None, **_kwargs):
        if event_callback:
            await event_callback(
                {
                    "type": "tool_observation",
                    "trace": {
                        "tool": "kb_search",
                        "arguments_summary": {"query_summary": "脱敏查询"},
                        "status": "success",
                        "result_summary": "命中 1 条证据。",
                        "next_action": "进入确定性复核。",
                    },
                }
            )
            await event_callback({"type": "constraint_check_started", "candidate_pool_count": 0})
            await event_callback({"type": "constraint_check_completed", "degraded": False})
        return DecisionReport(
            request_summary=query,
            constraint_verification=VerificationBatch(
                verifier_version="smartbuy-constraint-checker-v1",
                checked_at="2026-08-31T00:00:00Z",
                constraint_set_version="smartbuy-constraint-set-v1",
                semantic_fingerprint="api-fixture",
            ),
            tools_used=["kb_search"],
            abstained=True,
            stop_reason="没有合规候选。",
        )


def test_langgraph_sse_keeps_v1_events_and_adds_v2_events(tmp_path):
    agent = EventAgent(tmp_path)
    selector = OrchestratorSelector(
        ReactOrchestrator(agent),
        lambda: LangGraphOrchestrator(agent, InMemoryCheckpointBackend()),
        OrchestratorSettings(selected=OrchestratorKind.LANGGRAPH),
    )
    set_smartbuy_orchestrator(selector)
    app = FastAPI()
    app.include_router(router)
    try:
        response = TestClient(app).post(
            "/api/smartbuy/chat",
            json={"query": "SSE 兼容验证", "stream": True, "session_id": "v2-sse"},
        )
    finally:
        set_smartbuy_orchestrator(None)
    assert response.status_code == 200
    assert '"type": "tool_call"' in response.text
    assert '"type": "constraint_check_started"' in response.text
    assert '"type": "orchestrator_selected"' in response.text
    assert '"type": "graph_started"' in response.text
    assert '"type": "checker_terminal_completed"' in response.text
    assert '"type": "checkpoint_saved"' in response.text
    assert "Authorization" not in response.text
    assert "Qianwen_api_key" not in response.text
