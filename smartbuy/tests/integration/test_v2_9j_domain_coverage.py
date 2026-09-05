"""Offline product-path regressions for missing or unresolved domain quantities."""

from pathlib import Path

import pytest

from smartbuy.agent import DomainDecisionAgent
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.memory import DomainPreferenceMemoryStore
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)


ROOT = Path(__file__).resolve().parents[3]


def _agent(tmp_path, domain):
    domain_path = ROOT / "smartbuy/domain_packs" / domain
    pack_path = ROOT / "smartbuy/product_packs/examples" / f"{domain}-v1/pack.json"
    pack = DomainPackLoader().load(domain_path)
    manager = DomainProductPackManager(tmp_path / "runtime", domain_pack_path=domain_path)
    snapshot = manager.publish(manager.stage(pack_path).data_version)
    repository = DomainReadonlyRepository(snapshot, pack)
    return DomainDecisionAgent(
        pack, repository, DomainProductQueryTool(repository),
        DomainEvidenceCheckTool(repository), DomainConstraintCheckerTool(repository),
        NaturalConstraintEngine(pack), DomainPreferenceMemoryStore(tmp_path / "memory", pack),
    )


def _forbid_tools(monkeypatch, agent):
    def fail(*args, **kwargs):
        raise AssertionError("unresolved explicit requirement reached a tool")

    monkeypatch.setattr(agent.product_query, "run", fail)
    monkeypatch.setattr(agent.evidence_check, "run", fail)
    monkeypatch.setattr(agent.checker, "run", fail)


@pytest.mark.asyncio
@pytest.mark.parametrize("domain, query, missing_field", [
    ("laptop", "筛选笔记本：内存至少32GB，重量最多1.55kg。", "weight_kg"),
    ("headphone", "筛选耳机：重量最多250克，蓝牙版本至少5.0。", "weight_g"),
])
async def test_missing_domain_constraint_stops_before_tools(tmp_path, monkeypatch, domain, query, missing_field):
    agent = _agent(tmp_path, domain)
    resolution = await agent.constraint_engine.resolve(query, source_turn=1)
    constraints = resolution.constraint_set.model_copy(update={
        "constraints": [item for item in resolution.constraint_set.constraints if item.field != missing_field],
    })
    resolution = resolution.model_copy(update={"constraint_set": constraints})
    _forbid_tools(monkeypatch, agent)
    report = await agent.run(query, constraint_resolution=resolution)
    assert report.clarification_state.value == "pending"
    assert report.recommended_model_ids == []
    assert report.tool_call_count == 0
    assert report.usage["provider_calls"] == 0
    assert report.usage["requirement_coverage"]["complete"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("domain, query", [
    ("laptop", "筛选笔记本：内存至少32GB，重量最多3stones。"),
    ("headphone", "筛选耳机：蓝牙版本至少5.0，重量最多3stones。"),
])
async def test_unsupported_quantity_unit_pauses_in_domain_path(tmp_path, monkeypatch, domain, query):
    agent = _agent(tmp_path, domain)
    _forbid_tools(monkeypatch, agent)
    report = await agent.run(query)
    assert report.clarification_state.value == "pending"
    assert not report.recommended_model_ids
    assert report.tool_call_count == 0
    assert report.usage["provider_calls"] == 0
    assert report.usage["requirement_coverage"]["complete"] is False


@pytest.mark.asyncio
async def test_fact_fields_are_not_domain_purchase_obligations(tmp_path):
    agent = _agent(tmp_path, "headphone")
    report = await agent.run("QCUE2-BLACK-US 的重量是多少克？")
    assert report.constraint_set.active(hard_only=True) == []
    assert report.usage["requirement_coverage"] == {
        "version": "input-requirement-coverage-v1", "complete": True, "obligations": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "筛选耳机，必须支持光子接口。",
    "筛选耳机，重量小于250g。",
    "筛选耳机，重量<250g。",
])
async def test_explicit_unknown_field_and_strict_boundary_pause_before_tools(tmp_path, monkeypatch, query):
    agent = _agent(tmp_path, "headphone")
    _forbid_tools(monkeypatch, agent)
    report = await agent.run(query)
    assert report.clarification_state.value == "pending"
    assert report.recommended_model_ids == [] and report.tool_call_count == 0
    assert report.usage["provider_calls"] == 0


@pytest.mark.asyncio
async def test_validated_override_is_audited_without_reactivating_old_value(tmp_path):
    from smartbuy.decision_core.requirements import audit_requirement_coverage

    agent = _agent(tmp_path, "laptop")
    query = "内存至少32GB，存储先至少2TB，改为至少1TB。"
    resolution = await agent.constraint_engine.resolve(query, source_turn=1)
    coverage = audit_requirement_coverage(query, resolution.constraint_set, agent.pack, purchase=True, resolution=resolution)
    assert coverage.complete
    assert any(item.get("superseded") and item["value"] == 2048.0 for item in coverage.obligations)
    without_proof = audit_requirement_coverage(query, resolution.constraint_set, agent.pack, purchase=True)
    assert not without_proof.complete


@pytest.mark.asyncio
async def test_known_nonnumeric_hard_field_cannot_be_dropped(tmp_path, monkeypatch):
    agent = _agent(tmp_path, "headphone")
    query = "筛选耳机，必须支持主动降噪。"
    resolution = await agent.constraint_engine.resolve(query, source_turn=1)
    constraints = resolution.constraint_set.model_copy(update={"constraints": []})
    resolution = resolution.model_copy(update={"constraint_set": constraints})
    _forbid_tools(monkeypatch, agent)
    report = await agent.run(query, constraint_resolution=resolution)
    assert report.clarification_state.value == "pending"
    assert report.tool_call_count == 0 and not report.recommended_model_ids
