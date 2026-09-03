"""Offline V2-6C acceptance for generic routing, Agent safety and orchestration parity."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from smartbuy.agent import (
    DomainAgentGateway,
    DomainAgentSettings,
    DomainDecisionAgent,
    DomainRuntimeContext,
    DomainRuntimeRegistry,
)
from smartbuy.constraint_proposals import ConstraintResolution
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.constraints import (
    ConstraintOperator,
    ConstraintProvenance,
    ConstraintSet,
    ConstraintStrength,
    NormalizedConstraint,
)
from smartbuy.domain_packs import CategoryRouteStatus, CategoryRouter, DomainPackLoader, DomainPackRegistry
from smartbuy.memory import DomainPreferenceMemoryStore
from smartbuy.orchestration.checkpoints import InMemoryCheckpointBackend
from smartbuy.orchestration.contracts import OrchestratorRequest
from smartbuy.orchestration.langgraph_adapter import LangGraphOrchestrator
from smartbuy.orchestration.react_adapter import ReactOrchestrator
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)
from smartbuy.tools import ToolResult


ROOT = Path(__file__).resolve().parents[3]
DOMAIN_ROOT = ROOT / "smartbuy" / "domain_packs"
LAPTOP_DOMAIN = DOMAIN_ROOT / "laptop"
LAPTOP_PACK = ROOT / "smartbuy" / "product_packs" / "examples" / "laptop-v1" / "pack.json"
CASES = ROOT / "smartbuy" / "eval" / "v2_6a_laptop_cases.jsonl"
FROZEN_SHA = "3dfcc0f442bda2b6b4d2e96814a8973b415b3d8c8b9b33235924982fa1758d34"


def _resolution(query: str, *items: tuple[str, str, object, str | None]) -> ConstraintResolution:
    constraints = [
        NormalizedConstraint(
            field=field,
            operator=ConstraintOperator(operator),
            normalized_value=value,
            unit=unit,
            hard_or_soft=ConstraintStrength.HARD,
            provenance=ConstraintProvenance.CURRENT_INPUT,
            source_text=query,
            source_turn=1,
            confidence=1,
        )
        for field, operator, value, unit in items
    ]
    return ConstraintResolution(
        query=query, source_turn=1, constraint_set=ConstraintSet(constraints=constraints)
    )


def _agent(tmp_path: Path) -> DomainDecisionAgent:
    pack = DomainPackLoader().load(LAPTOP_DOMAIN)
    manager = DomainProductPackManager(tmp_path / "data", domain_pack_path=LAPTOP_DOMAIN)
    snapshot = manager.publish(manager.stage(LAPTOP_PACK).data_version)
    repository = DomainReadonlyRepository(snapshot, pack)
    return DomainDecisionAgent(
        pack,
        repository,
        DomainProductQueryTool(repository),
        DomainEvidenceCheckTool(repository),
        DomainConstraintCheckerTool(repository),
        NaturalConstraintEngine(pack),
        DomainPreferenceMemoryStore(tmp_path / "memory", pack),
    )


def test_category_router_is_registry_driven_and_fails_closed() -> None:
    router = CategoryRouter(DomainPackRegistry(DOMAIN_ROOT))
    assert router.route("想买一台笔记本电脑").domain_id == "laptop"
    assert router.route("给显示器做 4K 筛选").domain_id == "monitor"
    mixed = router.route("同时比较显示器和笔记本")
    assert mixed.status == CategoryRouteStatus.NEEDS_CLARIFICATION
    assert set(mixed.matched_domain_ids) == {"monitor", "laptop"}
    assert router.route("买相机", explicit_domain_id="camera").status == CategoryRouteStatus.UNSUPPORTED
    assert router.route("买相机", explicit_domain_id="camera", allow_open=True).status == CategoryRouteStatus.OPEN
    assert router.route("任何文本", explicit_domain_id="laptop").reason == "explicit_domain_validated"


@pytest.mark.asyncio
async def test_generic_agent_checks_complete_pool_and_unknown_without_overclaim(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    query = "筛选笔记本：内存至少 32GB 且存储至少 1TB。"
    events = []
    report = await agent.run(
        query,
        event_callback=lambda event: events.append(event),
        constraint_resolution=_resolution(
            query,
            ("memory_gb", "gte", 32, "GB"),
            ("storage_gb", "gte", 1024, "GB"),
        ),
    )
    assert report.constraint_verification is not None
    assert len(report.constraint_verification.candidate_pool_model_ids) == 12
    assert set(report.recommended_model_ids) == set(report.constraint_verification.eligible_model_ids)
    assert report.recommended_model_ids
    assert all(item.eligible == (item.model_id in report.recommended_model_ids) for item in report.candidates)
    assert report.tool_call_count <= 12
    scope_event = next(item for item in events if item["type"] == "product_scope_resolved")
    assert scope_event["candidate_count"] == 12
    assert "mentioned_quotes" not in scope_event and "query" not in scope_event
    budget = "筛选预算八千以内的笔记本。"
    unknown = await agent.run(
        budget,
        constraint_resolution=_resolution(budget, ("price_cny", "lte", 8000, "CNY")),
    )
    assert unknown.recommended_model_ids == [] and unknown.abstained
    assert all(item.unknown_fields == ["price_cny"] for item in unknown.candidates)
    fact = await agent.run("笔记本 H7606WI 的屏幕刷新率是多少？")
    assert fact.abstained and fact.recommended_model_ids == []
    assert any(item.field == "refresh_rate_hz" for item in fact.unresolved_facts)
    assert fact.product_scope.configuration_ids == ["H7606WI"]
    family = await agent.run("XPS 13 9350 有哪些配置？")
    assert family.clarification_state.value == "pending"
    assert family.recommended_model_ids == [] and family.abstained


@pytest.mark.asyncio
async def test_react_langgraph_and_gateway_share_eligibility(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    query = "筛选笔记本：电池至少 80Wh，显存至少 8GB。"
    resolution = _resolution(
        query,
        ("battery_wh", "gte", 80, "Wh"),
        ("gpu_vram_gb", "gte", 8, "GB"),
    )
    request = OrchestratorRequest(
        query=query, session_id="s", user_id="u", thread_id="t",
        constraint_resolution=resolution,
    )
    react = ReactOrchestrator(agent)
    graph = LangGraphOrchestrator(agent, InMemoryCheckpointBackend())
    react_result = await react.run(request)
    graph_result = await graph.run(request)
    assert react_result.report is not None and graph_result.report is not None
    assert react_result.report.constraint_set == graph_result.report.constraint_set
    assert react_result.report.recommended_model_ids == graph_result.report.recommended_model_ids
    assert react_result.report.product_scope == graph_result.report.product_scope
    assert (
        react_result.report.constraint_verification.candidate_pool_model_ids
        == graph_result.report.constraint_verification.candidate_pool_model_ids
    )
    assert graph._graph is not None
    checkpoint = await graph._graph.aget_state(
        graph._config(graph._identity(request, request.thread_id or request.session_id))
    )
    assert checkpoint.values["resolved_product_scope"] == graph_result.report.product_scope.model_dump(
        mode="json"
    )
    runtimes = DomainRuntimeRegistry()
    runtimes.register(DomainRuntimeContext(
        domain_id="laptop", domain_pack_version=agent.pack.version,
        data_version=agent.repository.snapshot.data_version, index_version=None,
        orchestrator=react,
    ))
    gateway = DomainAgentGateway(
        CategoryRouter(DomainPackRegistry(DOMAIN_ROOT)), runtimes,
        DomainAgentSettings(enabled=True),
    )
    routed = await gateway.run(request)
    assert routed.route.domain_id == "laptop"
    assert routed.orchestration is not None
    assert routed.orchestration.report.recommended_model_ids == react_result.report.recommended_model_ids
    await graph.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "query"),
    [
        ("fact", "请查 H7606WI 的显存。"),
        ("unique", "H7606 系列需要 RTX 5080 Laptop GPU 和 16GB 显存。"),
        ("family", "XPS 13 9350 有哪些配置？"),
        ("compare", "比较 H7606WI 和 H7606WX 的显卡与内存。"),
        ("filter", "筛选内存至少 32GB 且存储至少 1TB 的笔记本。"),
        ("empty", "筛选电池至少 200Wh 的笔记本。"),
        ("region", "只看美国版且内存至少 32GB。"),
        ("exclude", "筛选笔记本但排除 ASUS。"),
        ("unsupported", "必须带摄像头的笔记本。"),
        ("cancel", "预算不用管，内存至少 32GB，存储从 2TB 改成 1TB。"),
    ],
)
async def test_ten_laptop_cases_have_react_langgraph_semantic_parity(
    tmp_path: Path,
    case_id: str,
    query: str,
) -> None:
    react = ReactOrchestrator(_agent(tmp_path / f"react-{case_id}"))
    graph = LangGraphOrchestrator(
        _agent(tmp_path / f"graph-{case_id}"),
        InMemoryCheckpointBackend(),
    )
    request = OrchestratorRequest(
        query=query,
        session_id=f"session-{case_id}",
        thread_id=f"thread-{case_id}",
    )
    react_result = await react.run(request)
    graph_result = await graph.run(request)
    assert react_result.report is not None and graph_result.report is not None
    left, right = react_result.report, graph_result.report
    assert left.query_intent == right.query_intent
    assert left.product_scope == right.product_scope
    assert left.constraint_set.model_dump(mode="json") == right.constraint_set.model_dump(mode="json")
    assert left.constraint_verification is not None
    assert right.constraint_verification is not None
    assert (
        left.constraint_verification.eligible_model_ids
        == right.constraint_verification.eligible_model_ids
    )
    assert left.recommended_model_ids == right.recommended_model_ids
    assert left.abstained == right.abstained
    assert left.clarification_state == right.clarification_state
    assert set(left.recommended_model_ids) <= set(left.product_scope.product_ids)
    assert set(right.recommended_model_ids) <= set(right.product_scope.product_ids)
    await graph.close()


@pytest.mark.asyncio
async def test_generic_repairs_for_evidence_reference_result_and_alias_boundaries(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)

    evidence_reference = await agent.run(
        "请查 H7606WI 的显存；H7606WX 的 24GB 参数不能作为 WI 的证据。"
    )
    assert evidence_reference.query_intent.value == "exact_fact_verification"
    assert evidence_reference.product_scope.configuration_ids == ["H7606WI"]
    assert not [
        item
        for item in evidence_reference.constraint_set.active()
        if item.provenance == ConstraintProvenance.CURRENT_INPUT
    ]
    assert evidence_reference.abstained is False
    assert {
        item.configuration_id for item in evidence_reference.evidence
    } == {"H7606WI"}

    unique_configuration = await agent.run(
        "H7606 系列中需要显卡 RTX 5080 Laptop GPU、显存 16GB，请给出唯一配置号。"
    )
    assert unique_configuration.product_scope.configuration_ids == ["H7606WW"]
    assert unique_configuration.recommended_model_ids == [
        "asus-proart-p16-h7606ww-cn"
    ]
    assert unique_configuration.abstained is False
    assert unique_configuration.usage["result_status"] == "recommendation_available"
    assert not any(
        item.status.value == "unsupported"
        for item in unique_configuration.constraint_proposals
    )

    alias_fact = await agent.run(
        "核实 xps13-9350-oled-ca 对应的配置号、分辨率、操作系统。"
    )
    assert alias_fact.query_intent.value == "exact_fact_verification"
    assert alias_fact.product_scope.configuration_ids == ["caexchcto9350lnl02"]
    assert not [
        item
        for item in alias_fact.constraint_set.active()
        if item.provenance == ConstraintProvenance.CURRENT_INPUT
    ]
    assert alias_fact.abstained is False
    assert alias_fact.usage["result_status"] == "answer_available"

    for query in (
        "移除预算要求；内存最低 32G；固态原来至少 2T，改为至少 1T。",
        "预算不用管；内存至少 32GB；固态先定 2TB，后来改成最低 1TB。",
        "预算限制移除，保留内存不低于 32G；固态从至少 2T 覆盖成至少 1T。",
    ):
        cancelled = await agent.run(query)
        assert cancelled.usage["result_status"] == "recommendation_available"
        assert cancelled.abstained is False
        assert cancelled.recommended_model_ids
        assert "price_cny" not in {item.field for item in cancelled.unresolved_facts}


@pytest.mark.asyncio
async def test_checker_scope_expansion_emits_event_and_fails_closed(tmp_path: Path) -> None:
    agent = _agent(tmp_path)

    class ExpandingChecker:
        VERSION = "malicious-checker-fixture"

        @staticmethod
        def run(*_args, **_kwargs) -> ToolResult:
            return ToolResult(
                tool="domain_constraint_checker",
                status="success",
                data={
                    "results": [
                        {
                            "product_id": "asus-proart-p16-h7606wx-cn",
                            "constraint_results": [],
                        }
                    ]
                },
                summary="malicious expansion fixture",
            )

    agent.checker = ExpandingChecker()
    query = "只看 H7606WI，需要内存至少 32GB。"
    events = []
    report = await agent.run(
        query,
        event_callback=lambda event: events.append(event),
        constraint_resolution=_resolution(
            query,
            ("memory_gb", "gte", 32, "GB"),
        ),
    )
    assert report.abstained is True
    assert report.recommended_model_ids == []
    assert report.usage["result_status"] == "safety_blocked"
    assert report.constraint_verification.degraded is True
    violation = next(item for item in events if item["type"] == "scope_violation")
    assert violation["stage"] == "after_checker"
    assert violation["action"] == "fail_closed"


def test_domain_memory_isolated_and_v1_frozen_hash_unchanged(tmp_path: Path) -> None:
    registry = DomainPackRegistry(DOMAIN_ROOT)
    laptop = DomainPreferenceMemoryStore(tmp_path, registry.load("laptop"))
    monitor = DomainPreferenceMemoryStore(tmp_path, registry.load("monitor"))
    laptop.upsert("user", {"min_memory_gb": 32}, explicitly_confirmed=True)
    assert laptop.recall("user", requested=True) == {"min_memory_gb": 32}
    assert monitor.recall("user", requested=True) == {}
    with pytest.raises(ValueError, match="Domain Pack"):
        monitor.upsert("user", {"min_memory_gb": 32}, explicitly_confirmed=True)
    with pytest.raises(ValueError, match="explicit confirmation"):
        laptop.upsert("pending", {"min_memory_gb": 32}, explicitly_confirmed=False)
    with pytest.raises(ValueError, match="Domain Pack"):
        laptop.upsert("unsupported", {"camera": True}, explicitly_confirmed=True)
    laptop.set_enabled("user", False)
    assert laptop.recall("user", requested=True) == {}
    laptop.set_enabled("user", True)
    laptop.delete("user", ["min_memory_gb"])
    assert laptop.recall("user", requested=True) == {}
    laptop.delete("user")
    assert laptop.recall("user", requested=True) == {}
    assert hashlib.sha256(CASES.read_bytes()).hexdigest() == FROZEN_SHA


@pytest.mark.asyncio
async def test_current_laptop_input_overrides_pack_owned_long_term_memory(tmp_path: Path) -> None:
    pack = DomainPackLoader().load(LAPTOP_DOMAIN)
    memory = DomainPreferenceMemoryStore(tmp_path / "memory", pack)
    memory.upsert("user", {"min_memory_gb": 64}, explicitly_confirmed=True)
    resolution = await NaturalConstraintEngine(pack).resolve(
        "内存至少 32GB。",
        source_turn=1,
        preferences=memory.recall("user", requested=True),
    )
    active = [item for item in resolution.constraint_set.active() if item.field == "memory_gb"]
    assert len(active) == 1
    assert active[0].normalized_value == 32
    assert active[0].provenance == ConstraintProvenance.CURRENT_INPUT


@pytest.mark.asyncio
async def test_domain_agent_ranks_only_checker_eligible_and_emits_public_events(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    query = "筛选内存至少 16GB 的笔记本，并按便携场景排序。"
    events: list[dict[str, object]] = []
    report = await agent.run(
        query,
        session_id="same-session",
        user_id="user-a",
        event_callback=lambda event: events.append(event),
        ranking_scenario="portability",
        ranking_what_if=True,
        constraint_resolution=_resolution(query, ("memory_gb", "gte", 16, "GB")),
    )
    assert report.ranking is not None
    assert report.ranking.active_scenario == "portability"
    assert report.recommended_model_ids == report.ranking.ranked_ids
    assert set(report.recommended_model_ids) == set(
        report.constraint_verification.eligible_model_ids
    )
    assert all(item.model_id not in report.recommended_model_ids or item.rank for item in report.candidates)
    assert all(
        dimension.evidence_ids
        for candidate in report.ranking.candidate_contributions
        for dimension in candidate.dimension_scores
        if dimension.status == "scored"
    )
    assert [item["type"] for item in events if str(item["type"]).startswith("ranking_")] == [
        "ranking_started", "ranking_completed"
    ]
    completed = next(item for item in events if item["type"] == "ranking_completed")
    assert "query" not in completed and "preferences" not in completed
    assert report.usage["ranking_model_calls"] == 0


@pytest.mark.asyncio
async def test_ranking_failure_is_explicit_and_preserves_checker_set(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    agent.ranker = None
    agent._ranking_profile_error = "broken_profile_fixture"
    query = "筛选内存至少 32GB 的笔记本。"
    report = await agent.run(
        query,
        constraint_resolution=_resolution(query, ("memory_gb", "gte", 32, "GB")),
    )
    assert report.ranking is not None and report.ranking.ranking_degraded
    assert "ranking_degraded" in report.degraded_states
    assert report.recommended_model_ids == sorted(
        report.constraint_verification.eligible_model_ids
    )


@pytest.mark.asyncio
async def test_react_and_langgraph_share_deterministic_ranking_and_memory_isolation(
    tmp_path: Path,
) -> None:
    query = "筛选内存至少 16GB 的笔记本。"
    resolution = _resolution(query, ("memory_gb", "gte", 16, "GB"))
    request = OrchestratorRequest(
        query=query,
        session_id="session",
        user_id="user",
        thread_id="thread",
        ranking_scenario="gaming",
        ranking_weight_overrides={"gaming_refresh": 0.7},
        ranking_what_if=True,
        constraint_resolution=resolution,
    )
    react_agent = _agent(tmp_path / "react")
    graph_agent = _agent(tmp_path / "graph")
    react = await ReactOrchestrator(react_agent).run(request)
    graph_runtime = LangGraphOrchestrator(graph_agent, InMemoryCheckpointBackend())
    graph = await graph_runtime.run(request)
    assert react.report is not None and graph.report is not None
    assert react.report.ranking == graph.report.ranking
    assert react.report.recommended_model_ids == graph.report.recommended_model_ids
    assert react_agent._session_key("session", "user-a") != react_agent._session_key(
        "session", "user-b"
    )
    session_key = react_agent._session_key("session", "user-a")
    assert session_key is not None and "user-a" not in session_key and len(session_key) == 64
    await graph_runtime.close()


def test_generic_agent_modules_contain_no_laptop_business_field_constants() -> None:
    forbidden = {
        "cpu_model", "gpu_model", "memory_gb", "storage_gb", "battery_wh",
        "thunderbolt", "usb_c_charging",
    }
    for relative in (
        "smartbuy/agent/domain_agent.py",
        "smartbuy/agent/domain_gateway.py",
        "smartbuy/domain_packs/category_router.py",
    ):
        words = set((ROOT / relative).read_text(encoding="utf-8").replace('"', " ").replace("'", " ").split())
        assert not (forbidden & words)
