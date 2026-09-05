"""Offline fictional-catalog regressions for Domain fact execution closure."""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from smartbuy.agent import DomainDecisionAgent
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.memory import DomainPreferenceMemoryStore
from smartbuy.tools import ToolResult
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainProductQueryTool,
)


ROOT = Path(__file__).resolve().parents[3]


class FictionalRepository:
    def __init__(self, pack, *, conflict=False):
        self.domain_pack = pack
        self.snapshot = SimpleNamespace(data_version="fictional-facts-v1")
        self.products = {}
        for number in (110, 220):
            product_id = f"axiom-orbit-q{number}-us"
            attributes = {
                "family_id": "axiom-orbit", "configuration_id": f"AX-Q{number}-US",
                "part_number": f"AX{number}", "memory_gb": 32, "storage_gb": 1024,
                "region": "US", "model_name": f"Axiom Orbit Q{number}",
                "weight_kg": 1.4, "battery_wh": 72,
            }
            product = {
                "product_id": product_id, "domain_id": "laptop", "brand": "Axiom",
                "model_name": attributes["model_name"], "region": "US",
                "variant_key": f"q{number}-us", "attributes": attributes, "aliases": [],
                "evidence": [],
            }
            for field, value in attributes.items():
                product["evidence"].append({
                    "evidence_id": f"ev-{number}-{field}", "source_id": f"src-{number}",
                    "source_url": f"https://example.invalid/us/q{number}/specifications",
                    "source_type": "official_product", "field_id": field,
                    "normalized_value": value, "region": "US", "variant_key": product["variant_key"],
                    "observed_at": "2026-09-01T00:00:00Z",
                })
            if conflict and number == 110:
                conflicting = copy.deepcopy(next(row for row in product["evidence"] if row["field_id"] == "memory_gb"))
                conflicting.update(evidence_id="ev-conflict-memory", source_id="src-conflict-memory", normalized_value=64)
                product["evidence"].append(conflicting)
            self.products[product_id] = product

    def load(self):
        return copy.deepcopy(self.products)


class ControlledEvidence(DomainEvidenceCheckTool):
    def __init__(self, repository, behavior="success"):
        super().__init__(repository)
        self.behavior = behavior
        self.calls = []

    def run(self, product_id, constraints, *, scope=None):
        self.calls.append((product_id, tuple(item["field"] for item in constraints)))
        if self.behavior == "raises":
            raise RuntimeError("PRIVATE_FIXTURE_ERROR")
        if self.behavior == "failed":
            return ToolResult(tool="domain_evidence_check", status="failed", summary="fixture unavailable", error_code="fixture_failure")
        result = super().run(product_id, constraints, scope=scope)
        if self.behavior == "missing_field" and product_id.endswith("q220-us"):
            result.data["field_results"] = [row for row in result.data["field_results"] if row["field_id"] != "storage_gb"]
        if self.behavior == "unknown":
            for row in result.data["field_results"]:
                row.update(state="unknown", actual_value=None, evidence_ids=[], source_ids=[], reason="missing_governed_evidence")
        if self.behavior == "wrong_identity":
            result.data["product_id"] = "outside-scope-product"
        return result


def _agent(tmp_path, *, behavior="success", conflict=False, max_tool_calls=12):
    pack = DomainPackLoader().load(ROOT / "smartbuy/domain_packs/laptop")
    repository = FictionalRepository(pack, conflict=conflict)
    evidence = ControlledEvidence(repository, behavior)
    agent = DomainDecisionAgent(
        pack, repository, DomainProductQueryTool(repository), evidence,
        DomainConstraintCheckerTool(repository), NaturalConstraintEngine(pack),
        DomainPreferenceMemoryStore(tmp_path / "memory", pack), max_tool_calls=max_tool_calls,
    )
    return agent, evidence


@pytest.mark.asyncio
async def test_domain_failed_check_cannot_recreate_verified_facts_from_catalog(tmp_path):
    agent, _ = _agent(tmp_path, behavior="failed")
    report = await agent.run("核验 AX-Q110-US 的内存和存储。")
    assert all(row.status.value == "unknown" for row in report.candidates[0].fields)
    assert report.abstained
    assert {row["status"] for row in report.usage["fact_completion"]["matrix"]} == {"tool_failed"}


@pytest.mark.asyncio
async def test_domain_comparison_requires_every_product_and_requested_field(tmp_path):
    agent, evidence = _agent(tmp_path, behavior="missing_field")
    report = await agent.run("比较 AX-Q110-US 和 AX-Q220-US 的内存和存储。")
    assert report.abstained
    assert report.recommended_model_ids == []
    assert not any(row.eligible for row in report.candidates)
    completion = report.usage["fact_completion"]
    assert completion["completion_status"] == "partial"
    assert any(row["product_id"].endswith("q220-us") and row["field"] == "storage_gb" and row["status"] == "not_checked" for row in completion["matrix"])
    assert len(evidence.calls) == len({row[0] for row in evidence.calls}) == 2


@pytest.mark.asyncio
async def test_domain_checked_unknown_is_complete_but_not_answer_sufficient(tmp_path):
    agent, _ = _agent(tmp_path, behavior="unknown")
    report = await agent.run("核验 AX-Q110-US 的内存。")
    assert report.abstained
    assert report.candidates[0].fields[0].status.value == "unknown"
    completion = report.usage["fact_completion"]
    assert completion["completion_status"] == "complete"
    assert not completion["answer_sufficient"]
    assert {row["status"] for row in completion["matrix"]} == {"verified_unknown"}


@pytest.mark.asyncio
async def test_domain_real_bilateral_conflict_is_not_overwritten_by_attribute(tmp_path):
    agent, _ = _agent(tmp_path, conflict=True)
    report = await agent.run("核验 AX-Q110-US 的内存。")
    assert report.abstained
    field = report.candidates[0].fields[0]
    assert field.status.value == "conflict"
    assert set(field.actual_value) == {32, 64}
    assert {row.evidence_id for row in field.evidence} == {"ev-110-memory_gb", "ev-conflict-memory"}
    assert report.usage["fact_completion"]["completion_status"] == "complete"


@pytest.mark.asyncio
async def test_domain_budget_omission_is_not_confirmed_missing_evidence(tmp_path):
    agent, evidence = _agent(tmp_path, max_tool_calls=1)
    report = await agent.run("比较 AX-Q110-US 和 AX-Q220-US 的内存和存储。")
    assert report.abstained
    assert not report.recommended_model_ids
    assert report.usage["fact_completion"]["completion_status"] != "complete"
    assert "budget_exhausted" in {row["status"] for row in report.usage["fact_completion"]["matrix"]}
    assert len(evidence.calls) <= 1


@pytest.mark.asyncio
async def test_domain_complete_comparison_has_no_purchase_eligibility(tmp_path):
    agent, evidence = _agent(tmp_path)
    report = await agent.run("比较 AX-Q110-US 和 AX-Q220-US 的内存和存储。")
    assert not report.abstained
    assert report.recommended_model_ids == []
    assert not any(row.eligible for row in report.candidates)
    assert report.usage["fact_completion"]["completion_status"] == "complete"
    assert report.usage["fact_completion"]["answer_sufficient"]
    assert len(evidence.calls) == 2


@pytest.mark.asyncio
async def test_domain_tool_identity_mismatch_is_not_usable_fact(tmp_path):
    agent, _ = _agent(tmp_path, behavior="wrong_identity")
    report = await agent.run("核验 AX-Q110-US 的内存。")
    assert report.abstained
    assert all(row.status.value == "unknown" for row in report.candidates[0].fields)
    assert report.usage["fact_completion"]["completion_status"] != "complete"


@pytest.mark.asyncio
async def test_domain_ordered_only_fields_are_checked_without_purchase_constraints(tmp_path):
    agent, _ = _agent(tmp_path)
    report = await agent.run("核验 AX-Q110-US 的重量和电池容量。")
    assert not report.abstained
    assert report.constraint_set.active(hard_only=True, supported_only=True) == []
    assert report.usage["fact_completion"]["completion_status"] == "complete"
    assert {row.field for row in report.candidates[0].fields} == {"weight_kg", "battery_wh"}


@pytest.mark.asyncio
async def test_domain_fact_tool_exception_has_safe_incomplete_terminal(tmp_path):
    agent, _ = _agent(tmp_path, behavior="raises")
    report = await agent.run("核验 AX-Q110-US 的内存。")
    assert report.abstained
    assert report.usage["fact_completion"]["completion_status"] == "incomplete"
    assert report.usage["fact_completion"]["matrix"][0]["status"] == "tool_failed"
    assert "PRIVATE_FIXTURE_ERROR" not in report.model_dump_json()
