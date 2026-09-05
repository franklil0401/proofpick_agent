"""Default Portfolio API contracts with synthetic governed products and no network.

These development regressions exercise the real Monitor route, orchestrator,
SQLite, Evidence Check and final Checker.  Only model output and KB retrieval
are Fake Providers; this is not an independent evaluation or paid E2E run.
"""

from __future__ import annotations

import copy
import importlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from smartbuy.agent import DomainDecisionAgent, PurchaseDecisionAgent
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.db.build_database import SCHEMA_PATH
from smartbuy.domain_packs import DomainPackRegistry
from smartbuy.memory import DomainPreferenceMemoryStore, LongTermPreferenceStore
from smartbuy.observability import UsageLedger
from smartbuy.orchestration import ReactOrchestrator
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.tools import EvidenceCheckTool, Text2SQLTool, ToolResult, WebSearchTool
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)


api = importlib.import_module("smartbuy.api.router")
MODEL_IDS = ["acme-orbit-x410-cn", "acme-orbit-x420-cn", "acme-orbit-x430-cn"]
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.ledger = UsageLedger()

    async def chat(self, *_args, **_kwargs):
        self.calls += 1
        message = self.responses.pop(0) if self.responses else {"role": "assistant", "content": ""}
        return SimpleNamespace(data=message)


class RecordingSQL(Text2SQLTool):
    def __init__(self, database):
        super().__init__(database)
        self.received = []
        self.results = []

    async def invoke(self, arguments):
        self.received.append(copy.deepcopy(arguments))
        result = await super().invoke(arguments)
        self.results.append(result)
        return result


class RecordingEvidence(EvidenceCheckTool):
    def __init__(self, database):
        super().__init__(database)
        self.received = []

    async def invoke(self, arguments):
        self.received.append(copy.deepcopy(arguments))
        return await super().invoke(arguments)


class GovernedFakeKB:
    name = "kb_search"
    schema = {
        "type": "function",
        "function": {
            "name": "kb_search",
            "description": "Offline fixture retrieval",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    async def invoke(self, arguments):
        hits = []
        for model_id in arguments.get("model_ids") or [MODEL_IDS[0]]:
            if model_id not in MODEL_IDS:
                continue
            source_id = f"src-{model_id}"
            url = f"https://example.com/cn/{model_id}"
            hits.append({
                "model_id": model_id,
                "source_id": source_id,
                "source_url": url,
                "source_type": "official_product",
                "region": "CN",
                "section": "Synthetic specification",
                "accessed_at": "2026-09-01",
                "evidence_bindings": [
                    {
                        "evidence_id": f"ev-{model_id}-{field}",
                        "field": field,
                        "source_id": source_id,
                        "source_url": url,
                    }
                    for field in ["width_mm", "refresh_rate_hz"]
                ],
            })
        return ToolResult(tool=self.name, status="success", summary="Synthetic governed facts", data={"hits": hits})


def tool_call(name, arguments):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": f"call-{name}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
        }],
    }


def requirements(*, fact=False):
    return tool_call("set_requirements", {
        "summary": "合成商品规格核验" if fact else "合成商品宽度与刷新率筛选",
        "task_type": "fact" if fact else "filter",
        "hard_constraints": (
            [{"field": "model_id", "operator": "eq", "value": MODEL_IDS[0]}]
            if fact else [
                {"field": "refresh_rate_hz", "operator": "gte", "value": 144},
                {"field": "width_mm", "operator": "lte", "value": 610},
            ]
        ),
        "soft_preferences": [],
        "required_fields": ["width_mm", "refresh_rate_hz"],
        "excluded_model_ids": [],
        "pending_questions": [],
    })


def scripted_filter():
    return [
        requirements(),
        tool_call("text2sql", {
            "sql": "SELECT model_id FROM products WHERE refresh_rate_hz>=144 AND width_mm<=610",
            "filters": [
                {"field": "refresh_rate_hz", "operator": "gte", "value": 144},
                {"field": "width_mm", "operator": "lte", "value": 610},
            ],
            "reason": "筛选两项条件",
        }),
        tool_call("kb_search", {
            "query": "已筛选合成型号官方规格",
            "model_ids": MODEL_IDS,
            "required_fields": ["width_mm", "refresh_rate_hz"],
            "parent_step": 2,
            "reason": "核验字段",
        }),
        tool_call("evidence_check", {
            "model_ids": MODEL_IDS,
            "required_fields": ["width_mm", "refresh_rate_hz"],
            "constraints": [],
            "parent_step": 3,
            "reason": "检查全部明确条件",
        }),
        tool_call("finish_decision", {"stop_reason": "已完成", "pending_questions": []}),
    ]


@pytest.fixture
def synthetic_database(tmp_path):
    path = tmp_path / "synthetic.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    with connection:
        for model_id, suffix, width, refresh in zip(
            MODEL_IDS, ("X410", "X420", "X430"), (610.0, 611.9, 600.0), (144.0, 165.0, 120.0), strict=True
        ):
            source_id = f"src-{model_id}"
            connection.execute(
                "INSERT INTO products (model_id,brand,model_name,region,width_mm,refresh_rate_hz,"
                "official_source_id,source_updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (model_id, "Acme", f"Acme Orbit {suffix}", "CN", width, refresh, source_id, "2026-09-01"),
            )
            connection.execute(
                "INSERT INTO source_records (source_id,model_id,source_type,title,url,is_official,region,"
                "accessed_at,content_hash,redistribution_status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (source_id, model_id, "official_product", "Synthetic authored specification",
                 f"https://example.com/cn/{model_id}", 1, "CN", "2026-09-01", "a" * 64, "self_authored"),
            )
            for field, value in (("width_mm", width), ("refresh_rate_hz", refresh), ("region", "CN")):
                connection.execute(
                    "INSERT INTO evidence_records (evidence_id,source_id,model_id,normalized_field,"
                    "normalized_value,original_value,evidence_location,confidence_level,effective_time) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"ev-{model_id}-{field}", source_id, model_id, field, json.dumps(value), str(value),
                     "self-authored fixture", "high", "2026-09-01"),
                )
    connection.close()
    return path


@pytest.fixture
def portfolio_client(monkeypatch, tmp_path, synthetic_database):
    # Match documented start.ps1: only domain-agent opt-in is set, Monitor
    # remains V1 compatible and uses the default ReAct selector.
    for name in (
        "PROOFPICK_NATURAL_CONSTRAINTS_ENABLED", "PROOFPICK_DOMAIN_PACK_ENABLED",
        "PROOFPICK_PRODUCT_PACK_ENABLED", "SMARTBUY_ORCHESTRATOR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PROOFPICK_DOMAIN_AGENT_ENABLED", "true")
    monkeypatch.setenv("PROOFPICK_ORCHESTRATOR", "react")
    sql = RecordingSQL(synthetic_database)
    evidence = RecordingEvidence(synthetic_database)

    def make(responses, *, kb=None, evidence_tool=None, database=None):
        selected_sql = RecordingSQL(database) if database is not None else sql
        selected_evidence = RecordingEvidence(database) if database is not None else evidence
        provider = ScriptedProvider(responses)
        agent = PurchaseDecisionAgent(
            provider,
            {"text2sql": selected_sql, "kb_search": kb or GovernedFakeKB(), "evidence_check": evidence_tool or selected_evidence,
             "web_search": WebSearchTool()},
            preference_memory=LongTermPreferenceStore(tmp_path / "preferences.json"),
        )
        monkeypatch.setattr(api, "_agent", agent)
        monkeypatch.setattr(api, "_orchestrator", None)
        app = FastAPI()
        app.include_router(api.router)
        return TestClient(app), provider, selected_sql, selected_evidence

    yield make


@pytest.mark.parametrize("width", ["610毫米", "610mm", "61厘米", "61cm", "61.0厘米", "610.0毫米"])
def test_portfolio_default_monitor_carries_each_hard_constraint_to_checker(portfolio_client, width):
    client, _, sql, evidence = portfolio_client(scripted_filter())
    response = client.post("/api/smartbuy/portfolio/run", json={
        "domain_id": "monitor", "mode": "trusted",
        "query": f"请从已收录的显示器中挑选：刷新率至少144Hz，机身宽度最多{width}。不限制地区，保持各配置独立。",
    })
    assert response.status_code == 200
    report = response.json()["report"]
    active = {
        row["field"]: row["normalized_value"]
        for row in report["constraint_set"]["constraints"] if row["active"] and row["hard_or_soft"] == "hard"
    }
    assert active["refresh_rate_hz"] == 144
    assert active.get("width_mm") == 610
    assert {row["field"] for row in sql.received[0]["filters"]} >= {"width_mm", "refresh_rate_hz"}
    assert {row["field"] for row in evidence.received[0]["constraints"]} >= {"width_mm", "refresh_rate_hz"}
    for collection in (sql.received[0]["filters"], evidence.received[0]["constraints"]):
        actual = {row["field"]: (row["operator"], row["value"]) for row in collection}
        assert actual["width_mm"] == ("lte", 610)
        assert actual["refresh_rate_hz"] == ("gte", 144)
    verification = report["constraint_verification"]
    assert report["recommended_model_ids"] == [MODEL_IDS[0]]
    assert verification["candidate_pool_model_ids"] == [MODEL_IDS[0]]
    checked = {row["constraint"]["field"] for row in verification["candidates"][0]["constraint_results"]}
    assert checked >= {"width_mm", "refresh_rate_hz"}
    assert {row["field"] for row in report["candidates"][0]["fields"]} >= {"width_mm", "refresh_rate_hz"}


def test_portfolio_trace_exposes_executed_filters_not_only_suggested_sql(portfolio_client):
    client, _, sql, _ = portfolio_client(scripted_filter())
    response = client.post("/api/smartbuy/portfolio/run", json={
        "domain_id": "monitor", "query": "从显示器中筛选刷新率至少144Hz、宽度不超过610mm的型号。",
    })
    assert response.status_code == 200
    report = response.json()["report"]
    trace = next(row for row in report["trace"] if row["tool"] == "text2sql")
    summary = trace["arguments_summary"]
    assert summary.get("executed_sql") == sql.results[0].data["sql"]
    assert {row["field"] for row in summary["effective_filters"]} >= {"width_mm", "refresh_rate_hz"}
    assert summary["suggested_sql"] != summary["executed_sql"]


@pytest.mark.parametrize("reference", ["Acme Orbit X410，CN", "Orbit X410，CN，acme-orbit-x410-cn", "acme-orbit-x410-cn"])
def test_portfolio_exact_identity_overrides_shared_family_and_keeps_fact_query(portfolio_client, reference):
    responses = [
        requirements(fact=True),
        tool_call("kb_search", {"query": "明确配置规格", "model_ids": [MODEL_IDS[0]],
                 "required_fields": ["width_mm", "refresh_rate_hz"], "reason": "读取事实"}),
        tool_call("finish_decision", {"stop_reason": "事实核验完成", "pending_questions": []}),
    ]
    client, provider, _, _ = portfolio_client(responses)
    response = client.post("/api/smartbuy/portfolio/run", json={
        "domain_id": "monitor", "query": f"{reference} 的机身宽度和刷新率分别是多少？",
    })
    assert response.status_code == 200
    report = response.json()["report"]
    assert report["clarification_state"] != "pending"
    assert provider.calls > 0
    assert report["task_type"] == "fact"
    assert report["recommended_model_ids"] == []
    assert not [row for row in report["constraint_set"]["constraints"]
                if row["active"] and row["field"] in {"width_mm", "refresh_rate_hz"}]
    assert {row["model_id"] for row in report["candidates"]} == {MODEL_IDS[0]}


@pytest.mark.parametrize("query", [
    "Orbit系列的宽度是多少？",
    "Acme Orbit X410，acme-orbit-x410-cn，美国版，查询宽度。",
    "刷新率至少144Hz，机身宽度最多610光年，筛选显示器。",
    "刷新率至少144Hz，机身宽度窄一点，筛选显示器。",
])
def test_portfolio_unresolved_identity_or_hard_requirement_pauses_before_cost(portfolio_client, query):
    client, provider, sql, evidence = portfolio_client(scripted_filter())
    response = client.post("/api/smartbuy/portfolio/run", json={"domain_id": "monitor", "query": query})
    assert response.status_code == 200
    report = response.json()["report"]
    assert report["clarification_state"] == "pending"
    assert report["recommended_model_ids"] == []
    assert provider.calls == 0
    assert sql.received == [] and evidence.received == []


def test_portfolio_llm_omitted_width_cannot_remove_explicit_user_requirement(portfolio_client):
    responses = scripted_filter()
    declared = json.loads(responses[0]["tool_calls"][0]["function"]["arguments"])
    declared["hard_constraints"] = [{"field": "refresh_rate_hz", "operator": "gte", "value": 144}]
    declared["required_fields"] = ["refresh_rate_hz"]
    responses[0] = tool_call("set_requirements", declared)
    client, _, sql, evidence = portfolio_client(responses)
    response = client.post("/api/smartbuy/portfolio/run", json={
        "domain_id": "monitor", "query": "筛选刷新率至少144Hz、机身宽度最多610毫米的显示器，不限制地区。",
    })
    assert response.status_code == 200
    report = response.json()["report"]
    assert report["recommended_model_ids"] == [MODEL_IDS[0]]
    assert {row["field"] for row in sql.received[0]["filters"]} >= {"width_mm", "refresh_rate_hz"}
    assert {row["field"] for row in evidence.received[0]["constraints"]} >= {"width_mm", "refresh_rate_hz"}
    assert {row["constraint"]["field"] for row in report["constraint_verification"]["candidates"][0]["constraint_results"]} >= {
        "width_mm", "refresh_rate_hz",
    }


class OverbroadFakeKB(GovernedFakeKB):
    """Valid fixture evidence returned outside the requested identity scope."""

    async def invoke(self, arguments):
        return await super().invoke({**arguments, "model_ids": MODEL_IDS})


class OverbroadEvidence(RecordingEvidence):
    async def invoke(self, arguments):
        return await super().invoke({**arguments, "model_ids": MODEL_IDS})


@pytest.mark.parametrize("injected_tool", ["kb_search", "evidence_check"])
def test_portfolio_exact_scope_filters_overbroad_tool_results(
    portfolio_client, synthetic_database, injected_tool
):
    responses = [
        requirements(fact=True),
        tool_call("text2sql", {
            "sql": "SELECT model_id FROM products", "filters": [], "reason": "核验指定配置",
        }),
        tool_call("kb_search", {
            "query": "指定配置宽度", "model_ids": [MODEL_IDS[0]],
            "required_fields": ["width_mm", "refresh_rate_hz"], "reason": "核验全部字段", "parent_step": 2,
        }),
        tool_call("evidence_check", {
            "model_ids": [MODEL_IDS[0]], "required_fields": ["width_mm", "refresh_rate_hz"],
            "constraints": [], "reason": "核验指定配置", "parent_step": 3,
        }),
        tool_call("finish_decision", {"stop_reason": "完成事实核验", "pending_questions": []}),
    ]
    client, _, _, _ = portfolio_client(
        responses,
        kb=OverbroadFakeKB() if injected_tool == "kb_search" else None,
        evidence_tool=OverbroadEvidence(synthetic_database) if injected_tool == "evidence_check" else None,
    )
    response = client.post("/api/smartbuy/portfolio/run", json={
        "domain_id": "monitor", "query": "只核验 acme-orbit-x410-cn 的宽度和刷新率，不比较其他配置。",
    })
    assert response.status_code == 200
    report = response.json()["report"]
    allowed = {MODEL_IDS[0]}
    assert {row["model_id"] for row in report["candidates"]} <= allowed
    assert {row["model_id"] for row in report["evidence"]} <= allowed
    assert set(report["constraint_verification"]["candidate_pool_model_ids"]) <= allowed
    assert set(report["recommended_model_ids"]) <= allowed


@pytest.mark.parametrize("domain_id", ["laptop", "headphone"])
def test_portfolio_v2_domains_dispatch_real_agent_without_hidden_parser_flag(
    tmp_path, monkeypatch, domain_id
):
    monkeypatch.delenv("PROOFPICK_NATURAL_CONSTRAINTS_ENABLED", raising=False)
    monkeypatch.setenv("PROOFPICK_DOMAIN_AGENT_ENABLED", "true")
    pack_root = PROJECT_ROOT / "smartbuy" / "domain_packs"
    pack = DomainPackRegistry(pack_root).load(domain_id)
    source = PROJECT_ROOT / "smartbuy" / "product_packs" / "examples" / f"{domain_id}-v1" / "pack.json"
    manager = DomainProductPackManager(tmp_path / "data", domain_pack_path=pack_root / domain_id)
    snapshot = manager.publish(manager.stage(source).data_version)
    repository = DomainReadonlyRepository(snapshot, pack)
    product_id = sorted(repository.load())[0]
    agent = DomainDecisionAgent(
        pack, repository,
        DomainProductQueryTool(repository), DomainEvidenceCheckTool(repository),
        DomainConstraintCheckerTool(repository), NaturalConstraintEngine(pack),
        DomainPreferenceMemoryStore(tmp_path / "memory", pack),
    )
    selected = []

    def get_runtime(requested_domain):
        selected.append(requested_domain)
        assert requested_domain == domain_id
        return SimpleNamespace(
            orchestrator=ReactOrchestrator(agent), data_version=snapshot.data_version,
            index_version="not_built_offline_fixture",
        )

    monkeypatch.setattr(api, "_portfolio_runtimes", SimpleNamespace(get=get_runtime))
    app = FastAPI()
    app.include_router(api.router)
    response = TestClient(app).post("/api/smartbuy/portfolio/run", json={
        "domain_id": domain_id, "query": f"请核验 {product_id} 的重量是多少？",
    })
    assert response.status_code == 200
    assert selected == [domain_id]
    payload = response.json()
    assert payload["data_version"] == snapshot.data_version
    report = payload["report"]
    assert report["task_type"] == "fact"
    assert report["recommended_model_ids"] == []
    assert {row["model_id"] for row in report["candidates"]} <= {product_id}
    assert not [row for row in report["constraint_set"]["constraints"]
                if row["active"] and row["hard_or_soft"] == "hard" and row["field"] == "weight_kg"]


def test_portfolio_fact_fields_cannot_be_activated_by_llm_purchase_proposals(portfolio_client):
    declared = json.loads(requirements(fact=True)["tool_calls"][0]["function"]["arguments"])
    declared["hard_constraints"].extend([
        {"field": "width_mm", "operator": "lte", "value": 610},
        {"field": "refresh_rate_hz", "operator": "gte", "value": 144},
    ])
    client, _, _, _ = portfolio_client([
        tool_call("set_requirements", declared),
        tool_call("kb_search", {"query": "明确配置字段查询", "model_ids": [MODEL_IDS[0]],
                 "required_fields": ["width_mm", "refresh_rate_hz"], "reason": "核验事实"}),
        tool_call("finish_decision", {"stop_reason": "事实核验完成", "pending_questions": []}),
    ])
    response = client.post("/api/smartbuy/portfolio/run", json={
        "domain_id": "monitor", "query": "Acme Orbit X410，CN，机身宽度和刷新率分别是多少？",
    })
    assert response.status_code == 200
    report = response.json()["report"]
    assert report["task_type"] == "fact"
    assert report["recommended_model_ids"] == []
    assert not [row for row in report["constraint_set"]["constraints"]
                if row["active"] and row["field"] in {"width_mm", "refresh_rate_hz"}]


def test_portfolio_purchase_intent_cannot_be_downgraded_by_fact_subtask(portfolio_client):
    responses = scripted_filter()
    declared = json.loads(responses[0]["tool_calls"][0]["function"]["arguments"])
    declared["task_type"] = "fact"
    responses[0] = tool_call("set_requirements", declared)
    client, _, _, _ = portfolio_client(responses)
    response = client.post("/api/smartbuy/portfolio/run", json={
        "domain_id": "monitor",
        "query": "筛选刷新率至少144Hz、宽度最多610毫米的显示器，并核验候选依据。不限制地区。",
    })
    assert response.status_code == 200
    report = response.json()["report"]
    assert report["task_type"] == "filter"
    assert report["recommended_model_ids"] == [MODEL_IDS[0]]
    assert {item["field"] for item in report["hard_constraints"]} >= {"width_mm", "refresh_rate_hz"}


def test_public_width_incident_exposed_regression_uses_real_catalog(portfolio_client, tmp_path):
    """User-public incident only: not an independent evaluation or unseen task."""
    from smartbuy.db.build_database import build_database

    database = tmp_path / "exposed-catalog.sqlite"
    build_database(database)

    class CatalogFixtureKB(GovernedFakeKB):
        async def invoke(self, arguments):
            hits = []
            with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
                connection.row_factory = sqlite3.Row
                for model_id in arguments.get("model_ids", []):
                    rows = connection.execute(
                        "SELECT e.*,s.url,s.region,s.source_type,s.accessed_at FROM evidence_records e "
                        "JOIN source_records s USING(source_id) WHERE e.model_id=? "
                        "AND e.normalized_field IN ('width_mm','refresh_rate_hz')", (model_id,),
                    )
                    for row in rows:
                        hits.append({
                            "model_id": model_id, "source_id": row["source_id"], "source_url": row["url"],
                            "region": row["region"], "source_type": row["source_type"],
                            "accessed_at": row["accessed_at"], "section": row["evidence_location"],
                            "evidence_bindings": [{"field": row["normalized_field"],
                                                   "evidence_id": row["evidence_id"]}],
                        })
            return ToolResult(tool="kb_search", status="success", summary="Offline governed evidence replay",
                              data={"hits": hits})

    client, _, sql, evidence = portfolio_client(scripted_filter(), kb=CatalogFixtureKB(), database=database)
    response = client.post("/api/smartbuy/portfolio/run", json={
        "domain_id": "monitor",
        "query": "请从已收录的显示器中挑选：刷新率至少144Hz，机身宽度最多610毫米。不限制地区，保持各配置独立，给出符合条件的选择及依据。",
    })
    assert response.status_code == 200
    report = response.json()["report"]
    expected = {"asus-pg27aqdm-cn", "benq-ex2710u-cn", "lg-27gs95qe-b-cn"}
    assert set(report["recommended_model_ids"]) == expected
    assert set(report["constraint_verification"]["candidate_pool_model_ids"]) == expected
    assert report["usage"]["requirement_coverage"]["complete"] is True
    assert {item["field"] for item in sql.received[0]["filters"]} >= {"width_mm", "refresh_rate_hz"}
    assert {item["field"] for item in evidence.received[0]["constraints"]} >= {"width_mm", "refresh_rate_hz"}
    for candidate in report["constraint_verification"]["candidates"]:
        by_field = {row["constraint"]["field"]: row for row in candidate["constraint_results"]}
        assert by_field["width_mm"]["actual_value"] <= 610
        assert by_field["refresh_rate_hz"]["actual_value"] >= 144


def test_session_observations_cannot_escape_new_exact_scope(portfolio_client):
    client, provider, _, _ = portfolio_client(scripted_filter())
    first = client.post("/api/smartbuy/portfolio/run", json={
        "domain_id": "monitor", "session_id": "scope-followup",
        "query": "筛选刷新率至少144Hz、机身宽度最多610毫米的显示器。",
    })
    assert first.status_code == 200
    assert first.json()["report"]["recommended_model_ids"] == [MODEL_IDS[0]]
    provider.responses.extend([
        requirements(fact=True),
        tool_call("kb_search", {"query": "新指定配置事实", "model_ids": [MODEL_IDS[2]],
                                "required_fields": ["width_mm", "refresh_rate_hz"]}),
        tool_call("finish_decision", {"stop_reason": "只核验新指定配置", "pending_questions": []}),
    ])
    second = client.post("/api/smartbuy/portfolio/run", json={
        "domain_id": "monitor", "session_id": "scope-followup",
        "query": f"改为只查询 {MODEL_IDS[2]} 的宽度和刷新率。",
    })
    assert second.status_code == 200
    report = second.json()["report"]
    allowed = {MODEL_IDS[2]}
    assert report["clarification_state"] != "pending"
    assert {item["model_id"] for item in report["evidence"]} == allowed
    assert {item["model_id"] for item in report["candidates"]} == allowed
    assert set(report["constraint_verification"]["candidate_pool_model_ids"]) <= allowed
