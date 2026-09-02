"""V2-5 equivalent clarification pause/resume semantics for both orchestrators."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from smartbuy.api.router import router, set_smartbuy_orchestrator
from smartbuy.constraint_proposals.coordinator import (
    ClarificationCoordinator,
    ClarificationStore,
    ClarifyingOrchestrator,
)
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.constraint_proposals.models import ClarificationState
from smartbuy.constraint_proposals.settings import NaturalConstraintSettings
from smartbuy.domain import DecisionReport
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.domain_packs.loader import DEFAULT_MONITOR_PACK
from smartbuy.memory import LongTermPreferenceStore
from smartbuy.orchestration import OrchestratorRequest, OrchestrationStatus, ReactOrchestrator
from smartbuy.orchestration.checkpoints import InMemoryCheckpointBackend
from smartbuy.orchestration.langgraph_adapter import LangGraphOrchestrator


ROOT = Path(__file__).resolve().parents[3]


class RecordingAgent:
    def __init__(self, root: Path) -> None:
        self.preference_memory = LongTermPreferenceStore(root / "preferences.json")
        self.calls = 0
        self.resolutions = []

    async def run(self, query, **kwargs):
        self.calls += 1
        resolution = kwargs.get("constraint_resolution")
        self.resolutions.append(resolution)
        return DecisionReport(
            request_summary=query,
            constraint_set=resolution.constraint_set if resolution else {},
            constraint_proposals=resolution.proposals if resolution else [],
            clarification_state=(
                resolution.clarification_state if resolution else ClarificationState.NOT_REQUIRED
            ),
            constraint_diff=resolution.diff if resolution else [],
            stop_reason="fixture completed",
        )


def _wrapped(kind: str, tmp_path: Path):
    agent = RecordingAgent(tmp_path / kind)
    base = (
        ReactOrchestrator(agent)
        if kind == "react"
        else LangGraphOrchestrator(agent, InMemoryCheckpointBackend())
    )
    engine = NaturalConstraintEngine(DomainPackLoader().load(DEFAULT_MONITOR_PACK))
    coordinator = ClarificationCoordinator(
        engine,
        ClarificationStore(tmp_path / kind / "pending", repository_root=ROOT),
        context_loader=lambda _session: (None, 1),
        preference_memory=agent.preference_memory,
    )
    return (
        ClarifyingOrchestrator(
            base,
            coordinator,
            NaturalConstraintSettings(
                enabled=True,
                llm_fallback_enabled=False,
                clarification_root=tmp_path / kind / "pending",
            ),
        ),
        agent,
    )


@pytest.mark.parametrize("kind", ["react", "langgraph"])
@pytest.mark.parametrize(
    "task_id,query",
    [
        ("c1", "27 寸左右"),
        ("c2", "预算两三千吧"),
        ("c3", "高刷就行"),
        ("c4", "屏幕不要太大"),
        ("c5", "Type-C 可以给笔记本充电"),
    ],
)
@pytest.mark.asyncio
async def test_five_clarification_tasks_pause_and_resume_without_replaying_tools(
    tmp_path, kind, task_id, query
):
    orchestrator, agent = _wrapped(kind, tmp_path / task_id)
    common = dict(
        query=query,
        user_id="u1",
        session_id=f"s-{task_id}",
        thread_id=f"t-{task_id}",
        use_natural_constraints=True,
    )
    events = []
    first = await orchestrator.run(OrchestratorRequest(**common), event_callback=events.append)
    assert first.status == OrchestrationStatus.INTERRUPTED
    assert agent.calls == 0
    resumed = await orchestrator.run(
        OrchestratorRequest(**common, resume_value=False), event_callback=events.append
    )
    assert resumed.status == OrchestrationStatus.COMPLETED
    assert resumed.resumed is True
    assert agent.calls == 1
    assert agent.resolutions[0].clarification_state == ClarificationState.REJECTED
    assert any(event["type"] == "clarification_pending" for event in events)
    assert any(event["type"] == "clarification_resolved" for event in events)


@pytest.mark.asyncio
async def test_react_and_langgraph_return_same_confirmed_constraint_result(tmp_path):
    outputs = []
    for kind in ("react", "langgraph"):
        orchestrator, agent = _wrapped(kind, tmp_path / kind)
        common = dict(
            query="27 寸左右",
            user_id="u",
            session_id=f"s-{kind}",
            thread_id=f"t-{kind}",
            use_natural_constraints=True,
        )
        await orchestrator.run(OrchestratorRequest(**common))
        result = await orchestrator.run(OrchestratorRequest(**common, resume_value=True))
        outputs.append(
            result.report.constraint_set.model_dump(mode="json", exclude={"constraints": {0: {"source_turn"}}})
        )
        assert agent.calls == 1
    assert outputs[0] == outputs[1]


@pytest.mark.asyncio
async def test_followup_value_resolves_missing_threshold_without_provider_or_tool_replay(tmp_path):
    orchestrator, agent = _wrapped("react", tmp_path)
    common = dict(
        query="屏幕不要太大",
        user_id="u",
        session_id="s-value",
        thread_id="t-value",
        use_natural_constraints=True,
    )
    first = await orchestrator.run(OrchestratorRequest(**common))
    assert first.status == OrchestrationStatus.INTERRUPTED and agent.calls == 0
    resumed = await orchestrator.run(
        OrchestratorRequest(**common, resume_value="32 英寸以下")
    )
    active = [
        item
        for item in resumed.report.constraint_set.active()
        if item.field == "display_size_inch"
    ]
    assert len(active) == 1 and active[0].normalized_value == 32
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_react_pending_state_resumes_after_runtime_reconstruction(tmp_path):
    first_runtime, first_agent = _wrapped("react", tmp_path)
    common = dict(
        query="预算两三千吧",
        user_id="u",
        session_id="s-restart",
        thread_id="t-restart",
        use_natural_constraints=True,
    )
    first = await first_runtime.run(OrchestratorRequest(**common))
    assert first.status == OrchestrationStatus.INTERRUPTED
    assert first_agent.calls == 0
    second_runtime, second_agent = _wrapped("react", tmp_path)
    resumed = await second_runtime.run(
        OrchestratorRequest(**common, resume_value=True)
    )
    assert resumed.status == OrchestrationStatus.COMPLETED
    assert second_agent.calls == 1


@pytest.mark.asyncio
async def test_feature_off_preserves_v1_path_and_pending_never_writes_long_term_memory(tmp_path):
    orchestrator, agent = _wrapped("react", tmp_path)
    plain = await orchestrator.run(OrchestratorRequest(query="27 寸左右"))
    assert plain.status == OrchestrationStatus.COMPLETED
    assert agent.calls == 1
    pending = await orchestrator.run(
        OrchestratorRequest(
            query="预算两三千吧",
            user_id="memory-user",
            session_id="memory-session",
            thread_id="memory-thread",
            use_natural_constraints=True,
            use_long_term_memory=True,
        )
    )
    assert pending.status == OrchestrationStatus.INTERRUPTED
    assert agent.preference_memory.view("memory-user")["preferences"] == {}


@pytest.mark.asyncio
async def test_explicit_request_is_not_silently_downgraded_when_runtime_flag_is_off(tmp_path):
    agent = RecordingAgent(tmp_path)
    orchestrator = ClarifyingOrchestrator(
        ReactOrchestrator(agent),
        None,
        NaturalConstraintSettings(enabled=False),
    )
    with pytest.raises(RuntimeError, match="not enabled"):
        await orchestrator.run(
            OrchestratorRequest(query="27 寸左右", use_natural_constraints=True)
        )
    assert agent.calls == 0


def test_api_sse_and_monitor_expose_sanitized_proposal_and_clarification_state(tmp_path):
    orchestrator, _agent = _wrapped("react", tmp_path)
    set_smartbuy_orchestrator(orchestrator)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    common = {
        "query": "27 寸左右",
        "session_id": "api-s",
        "thread_id": "api-t",
        "use_natural_constraints": True,
    }
    try:
        first = client.post("/api/smartbuy/chat", json={**common, "stream": True})
        assert first.status_code == 200
        assert '"type": "constraint_proposals_resolved"' in first.text
        assert '"type": "clarification_pending"' in first.text
        assert '"status": "interrupted"' in first.text
        resumed = client.post(
            "/api/smartbuy/chat",
            json={**common, "stream": False, "resume_value": False},
        )
        assert resumed.status_code == 200
        assert resumed.json()["report"]["clarification_state"] == "rejected"
        monitor = client.get("/api/smartbuy/monitor").json()
        assert monitor["recent_constraint_events"][-1]["status"] == "rejected"
        assert "source_span" not in monitor["recent_constraint_events"][-1]
    finally:
        set_smartbuy_orchestrator(None)
