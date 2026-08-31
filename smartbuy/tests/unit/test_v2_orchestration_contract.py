"""V2-1C orchestration compatibility, selection and safety-gate tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smartbuy.constraints import CandidateVerification, VerificationBatch, VerificationStatus
from smartbuy.domain import CandidateDecision, ConstraintStatus, DecisionReport
from smartbuy.memory import LongTermPreferenceStore
from smartbuy.orchestration import (
    OrchestratorKind,
    OrchestratorRequest,
    OrchestrationStatus,
    OrchestratorSelector,
    OrchestratorSettings,
    ReactOrchestrator,
)
from smartbuy.orchestration.checkpoints import (
    InMemoryCheckpointBackend,
    SqliteCheckpointBackend,
    ThreadIdentity,
    strict_serializer,
)
from smartbuy.orchestration.langgraph_adapter import (
    IncompatibleCheckpointError,
    LangGraphInitializationError,
    LangGraphOrchestrator,
)


MODEL_IDS = [
    "dell-u2723qe-cn",
    "asus-pa279crv-cn",
    "lg-27up850k-w-cn",
    "dell-g2724d-cn",
    "benq-pd2705u-us",
    "dell-u2724d-cn",
    "asus-pg27aqdm-cn",
    "lg-27gr93u-cn",
    "benq-pd2706u-cn",
    "dell-u3223qe-cn",
]


def valid_report(model_id: str = MODEL_IDS[0]) -> DecisionReport:
    checked_at = "2026-08-31T00:00:00Z"
    verification = VerificationBatch(
        verifier_version="smartbuy-constraint-checker-v1",
        checked_at=checked_at,
        constraint_set_version="smartbuy-constraint-set-v1",
        candidate_pool_model_ids=[model_id],
        candidates=[
            CandidateVerification(
                model_id=model_id,
                overall_status=VerificationStatus.PASSED,
                eligible=True,
                checked_at=checked_at,
                verifier_version="smartbuy-constraint-checker-v1",
            )
        ],
        eligible_model_ids=[model_id],
        semantic_fingerprint=f"fixture-{model_id}",
    )
    return DecisionReport(
        request_summary=f"核验 {model_id}",
        constraint_verification=verification,
        candidates=[
            CandidateDecision(
                model_id=model_id,
                overall_status=ConstraintStatus.MATCHED,
                eligible=True,
                verifier_status=VerificationStatus.PASSED,
                verifier_version="smartbuy-constraint-checker-v1",
            )
        ],
        recommended_model_ids=[model_id],
        stop_reason="已完成确定性复核。",
    )


class StubCompatibleAgent:
    def __init__(self, tmp_path: Path, report: DecisionReport | None = None) -> None:
        self.preference_memory = LongTermPreferenceStore(tmp_path / "preferences.json")
        self.report = report or valid_report()
        self.calls = 0

    async def run(self, query, **_kwargs):
        self.calls += 1
        return self.report.model_copy(deep=True, update={"request_summary": query})


class ExplodingAgent(StubCompatibleAgent):
    async def run(self, query, **_kwargs):
        raise RuntimeError("injected runtime failure")


class BrokenCheckpointBackend:
    async def start(self):
        raise OSError("injected initialization failure")

    async def clear(self, _identity):
        return None

    async def close(self):
        return None


@pytest.mark.parametrize("model_id", MODEL_IDS)
@pytest.mark.asyncio
async def test_react_and_langgraph_share_result_contract_for_ten_cases(tmp_path, model_id):
    request = OrchestratorRequest(
        query=f"核验 {model_id}",
        session_id=f"session-{model_id}",
        user_id="comparison-user",
    )
    react = ReactOrchestrator(StubCompatibleAgent(tmp_path / "react", valid_report(model_id)))
    graph = LangGraphOrchestrator(
        StubCompatibleAgent(tmp_path / "graph", valid_report(model_id)),
        InMemoryCheckpointBackend(),
    )
    react_result = await react.run(request)
    graph_result = await graph.run(request)
    assert react_result.report == graph_result.report
    assert graph_result.status == OrchestrationStatus.COMPLETED
    assert graph_result.report.recommended_model_ids == [model_id]


def test_feature_flag_defaults_to_react_and_rejects_invalid_values(monkeypatch):
    monkeypatch.delenv("PROOFPICK_ORCHESTRATOR", raising=False)
    monkeypatch.delenv("PROOFPICK_LANGGRAPH_FALLBACK_TO_REACT", raising=False)
    assert OrchestratorSettings.from_environment().selected == OrchestratorKind.REACT
    assert OrchestratorSettings.from_environment().allow_initialization_fallback is False
    monkeypatch.setenv("PROOFPICK_ORCHESTRATOR", "automatic")
    with pytest.raises(ValueError, match="react or langgraph"):
        OrchestratorSettings.from_environment()


@pytest.mark.asyncio
async def test_langgraph_requires_explicit_selection_and_records_choice(tmp_path):
    agent = StubCompatibleAgent(tmp_path)
    created = 0

    def factory():
        nonlocal created
        created += 1
        return LangGraphOrchestrator(agent, InMemoryCheckpointBackend())

    events = []
    selector = OrchestratorSelector(
        ReactOrchestrator(agent),
        factory,
        OrchestratorSettings(selected=OrchestratorKind.REACT),
    )
    result = await selector.run(OrchestratorRequest(query="默认路径"), event_callback=events.append)
    assert result.orchestrator == OrchestratorKind.REACT
    assert created == 0
    assert events[0] == {
        "type": "orchestrator_selected",
        "requested": "react",
        "selected": "react",
        "status": "selected",
        "reason": None,
    }


@pytest.mark.asyncio
async def test_initialization_failure_never_silently_falls_back(tmp_path):
    agent = StubCompatibleAgent(tmp_path)
    selector = OrchestratorSelector(
        ReactOrchestrator(agent),
        lambda: LangGraphOrchestrator(agent, BrokenCheckpointBackend()),
        OrchestratorSettings(selected=OrchestratorKind.LANGGRAPH),
    )
    events = []
    with pytest.raises(LangGraphInitializationError):
        await selector.run(OrchestratorRequest(query="禁止静默回退"), event_callback=events.append)
    assert not any(event["type"] == "orchestrator_fallback" for event in events)
    assert any(event["type"] == "orchestrator_failed" for event in events)


@pytest.mark.asyncio
async def test_explicit_initialization_fallback_is_audited(tmp_path):
    agent = StubCompatibleAgent(tmp_path)
    selector = OrchestratorSelector(
        ReactOrchestrator(agent),
        lambda: LangGraphOrchestrator(agent, BrokenCheckpointBackend()),
        OrchestratorSettings(
            selected=OrchestratorKind.LANGGRAPH,
            allow_initialization_fallback=True,
        ),
    )
    events = []
    result = await selector.run(
        OrchestratorRequest(query="显式回退"), event_callback=events.append
    )
    assert result.orchestrator == OrchestratorKind.REACT
    assert [event["type"] for event in events if event["type"].startswith("orchestrator_")] == [
        "orchestrator_selected",
        "orchestrator_failed",
        "orchestrator_fallback",
    ]


@pytest.mark.asyncio
async def test_runtime_failure_is_not_replayed_through_react(tmp_path):
    react_agent = StubCompatibleAgent(tmp_path / "react")
    graph_agent = ExplodingAgent(tmp_path / "graph")
    selector = OrchestratorSelector(
        ReactOrchestrator(react_agent),
        lambda: LangGraphOrchestrator(graph_agent, InMemoryCheckpointBackend()),
        OrchestratorSettings(
            selected=OrchestratorKind.LANGGRAPH,
            allow_initialization_fallback=True,
        ),
    )
    with pytest.raises(RuntimeError, match="injected runtime failure"):
        await selector.run(OrchestratorRequest(query="运行时不得重复调用"))
    assert react_agent.calls == 0


@pytest.mark.asyncio
async def test_checker_bypass_and_missing_verification_fail_closed(tmp_path):
    bypass = valid_report()
    bypass.recommended_model_ids.append("outside-checker-pool")
    for report in [bypass, DecisionReport(request_summary="无 Checker", stop_reason="unsafe")]:
        graph = LangGraphOrchestrator(
            StubCompatibleAgent(tmp_path / str(len(report.recommended_model_ids)), report),
            InMemoryCheckpointBackend(),
        )
        result = await graph.run(OrchestratorRequest(query=report.request_summary))
        assert result.report.recommended_model_ids == []
        assert result.report.abstained is True
        assert any("orchestration_fail_closed" in item for item in result.report.degraded_states)


@pytest.mark.asyncio
async def test_checker_exception_batch_stays_fail_closed_at_graph_terminal(tmp_path):
    report = valid_report()
    report.constraint_verification.degraded = True
    report.constraint_verification.degrade_reason = "injected_checker_exception"
    events = []
    graph = LangGraphOrchestrator(
        StubCompatibleAgent(tmp_path, report),
        InMemoryCheckpointBackend(),
    )
    result = await graph.run(
        OrchestratorRequest(query="Checker 异常"),
        event_callback=events.append,
    )
    assert result.report.recommended_model_ids == []
    assert result.report.abstained is True
    terminal = next(event for event in events if event["type"] == "checker_terminal_completed")
    assert terminal["status"] == "fail_closed"


@pytest.mark.asyncio
async def test_graph_topology_has_no_report_path_around_checker(tmp_path):
    graph = LangGraphOrchestrator(
        StubCompatibleAgent(tmp_path),
        InMemoryCheckpointBackend(),
    )
    compiled = await graph._ensure_graph()
    topology = compiled.get_graph()
    report_predecessors = {edge.source for edge in topology.edges if edge.target == "report"}
    assert report_predecessors == {"checker_terminal"}
    assert any(edge.source == "execute_react" and edge.target == "checker_terminal" for edge in topology.edges)


@pytest.mark.asyncio
async def test_interrupt_resume_and_checkpoint_version_rejection(tmp_path):
    graph = LangGraphOrchestrator(
        StubCompatibleAgent(tmp_path),
        InMemoryCheckpointBackend(),
    )
    first_request = OrchestratorRequest(
        query="27 英寸左右",
        user_id="u1",
        session_id="s1",
        thread_id="t1",
        clarification_question="27 英寸是否为硬约束？",
    )
    first = await graph.run(first_request)
    assert first.status == OrchestrationStatus.INTERRUPTED
    resumed = await graph.run(
        OrchestratorRequest(
            query=first_request.query,
            user_id="u1",
            session_id="s1",
            thread_id="t1",
            resume_value="是",
        )
    )
    assert resumed.status == OrchestrationStatus.COMPLETED
    assert resumed.resumed is True

    await graph.run(
        OrchestratorRequest(
            query="另一个中断",
            user_id="u1",
            session_id="s1",
            thread_id="t2",
            clarification_question="继续吗？",
        )
    )
    identity = ThreadIdentity(user_id="u1", session_id="s1", thread_id="t2")
    config = graph._config(identity)
    await graph._graph.aupdate_state(config, {"state_version": "unsupported-v0"})
    with pytest.raises(IncompatibleCheckpointError):
        await graph.run(
            OrchestratorRequest(
                query="另一个中断",
                user_id="u1",
                session_id="s1",
                thread_id="t2",
                resume_value="继续",
            )
        )


def test_thread_identity_isolates_user_session_and_thread():
    base = ThreadIdentity(user_id="u1", session_id="s1", thread_id="t1").storage_key
    assert base != ThreadIdentity(user_id="u2", session_id="s1", thread_id="t1").storage_key
    assert base != ThreadIdentity(user_id="u1", session_id="s2", thread_id="t1").storage_key
    assert base != ThreadIdentity(user_id="u1", session_id="s1", thread_id="t2").storage_key
    assert len(base) == 64


def test_serializer_disables_pickle_and_uses_exact_allowlist():
    serializer = strict_serializer()
    assert serializer.pickle_fallback is False
    assert serializer._allowed_modules == {("builtins", "dict")}


@pytest.mark.asyncio
async def test_sqlite_backend_rejects_repo_path_and_supports_clear(tmp_path):
    repository_root = Path(__file__).resolve().parents[3]
    with pytest.raises(ValueError, match="outside"):
        SqliteCheckpointBackend(repository_root / "unsafe.sqlite3", repository_root=repository_root)
    backend = SqliteCheckpointBackend(tmp_path / "safe.sqlite3", repository_root=repository_root)
    saver = await backend.start()
    assert saver is await backend.start()
    await backend.clear(ThreadIdentity(user_id="u", session_id="s", thread_id="t"))
    await backend.close()


def test_frozen_v1_sixteen_case_result_is_unchanged():
    root = Path(__file__).resolve().parents[3]
    payload = json.loads(
        (root / "smartbuy/data/processed/stage6_stage4_regression_results.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(payload["cases"]) == 16
    assert sum(bool(case["end_to_end_pass"]) for case in payload["cases"]) == 16
