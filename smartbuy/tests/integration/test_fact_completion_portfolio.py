"""Offline development regressions for the public Portfolio fact-completion contract.

The fixture catalog is fictional. SQLite, Evidence Check, Checker and the
documented default Monitor API path are real; model and KB calls are fake.
No independent evaluation inputs, gold answers or runner are used here.
"""

from __future__ import annotations

import asyncio
import copy
import json
import sqlite3

import pytest

from smartbuy.tests.integration import test_v2_9j_portfolio_contracts as shared_fixture
from smartbuy.tests.integration.test_v2_9j_portfolio_contracts import (
    MODEL_IDS,
    GovernedFakeKB,
    OverbroadEvidence,
    RecordingEvidence,
    api,
    tool_call,
)
from smartbuy.tools import ToolResult


FIELDS = ["width_mm", "refresh_rate_hz"]


@pytest.fixture(name="synthetic_database")
def _synthetic_database(tmp_path):
    return shared_fixture.synthetic_database.__wrapped__(tmp_path)


@pytest.fixture(name="portfolio_client")
def _portfolio_client(monkeypatch, tmp_path, synthetic_database):
    yield from shared_fixture.portfolio_client.__wrapped__(monkeypatch, tmp_path, synthetic_database)


def _script(*, models=None, fields=None, comparison=False, sql=False, evidence=False, direct_finish=False):
    models = list(models or [MODEL_IDS[0]])
    fields = list(fields or FIELDS)
    messages = [tool_call("set_requirements", {
        "summary": "核验明确配置的已治理事实，不做购买推荐",
        "task_type": "comparison" if comparison else "fact",
        "hard_constraints": [{"field": "model_id", "operator": "in", "value": models}],
        "soft_preferences": [], "required_fields": fields,
        "excluded_model_ids": [], "pending_questions": [],
    })]
    if sql:
        messages.append(tool_call("text2sql", {
            "sql": "SELECT model_id FROM products", "filters": [], "reason": "读取指定配置",
        }))
    if not direct_finish:
        messages.append(tool_call("kb_search", {
            "query": "核验指定配置的宽度和刷新率", "model_ids": models,
            "required_fields": fields, "reason": "读取事实证据", "parent_step": 1,
        }))
    if evidence:
        messages.append(tool_call("evidence_check", {
            "model_ids": models, "required_fields": fields, "constraints": [],
            "reason": "检查指定字段", "parent_step": 2,
        }))
    messages.append(tool_call("finish_decision", {"stop_reason": "完成事实查询", "pending_questions": []}))
    return messages


def _query(models=None, *, field_text="机身宽度和刷新率", comparison=False):
    reference = "、".join(models or [MODEL_IDS[0]])
    return f"{'比较' if comparison else '核验'} {reference} 的{field_text}分别是多少？仅说明事实。"


def _run(client, query):
    response = client.post("/api/smartbuy/portfolio/run", json={
        "domain_id": "monitor", "mode": "trusted", "query": query,
    })
    assert response.status_code == 200
    return response.json()["report"]


def _facts(report):
    return {(candidate["model_id"], field["field"]): field
            for candidate in report["candidates"] for field in candidate["fields"]}


def _completion(report):
    result = report["usage"].get("fact_completion")
    assert isinstance(result, dict), "Public report must disclose the product × requested-field completion audit"
    assert result.get("completion_status") in {"complete", "partial", "incomplete"}
    matrix = result.get("matrix")
    assert isinstance(matrix, (list, dict)) and matrix, "Every requested product/field needs a visible terminal state"
    return result


def _matrix_statuses(matrix):
    """Accept row-list and product/field-keyed matrix encodings, not a fixed layout."""
    if isinstance(matrix, list):
        return set().union(*(_matrix_statuses(item) for item in matrix)) if matrix else set()
    if isinstance(matrix, dict):
        statuses = {matrix["status"]} if isinstance(matrix.get("status"), str) else set()
        for value in matrix.values():
            if isinstance(value, (list, dict)):
                statuses.update(_matrix_statuses(value))
        return statuses
    return set()


def _no_purchase(report):
    assert report["recommended_model_ids"] == []
    assert not any(item.get("recommendation_reason") for item in report["candidates"])
    assert not any(item.get("eligible") for item in report["candidates"])


class RecordingKB(GovernedFakeKB):
    def __init__(self, *, only_field=None, only_model=None, wrong_identity=False):
        self.calls = []
        self.only_field = only_field
        self.only_model = only_model
        self.wrong_identity = wrong_identity

    async def invoke(self, arguments):
        self.calls.append(copy.deepcopy(arguments))
        result = await super().invoke(arguments)
        if self.only_model:
            result.data["hits"] = [hit for hit in result.data["hits"] if hit["model_id"] == self.only_model]
        for hit in result.data["hits"]:
            if self.only_field:
                hit["evidence_bindings"] = [item for item in hit["evidence_bindings"] if item["field"] == self.only_field]
            if self.wrong_identity:
                hit["region"] = "US"
                hit["data_version"] = "untrusted-other-version"
                hit["source_id"] = "wrong-region-source"
                for binding in hit["evidence_bindings"]:
                    binding["source_id"] = "wrong-region-source"
                    binding["evidence_id"] = "wrong-region-evidence"
        return result


class IncompleteEvidence(RecordingEvidence):
    def __init__(self, database, *, only_field=None, only_model=None):
        super().__init__(database)
        self.only_field = only_field
        self.only_model = only_model

    async def invoke(self, arguments):
        result = await super().invoke(arguments)
        if self.only_model:
            result.data["models"] = {
                key: value for key, value in result.data["models"].items() if key == self.only_model
            }
        if self.only_field:
            result.data["models"] = {
                key: [field for field in value if field["field"] == self.only_field]
                for key, value in result.data["models"].items()
            }
        return result


class FailedEvidence(RecordingEvidence):
    def __init__(self, database, *, timeout=False):
        super().__init__(database)
        self.timeout = timeout

    async def invoke(self, arguments):
        self.received.append(copy.deepcopy(arguments))
        if self.timeout:
            await asyncio.sleep(0.3)
        return ToolResult(tool=self.name, status="failed", error_code="FIXTURE_UNAVAILABLE",
                          summary="Offline evidence dependency unavailable", data={})


class FirstPartialEvidence(RecordingEvidence):
    """A successful first response omits one cell, the next really returns it."""

    async def invoke(self, arguments):
        result = await super().invoke(arguments)
        if len(self.received) == 1:
            result.data["models"] = {
                model: [field for field in fields if field["field"] == "refresh_rate_hz"]
                for model, fields in result.data["models"].items()
            }
        return result


class CorruptIdentityEvidence(RecordingEvidence):
    def __init__(self, database, *, identity_field):
        super().__init__(database)
        self.identity_field = identity_field

    async def invoke(self, arguments):
        result = await super().invoke(arguments)
        for assessments in result.data["models"].values():
            for assessment in assessments:
                for reference in assessment["evidence"]:
                    reference[self.identity_field] = (
                        "US" if self.identity_field == "region" else "unattested-other-identity"
                    )
        return result


class ConflictingDuplicateEvidence(RecordingEvidence):
    """Inject a duplicate returned field after a complete two-source conflict."""

    async def invoke(self, arguments):
        result = await super().invoke(arguments)
        for model_id, assessments in result.data["models"].items():
            width = next((field for field in assessments if field["field"] == "width_mm"), None)
            if width is None:
                continue
            conflict = copy.deepcopy(width)
            conflict["status"] = "conflict"
            conflict["actual_value"] = [610.0, 608.0]
            conflict["reason"] = "Two fictional governed observations disagree"
            alternative = copy.deepcopy(conflict["evidence"][0])
            alternative["evidence_id"] = "ev-duplicate-conflicting-width"
            alternative["value"] = "608.0"
            conflict["evidence"].append(alternative)
            result.data["models"][model_id] = [conflict, *assessments]
        return result


class SlowKB(RecordingKB):
    async def invoke(self, arguments):
        await asyncio.sleep(0.075)
        return await super().invoke(arguments)


def test_kb_only_fact_runs_real_field_verification_without_sql(portfolio_client):
    client, _, sql, evidence = portfolio_client(_script())
    report = _run(client, _query())
    assert sql.received == [], "A simple fact question must not acquire a SQL filtering prerequisite"
    assert evidence.received, "KB binding IDs without actual values are not verified field answers"
    facts = _facts(report)
    assert facts[(MODEL_IDS[0], "width_mm")]["actual_value"] == 610
    assert facts[(MODEL_IDS[0], "refresh_rate_hz")]["actual_value"] == 144
    assert all(facts[(MODEL_IDS[0], field)]["status"] == "matched" for field in FIELDS)
    assert _completion(report)["completion_status"] == "complete"
    assert report["abstained"] is False
    _no_purchase(report)


def test_direct_finish_cannot_claim_an_unobserved_fact_complete(portfolio_client):
    client, _, sql, evidence = portfolio_client(_script(direct_finish=True))
    report = _run(client, _query())
    completion = _completion(report)
    if completion["completion_status"] == "complete":
        assert evidence.received
        assert {(MODEL_IDS[0], field) for field in FIELDS} <= set(_facts(report))
    else:
        assert report["abstained"] is True
        assert report["unresolved_facts"]
    assert sql.received == []
    _no_purchase(report)


def test_two_fields_with_one_kb_binding_are_completed_from_governed_evidence(portfolio_client):
    kb = RecordingKB(only_field="refresh_rate_hz")
    client, _, _, evidence = portfolio_client(_script(), kb=kb)
    report = _run(client, _query())
    facts = _facts(report)
    assert set(FIELDS) <= {field for model, field in facts if model == MODEL_IDS[0]}
    assert evidence.received
    assert _completion(report)["completion_status"] == "complete"
    _no_purchase(report)


def test_missing_assessment_for_one_field_is_partial_not_complete(portfolio_client, synthetic_database):
    evidence = IncompleteEvidence(synthetic_database, only_field="refresh_rate_hz")
    client, _, _, _ = portfolio_client(_script(evidence=True), evidence_tool=evidence)
    report = _run(client, _query())
    assert report["abstained"] is True
    assert _completion(report)["completion_status"] == "partial"
    assert any(item["field"] == "width_mm" and item["reason"] for item in report["unresolved_facts"])
    _no_purchase(report)


def test_comparison_requires_each_named_product_times_each_field(portfolio_client):
    models = MODEL_IDS[:2]
    client, _, _, evidence = portfolio_client(
        _script(models=models, comparison=True, sql=True), kb=RecordingKB(only_model=models[0]),
    )
    report = _run(client, _query(models, comparison=True))
    facts = _facts(report)
    assert {(model, field) for model in models for field in FIELDS} <= set(facts)
    assert all(facts[(model, field)]["status"] == "matched" for model in models for field in FIELDS)
    assert set().union(*(set(call["model_ids"]) for call in evidence.received)) == set(models)
    assert _completion(report)["completion_status"] == "complete"
    _no_purchase(report)


def test_comparison_missing_one_evidence_side_cannot_report_full_completion(portfolio_client, synthetic_database):
    models = MODEL_IDS[:2]
    evidence = IncompleteEvidence(synthetic_database, only_model=models[0])
    client, _, _, _ = portfolio_client(
        _script(models=models, comparison=True, sql=True, evidence=True), evidence_tool=evidence,
    )
    report = _run(client, _query(models, comparison=True))
    assert report["abstained"] is True
    assert _completion(report)["completion_status"] == "partial"
    assert any(item.get("model_id") == models[1] and item["reason"] for item in report["unresolved_facts"])
    _no_purchase(report)


def test_unknown_field_stays_unknown_without_buy_recommendation(portfolio_client):
    client, _, _, _ = portfolio_client(_script(fields=["weight_kg"]))
    report = _run(client, _query(field_text="机身重量"))
    field = _facts(report)[(MODEL_IDS[0], "weight_kg")]
    assert field["status"] == "unknown" and field["actual_value"] is None
    assert field["reason"]
    assert report["abstained"] is True
    completion = _completion(report)
    assert completion["completion_status"] == "complete"
    assert "verified_unknown" in _matrix_statuses(completion["matrix"])
    _no_purchase(report)


def test_conflicting_governed_values_keep_both_evidence_records(portfolio_client, synthetic_database):
    with sqlite3.connect(synthetic_database) as connection:
        connection.execute(
            "INSERT INTO evidence_records (evidence_id,source_id,model_id,normalized_field,normalized_value,"
            "original_value,evidence_location,confidence_level,effective_time) VALUES (?,?,?,?,?,?,?,?,?)",
            ("ev-conflicting-width", f"src-{MODEL_IDS[0]}", MODEL_IDS[0], "width_mm", json.dumps(608.0),
             "608.0", "second fictional specification", "high", "2026-09-01"),
        )
    client, _, _, _ = portfolio_client(_script())
    report = _run(client, _query())
    field = _facts(report)[(MODEL_IDS[0], "width_mm")]
    assert field["status"] == "conflict"
    assert {item["evidence_id"] for item in field["evidence"]} >= {
        f"ev-{MODEL_IDS[0]}-width_mm", "ev-conflicting-width",
    }
    assert report["abstained"] is True
    completion = _completion(report)
    assert completion["completion_status"] == "complete"
    assert "verified_conflict" in _matrix_statuses(completion["matrix"])
    _no_purchase(report)


@pytest.mark.parametrize("failure", ["unavailable", "timeout", "tool_budget"])
def test_evidence_failure_or_budget_is_bounded_and_cannot_look_complete(
    portfolio_client, synthetic_database, failure,
):
    evidence = FailedEvidence(synthetic_database, timeout=failure == "timeout")
    client, _, _, _ = portfolio_client(_script(evidence=True), evidence_tool=evidence)
    api._agent.limits.tool_timeout_seconds = 0.1
    if failure == "tool_budget":
        api._agent.limits.max_tool_calls = 2
    report = _run(client, _query())
    assert report["abstained"] is True
    completion = _completion(report)
    assert completion["completion_status"] == "incomplete"
    assert _matrix_statuses(completion["matrix"]) <= {"not_checked", "tool_failed", "budget_exhausted"}
    assert report["unresolved_facts"]
    assert len(evidence.received) <= 2, "Mandatory completion must not become an unbounded retry loop"
    _no_purchase(report)


def test_already_verified_fields_are_not_verified_again(portfolio_client):
    client, _, _, evidence = portfolio_client(_script(evidence=True))
    report = _run(client, _query())
    assert len(evidence.received) == 1, "The completion gate must reuse valid prior field assessments"
    assert _completion(report)["completion_status"] == "complete"
    _no_purchase(report)


def test_wrong_region_and_version_kb_binding_cannot_be_reported_as_verified(portfolio_client):
    client, _, _, _ = portfolio_client(_script(), kb=RecordingKB(wrong_identity=True))
    report = _run(client, _query())
    assert {row["model_id"] for row in report["candidates"]} <= {MODEL_IDS[0]}
    assert not any(item["source_id"] == "wrong-region-source" for item in report["evidence"])
    assert not any(item.get("region") == "US" for item in report["evidence"])
    completion = _completion(report)
    if completion["completion_status"] == "complete":
        assert all(field["status"] == "matched" and field["actual_value"] is not None
                   for field in _facts(report).values())
    else:
        assert report["abstained"] is True
    _no_purchase(report)


def test_fact_completion_rejects_tool_candidate_scope_expansion(portfolio_client, synthetic_database):
    evidence = OverbroadEvidence(synthetic_database)
    client, _, _, _ = portfolio_client(_script(evidence=True), evidence_tool=evidence)
    report = _run(client, _query())
    assert {row["model_id"] for row in report["candidates"]} == {MODEL_IDS[0]}
    assert set(report["constraint_verification"]["candidate_pool_model_ids"]) == {MODEL_IDS[0]}
    assert all(item["model_id"] == MODEL_IDS[0] for item in report["evidence"])
    assert _completion(report)["completion_status"] == "complete"
    _no_purchase(report)


def test_explicit_partial_evidence_supplement_calls_only_missing_field(portfolio_client, synthetic_database):
    evidence = FirstPartialEvidence(synthetic_database)
    client, _, _, _ = portfolio_client(_script(evidence=True), evidence_tool=evidence)
    report = _run(client, _query())
    assert len(evidence.received) == 2
    assert set(evidence.received[0]["required_fields"]) >= set(FIELDS)
    assert set(evidence.received[1]["required_fields"]) == (
        set(evidence.received[0]["required_fields"]) - {"refresh_rate_hz"}
    )
    assert "width_mm" in evidence.received[1]["required_fields"]
    assert evidence.received[1]["model_ids"] == [MODEL_IDS[0]]
    assert _completion(report)["completion_status"] == "complete"
    facts = _facts(report)
    assert facts[(MODEL_IDS[0], "refresh_rate_hz")]["actual_value"] == 144
    assert facts[(MODEL_IDS[0], "width_mm")]["actual_value"] == 610
    _no_purchase(report)


def test_repeated_explicit_evidence_requests_reuse_completed_cells(portfolio_client):
    messages = _script(evidence=True)
    messages.insert(-1, copy.deepcopy(messages[-2]))
    client, _, _, evidence = portfolio_client(messages)
    report = _run(client, _query())
    assert len(evidence.received) == 1
    assert _completion(report)["completion_status"] == "complete"
    _no_purchase(report)


@pytest.mark.parametrize("identity_field", ["model_id", "region", "configuration_id", "data_version"])
def test_executed_evidence_identity_mismatch_is_not_a_verified_fact(
    portfolio_client, synthetic_database, identity_field,
):
    evidence = CorruptIdentityEvidence(synthetic_database, identity_field=identity_field)
    client, _, _, _ = portfolio_client(_script(evidence=True), evidence_tool=evidence)
    report = _run(client, _query())
    assert report["abstained"] is True
    completion = _completion(report)
    assert completion["completion_status"] == "incomplete"
    assert "verified_value" not in _matrix_statuses(completion["matrix"])
    assert report["unresolved_facts"]
    assert not any(field["status"] == "matched" for field in _facts(report).values())
    _no_purchase(report)


def test_task_latency_budget_stops_supplement_after_slow_fake_tools(portfolio_client):
    client, provider, _, evidence = portfolio_client(_script(), kb=SlowKB())
    original_chat = provider.chat

    async def slow_fake_chat(*args, **kwargs):
        await asyncio.sleep(0.085)
        return await original_chat(*args, **kwargs)

    provider.chat = slow_fake_chat
    api._agent.limits.max_steps = 2
    api._agent.limits.tool_timeout_seconds = 0.1
    report = _run(client, _query())
    assert report["abstained"] is True
    assert evidence.received == []
    completion = _completion(report)
    assert completion["completion_status"] == "incomplete"
    assert _matrix_statuses(completion["matrix"]) == {"budget_exhausted"}
    _no_purchase(report)


def test_terminal_verification_is_auditable_in_api_events_and_budget(portfolio_client):
    client, _, sql, evidence = portfolio_client(_script())
    response = client.post("/api/smartbuy/portfolio/run", json={
        "domain_id": "monitor", "mode": "trusted", "query": _query(),
    })
    assert response.status_code == 200
    payload = response.json()
    report = payload["report"]
    completion = _completion(report)
    checks = completion.get("checks", [])
    assert len(checks) == len(evidence.received) == 1
    assert checks[0]["tool"] == "evidence_check"
    assert set(checks[0]["required_fields"]) >= set(FIELDS)
    assert checks[0]["additional_model_calls"] == 0
    assert report["usage"].get("verification_tools_used") == ["evidence_check"]
    assert report["tool_call_count"] >= len(evidence.received) + 1
    assert report["tools_used"] == ["kb_search"] and not sql.received
    observations = [event for event in payload["events"] if event.get("type") == "fact_verification_observation"]
    assert observations and observations[0].get("check", {}).get("tool") == "evidence_check"
    completions = [event for event in payload["events"] if event.get("type") == "fact_completion"]
    assert completions and completions[-1].get("completion", {}).get("matrix")


def test_duplicate_matched_field_cannot_erase_an_observed_conflict(portfolio_client, synthetic_database):
    evidence = ConflictingDuplicateEvidence(synthetic_database)
    client, _, _, _ = portfolio_client(_script(evidence=True), evidence_tool=evidence)
    report = _run(client, _query())
    assert report["abstained"] is True
    completion = _completion(report)
    assert completion["completion_status"] == "complete"
    assert "verified_conflict" in _matrix_statuses(completion["matrix"])
    field = _facts(report)[(MODEL_IDS[0], "width_mm")]
    assert field["status"] == "conflict"
    assert {reference["evidence_id"] for reference in field["evidence"]} >= {
        f"ev-{MODEL_IDS[0]}-width_mm", "ev-duplicate-conflicting-width",
    }
    assert not report["recommended_model_ids"]
    _no_purchase(report)


def test_completed_fact_finish_does_not_make_a_purchase_ranking_model_call(portfolio_client):
    messages = _script()
    client, provider, _, evidence = portfolio_client(messages)
    report = _run(client, _query())
    assert _completion(report)["completion_status"] == "complete"
    assert len(evidence.received) == 1
    assert provider.calls == len(messages) == 3
    assert not any("rank" in trace["tool"] for trace in report["trace"])
    assert report["abstained"] is False
    _no_purchase(report)
