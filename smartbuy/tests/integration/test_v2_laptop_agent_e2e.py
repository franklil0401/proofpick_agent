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
    report = await agent.run(
        query,
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
    assert (
        react_result.report.constraint_verification.candidate_pool_model_ids
        == graph_result.report.constraint_verification.candidate_pool_model_ids
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


def test_domain_memory_isolated_and_v1_frozen_hash_unchanged(tmp_path: Path) -> None:
    registry = DomainPackRegistry(DOMAIN_ROOT)
    laptop = DomainPreferenceMemoryStore(tmp_path, registry.load("laptop"))
    monitor = DomainPreferenceMemoryStore(tmp_path, registry.load("monitor"))
    laptop.upsert("user", {"min_memory_gb": 32}, explicitly_confirmed=True)
    assert laptop.recall("user", requested=True) == {"min_memory_gb": 32}
    assert monitor.recall("user", requested=True) == {}
    with pytest.raises(ValueError, match="Domain Pack"):
        monitor.upsert("user", {"min_memory_gb": 32}, explicitly_confirmed=True)
    laptop.delete("user")
    assert laptop.recall("user", requested=True) == {}
    assert hashlib.sha256(CASES.read_bytes()).hexdigest() == FROZEN_SHA


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
