"""V2-8 shared toolchain, ranking and memory checks for Headphone."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from smartbuy.agent import DomainDecisionAgent
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.constraint_proposals.models import ProposalStatus
from smartbuy.domain_packs import DomainPackLoader, DomainPackRegistry
from smartbuy.memory import DomainPreferenceMemoryStore
from smartbuy.orchestration.checkpoints import InMemoryCheckpointBackend
from smartbuy.orchestration.contracts import OrchestratorRequest
from smartbuy.orchestration.langgraph_adapter import LangGraphOrchestrator
from smartbuy.orchestration.react_adapter import ReactOrchestrator
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.providers.bailian import BailianError, ProviderResult
from smartbuy.ranking import (
    DeterministicDecisionRanker,
    RankingCandidateInput,
    RankingEvidence,
    RankingProfileLoader,
    RankingRequest,
)
from smartbuy.retrieval.domain_index import DomainIndexManager
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainKBSearchTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)


ROOT = Path(__file__).resolve().parents[3]
DOMAIN_ROOT = ROOT / "smartbuy" / "domain_packs"
HEADPHONE_DOMAIN = DOMAIN_ROOT / "headphone"
HEADPHONE_PACK = ROOT / "smartbuy" / "product_packs" / "examples" / "headphone-v1" / "pack.json"


class FakeProvider:
    def __init__(self, *, fail_rerank: bool = False) -> None:
        self.fail_rerank = fail_rerank

    @staticmethod
    def _vector(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        return [float(digest[index % len(digest)]) / 255.0 for index in range(1024)]

    async def embed(self, texts):
        return ProviderResult([self._vector(text) for text in texts], 1, 1.0, {"input_tokens":len(texts)})

    async def rerank(self, _query, documents, *, top_n, instruct=None):
        del instruct
        if self.fail_rerank:
            raise BailianError("injected")
        return ProviderResult(
            [{"index":index,"relevance_score":1-index/100} for index in range(min(top_n,len(documents)))],
            1,1.0,{"input_tokens":len(documents)},
        )


async def _runtime(tmp_path: Path, *, fail_rerank: bool = False):
    pack = DomainPackLoader().load(HEADPHONE_DOMAIN)
    manager = DomainProductPackManager(tmp_path / "data", domain_pack_path=HEADPHONE_DOMAIN)
    snapshot = manager.publish(manager.stage(HEADPHONE_PACK).data_version)
    repository = DomainReadonlyRepository(snapshot, pack)
    provider = FakeProvider(fail_rerank=fail_rerank)
    index_manager = DomainIndexManager(
        tmp_path / "index", data_manager=manager, domain_id="headphone", domain_pack_version=pack.version
    )
    index = await index_manager.build(snapshot.data_version, "headphone-fake-index-v1", provider, batch_size=10)
    index_manager.activate(index.index_version)
    return pack, snapshot, repository, provider, index_manager


@pytest.mark.asyncio
async def test_four_generic_tools_complete_headphone_decision_loop(tmp_path: Path) -> None:
    _, _, repository, provider, index_manager = await _runtime(tmp_path)
    constraints = [
        {"field":"wireless_dongle","operator":"eq","value":True},
        {"field":"supported_platforms","operator":"contains_all","value":["Xbox"]},
    ]
    query = DomainProductQueryTool(repository).run(constraints)
    matched = [row["product_id"] for row in query.data["rows"] if row["status"] == "matched"]
    assert matched == [
        "logitech-astro-a50x-black-us",
        "steelseries-arctis-nova-pro-wireless-xbox-us",
    ]
    kb = await DomainKBSearchTool(index_manager, provider).run(
        "NOVA-PRO-WL-XBOX-B-US Xbox 配置", configuration_id="NOVA-PRO-WL-XBOX-B-US"
    )
    assert kb.status == "success"
    assert {hit["product_id"] for hit in kb.data["hits"]} == {
        "steelseries-arctis-nova-pro-wireless-xbox-us"
    }
    evidence = DomainEvidenceCheckTool(repository).run(matched[0], constraints)
    assert evidence.status == "success"
    assert {row["state"] for row in evidence.data["field_results"]} == {"matched"}
    checker = DomainConstraintCheckerTool(repository).run(constraints, candidate_ids=matched)
    assert checker.status == "success"
    assert {item["product_id"] for item in checker.data["results"] if item["eligible"]} == set(matched)
    assert checker.data["candidate_pool_size"] == 2


@pytest.mark.asyncio
async def test_reranker_failure_uses_vector_order_and_marks_degraded(tmp_path: Path) -> None:
    _, _, _, provider, index_manager = await _runtime(tmp_path, fail_rerank=True)
    result = await DomainKBSearchTool(index_manager, provider).run("Sony WF-1000XM5 IPX4")
    assert result.status == "degraded"
    assert result.degraded is True and result.data["reranker_degraded"] is True
    assert result.data["hits"]
    assert all(hit["domain_id"] == "headphone" for hit in result.data["hits"])


def _ranking_candidates(repository: DomainReadonlyRepository) -> list[RankingCandidateInput]:
    products = repository.load()
    return [
        RankingCandidateInput(
            product_id=product_id,
            configuration_id=product["attributes"]["configuration_id"],
            region=product["region"],
            values=dict(product["attributes"]),
            evidence=[
                RankingEvidence(
                    evidence_id=row["evidence_id"],source_id=row["source_id"],
                    source_type=row["source_type"],field_id=row["field_id"],
                    normalized_value=row["normalized_value"],region=row["region"],
                ) for row in product["evidence"]
            ],
        ) for product_id, product in products.items()
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("baseline","what_if"),
    [
        ("commute","meeting"),("commute","gaming"),("commute","music"),
        ("meeting","gaming"),("meeting","music"),("gaming","music"),
        ("music","commute"),("gaming","commute"),
    ],
)
async def test_eight_headphone_what_if_tasks_change_order_not_checker_set(
    tmp_path: Path, baseline: str, what_if: str
) -> None:
    pack, snapshot, repository, _, _ = await _runtime(tmp_path)
    candidates = _ranking_candidates(repository)
    profile = RankingProfileLoader.load(pack)
    ranker = DeterministicDecisionRanker(profile)

    def request(scenario: str) -> RankingRequest:
        return RankingRequest(
            domain_id="headphone",scenario=scenario,eligible_candidates=candidates,
            checker_eligible_ids=[item.product_id for item in candidates],
            explicit_preferences={"ranking_scenario":scenario},
            ranking_profile_version=profile.profile.profile_version,
            data_version=snapshot.data_version,domain_pack_version=pack.version,what_if=True,
        )

    first = ranker.rank(request(baseline))
    second = ranker.rank(request(what_if))
    assert set(first.ranked_ids) == set(second.ranked_ids) == {item.product_id for item in candidates}
    assert first.ranked_ids != second.ranked_ids
    assert all(
        dimension.evidence_ids
        for result in (first, second)
        for candidate in result.candidate_contributions
        for dimension in candidate.dimension_scores
        if dimension.status == "scored"
    )
    assert ranker.canonical_bytes(second) == ranker.canonical_bytes(ranker.rank(request(what_if)))


def test_headphone_memory_lifecycle_and_three_domain_isolation(tmp_path: Path) -> None:
    registry = DomainPackRegistry(DOMAIN_ROOT)
    headphone = DomainPreferenceMemoryStore(tmp_path, registry.load("headphone"))
    monitor = DomainPreferenceMemoryStore(tmp_path, registry.load("monitor"))
    laptop = DomainPreferenceMemoryStore(tmp_path, registry.load("laptop"))
    preferences = {
        "preferred_form_factor":"over_ear","preferred_codec":["LDAC"],
        "preferred_platform":["PS5"],"max_weight_g":300,"anc_preference":True,
    }
    with pytest.raises(ValueError, match="explicit confirmation"):
        headphone.upsert("user", preferences, explicitly_confirmed=False)
    headphone.upsert("user", preferences, explicitly_confirmed=True)
    assert headphone.recall("user", requested=True) == preferences
    assert monitor.recall("user", requested=True) == {}
    assert laptop.recall("user", requested=True) == {}
    for forbidden in ("battery_hours", "weight_g", "sound_signature", "price_cny", "stock_status"):
        with pytest.raises(ValueError, match="Domain Pack"):
            headphone.upsert("blocked", {forbidden:1}, explicitly_confirmed=True)
    headphone.upsert("user", {"max_weight_g":250}, explicitly_confirmed=True)
    assert headphone.recall("user", requested=True)["max_weight_g"] == 250
    headphone.set_enabled("user",False)
    assert headphone.recall("user",requested=True) == {}
    headphone.set_enabled("user",True)
    headphone.delete("user",["max_weight_g"])
    assert "max_weight_g" not in headphone.recall("user",requested=True)
    headphone.delete("user")
    assert headphone.recall("user",requested=True) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query","expected_field","expected_status"),
    [
        ("必须支持LDAC。","supported_codecs",ProposalStatus.SUPPORTED),
        ("重量不要超过250克。","weight_g",ProposalStatus.SUPPORTED),
        ("必须支持PS5。","supported_platforms",ProposalStatus.SUPPORTED),
        ("不要入耳式。","wearing_style",ProposalStatus.SUPPORTED),
        ("想要通勤降噪好一点的。","active_noise_cancellation",ProposalStatus.SUPPORTED),
        ("最好能同时连电脑和手机。","multipoint",ProposalStatus.SUPPORTED),
        ("打游戏延迟不能太高。","measured_latency_ms",ProposalStatus.AMBIGUOUS),
        ("主要听流行，不要低频太轰。","sound_signature",ProposalStatus.AMBIGUOUS),
    ],
)
async def test_headphone_natural_constraints_are_pack_driven(
    query: str, expected_field: str, expected_status: ProposalStatus
) -> None:
    pack = DomainPackLoader().load(HEADPHONE_DOMAIN)
    resolution = await NaturalConstraintEngine(pack).resolve(query,source_turn=1)
    proposal = next(item for item in resolution.proposals if item.field == expected_field)
    assert proposal.status == expected_status
    assert proposal.active is (expected_status == ProposalStatus.SUPPORTED)
    if expected_status != ProposalStatus.SUPPORTED:
        assert proposal.proposal_id in resolution.pending_proposal_ids


@pytest.mark.asyncio
async def test_headphone_pack_driven_cancel_does_not_enter_checker_or_memory(tmp_path: Path) -> None:
    pack = DomainPackLoader().load(HEADPHONE_DOMAIN)
    engine = NaturalConstraintEngine(pack)
    first = await engine.resolve("必须有蓝牙且重量不超过250克。",source_turn=1)
    second = await engine.resolve(
        "有线无线都可以，重量不限。",source_turn=2,previous=first.constraint_set
    )
    active_fields = {item.field for item in second.constraint_set.active()}
    assert "bluetooth" not in active_fields and "weight_g" not in active_fields
    assert {item.field for item in second.proposals if item.action.value == "cancel"} >= {
        "bluetooth","wired_connection","weight_g"
    }
    memory = DomainPreferenceMemoryStore(tmp_path / "memory",pack)
    with pytest.raises(ValueError,match="explicit confirmation"):
        memory.upsert("user",{"anc_preference":True},explicitly_confirmed=False)


async def _agent(tmp_path: Path) -> DomainDecisionAgent:
    pack, _, repository, provider, index_manager = await _runtime(tmp_path)
    return DomainDecisionAgent(
        pack,
        repository,
        DomainProductQueryTool(repository),
        DomainEvidenceCheckTool(repository),
        DomainConstraintCheckerTool(repository),
        NaturalConstraintEngine(pack),
        DomainPreferenceMemoryStore(tmp_path / "agent-memory", pack),
        kb_search=DomainKBSearchTool(index_manager, provider),
    )


@pytest.mark.asyncio
async def test_later_numeric_negation_does_not_negate_earlier_boolean(tmp_path: Path) -> None:
    report = await (await _agent(tmp_path)).run(
        "耳机：需要主动降噪，重量不要超过 250 克。",
        ranking_scenario="commute",
    )
    active = {item.field: item.normalized_value for item in report.constraint_set.active()}
    assert active["active_noise_cancellation"] is True
    assert active["weight_g"] == 250
    assert report.recommended_model_ids


@pytest.mark.asyncio
async def test_detachable_microphone_fact_maps_to_specific_pack_field(tmp_path: Path) -> None:
    report = await (await _agent(tmp_path)).run("耳机：G735-WHITE-US 的麦克风能否拆卸？")
    assert "detachable_microphone" in report.requested_fields
    assert {item.model_id for item in report.evidence} == {"logitech-g735-white-us"}
    assert "detachable_microphone" in {item.field for item in report.evidence}


@pytest.mark.asyncio
async def test_subjective_microphone_quality_requires_clarification(tmp_path: Path) -> None:
    report = await (await _agent(tmp_path)).run("耳机：开会用，麦克风要清楚。")
    assert report.clarification_state.value == "pending"
    assert report.recommended_model_ids == []
    assert any(item.field == "call_quality_observation" for item in report.constraint_proposals)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "query"),
    [
        ("filter", "耳机：必须支持 LDAC 且重量不超过 300 克。"),
        ("configuration", "耳机：核验 NOVA-PRO-WL-XBOX-B-US 是否支持 Xbox。"),
        ("clarify", "耳机：开会用，麦克风要清楚。"),
    ],
)
async def test_headphone_react_and_langgraph_keep_identical_eligibility(
    tmp_path: Path,
    case_id: str,
    query: str,
) -> None:
    react = ReactOrchestrator(await _agent(tmp_path / f"react-{case_id}"))
    graph = LangGraphOrchestrator(
        await _agent(tmp_path / f"graph-{case_id}"),
        InMemoryCheckpointBackend(),
    )
    request = OrchestratorRequest(
        query=query,
        session_id=f"session-{case_id}",
        thread_id=f"thread-{case_id}",
    )
    left = await react.run(request)
    right = await graph.run(request)
    assert left.report is not None and right.report is not None
    assert left.report.product_scope == right.report.product_scope
    assert (
        left.report.constraint_verification.eligible_model_ids
        == right.report.constraint_verification.eligible_model_ids
    )
    assert left.report.recommended_model_ids == right.report.recommended_model_ids
    assert left.report.clarification_state == right.report.clarification_state
    await graph.close()
