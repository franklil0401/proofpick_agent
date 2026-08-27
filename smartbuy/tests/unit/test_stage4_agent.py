"""Bounded Agent loop, dependent multihop and public-report tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from smartbuy.agent import PurchaseDecisionAgent
from smartbuy.db.build_database import build_database
from smartbuy.domain import AgentLimits, UserRequirements
from smartbuy.memory import LongTermPreferenceStore
from smartbuy.observability import UsageLedger
from smartbuy.tools import EvidenceCheckTool, Text2SQLTool, ToolResult, WebSearchTool


class FakeProvider:
    def __init__(self, calls):
        self.calls = list(calls)
        self.ledger = UsageLedger()

    async def chat(self, *_args, **_kwargs):
        if not self.calls:
            return SimpleNamespace(data={"role": "assistant", "content": "no tool"})
        return SimpleNamespace(data=self.calls.pop(0))


class FakeKB:
    name = "kb_search"
    schema = {
        "type": "function",
        "function": {
            "name": "kb_search",
            "description": "fake",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    async def invoke(self, arguments):
        model_id = (arguments.get("model_ids") or ["dell-u2723qe-cn"])[0]
        return ToolResult(
            tool=self.name,
            status="success",
            summary="命中官方事实卡。",
            data={
                "hits": [
                    {
                        "model_id": model_id,
                        "source_id": "src-dell-u2723qe-cn-product",
                        "source_url": "https://example.com/dell-u2723qe",
                        "source_type": "official_product",
                        "region": "CN",
                        "section": "接口与供电",
                        "accessed_at": "2026-08-26",
                    }
                ]
            },
        )


def call(name, arguments, call_id):
    return {
        "role": "assistant",
        "content": "SECRET_HIDDEN_REASONING",
        "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
        ],
    }


@pytest.fixture()
def database(tmp_path):
    path = tmp_path / "catalog.sqlite"
    build_database(path)
    return path


def tools(database):
    return {
        "text2sql": Text2SQLTool(database),
        "kb_search": FakeKB(),
        "evidence_check": EvidenceCheckTool(database),
        "web_search": WebSearchTool(),
    }


def test_task_type_and_explicit_constraints_are_normalized():
    assert PurchaseDecisionAgent._infer_task_type("U2724D 是否有 90W 供电？", "fact") == "filter"
    assert PurchaseDecisionAgent._infer_task_type("PD2705U 到底是 60W 还是 65W？", "fact") == "comparison"
    requirements = PurchaseDecisionAgent._augment_requirements(
        "中国版 QHD、至少 120Hz、非 OLED 且没有 USB-C",
        UserRequirements(summary="组合筛选", task_type="filter"),
    )
    values = {item.field: item.value for item in requirements.hard_constraints}
    assert values == {
        "region": "CN", "resolution": "2560x1440", "refresh_rate_hz": 120.0,
        "is_oled": False, "has_usb_c": False,
    }


@pytest.mark.asyncio
async def test_agent_executes_dependent_sql_kb_evidence_chain(database, tmp_path):
    responses = [
        call(
            "set_requirements",
            {
                "summary": "中国版 27 英寸 4K，USB-C 视频和至少 90W 供电",
                "hard_constraints": [
                    {"field": "region", "operator": "eq", "value": "CN"},
                    {"field": "display_size_inch", "operator": "eq", "value": 27},
                    {"field": "resolution", "operator": "eq", "value": "3840x2160"},
                    {"field": "usb_c_video", "operator": "eq", "value": True},
                    {"field": "usb_c_power_delivery_w", "operator": "gte", "value": 90},
                ],
                "soft_preferences": [],
                "required_fields": [
                    "region", "display_size_inch", "resolution", "usb_c_video", "usb_c_power_delivery_w"
                ],
                "excluded_model_ids": [],
                "pending_questions": [],
            },
            "c1",
        ),
        call(
            "text2sql",
            {
                "sql": "SELECT model_id, brand, model_name, region, display_size_inch, resolution, "
                "usb_c_video, usb_c_power_delivery_w FROM products WHERE model_id='dell-u2723qe-cn'",
                "filters": [{"field": "model_id", "operator": "eq", "value": "dell-u2723qe-cn"}],
                "reason": "先筛选硬条件候选",
            },
            "c2",
        ),
        call(
            "kb_search",
            {
                "query": "U2723QE 中国版 USB-C 视频 90W 官方规格",
                "model_ids": ["dell-u2723qe-cn"],
                "required_fields": ["usb_c_video", "usb_c_power_delivery_w"],
                "reason": "核验第一跳候选",
                "parent_step": 2,
            },
            "c3",
        ),
        call(
            "evidence_check",
            {
                "model_ids": ["dell-u2723qe-cn"],
                "required_fields": [
                    "region", "display_size_inch", "resolution", "usb_c_video", "usb_c_power_delivery_w"
                ],
                "constraints": [
                    {"field": "region", "operator": "eq", "value": "CN"},
                    {"field": "display_size_inch", "operator": "eq", "value": 27},
                    {"field": "resolution", "operator": "eq", "value": "3840x2160"},
                    {"field": "usb_c_video", "operator": "eq", "value": True},
                    {"field": "usb_c_power_delivery_w", "operator": "gte", "value": 90},
                ],
                "reason": "检查完整命题",
                "parent_step": 3,
            },
            "c4",
        ),
        call("finish_decision", {"stop_reason": "必要字段均已核验。", "pending_questions": []}, "c5"),
    ]
    agent = PurchaseDecisionAgent(
        FakeProvider(responses), tools(database),
        preference_memory=LongTermPreferenceStore(tmp_path / "preferences.json"),
    )
    report = await agent.run("帮我找符合条件的显示器", session_id="s1")
    assert report.recommended_model_ids == ["dell-u2723qe-cn"]
    assert report.abstained is False
    assert report.tools_used == ["text2sql", "kb_search", "evidence_check"]
    assert [item.parent_step for item in report.trace if item.tool in {"kb_search", "evidence_check"}] == [2, 3]
    assert "SECRET_HIDDEN_REASONING" not in report.model_dump_json()
    assert "SECRET_HIDDEN_REASONING" not in report.to_markdown()


@pytest.mark.asyncio
async def test_simple_fact_uses_only_kb_domain_tool(database, tmp_path):
    responses = [
        call(
            "set_requirements",
            {
                "summary": "U2723QE 的分辨率",
                "hard_constraints": [], "soft_preferences": [], "required_fields": ["resolution"],
                "excluded_model_ids": [], "pending_questions": [],
            },
            "c1",
        ),
        call(
            "kb_search",
            {
                "query": "U2723QE 分辨率 官方规格", "model_ids": ["dell-u2723qe-cn"],
                "required_fields": ["resolution"], "reason": "简单事实查询", "parent_step": 1,
            },
            "c2",
        ),
        call("finish_decision", {"stop_reason": "事实证据已命中。", "pending_questions": []}, "c3"),
    ]
    agent = PurchaseDecisionAgent(
        FakeProvider(responses), tools(database),
        preference_memory=LongTermPreferenceStore(tmp_path / "preferences.json"),
    )
    report = await agent.run("U2723QE 分辨率？")
    assert report.tools_used == ["kb_search"]
    assert report.abstained is False


@pytest.mark.asyncio
async def test_max_step_limit_stops_without_looping(database, tmp_path):
    provider = FakeProvider([])
    agent = PurchaseDecisionAgent(
        provider, tools(database), limits=AgentLimits(max_steps=2),
        preference_memory=LongTermPreferenceStore(tmp_path / "preferences.json"),
    )
    report = await agent.run("一直思考但不调用工具")
    assert "安全停止" in report.stop_reason
    assert report.abstained is True


@pytest.mark.asyncio
async def test_web_unavailable_does_not_break_kb_sql_chain(database, tmp_path):
    responses = [
        call(
            "set_requirements",
            {"summary": "查动态库存", "hard_constraints": [], "soft_preferences": [],
             "required_fields": ["stock_status"], "excluded_model_ids": [], "pending_questions": []},
            "c1",
        ),
        call("web_search", {"query": "当前库存", "reason": "尝试动态补充"}, "c2"),
        call(
            "text2sql",
            {"sql": "SELECT p.model_id, p.brand, p.model_name, p.region, po.stock_status, po.observed_at "
             "FROM products p JOIN price_observations po ON po.model_id=p.model_id WHERE p.model_id='dell-u2724d-cn'",
             "filters": [{"field": "model_id", "operator": "eq", "value": "dell-u2724d-cn"}],
             "reason": "回退本地观测"},
            "c3",
        ),
        call(
            "evidence_check",
            {"model_ids": ["dell-u2724d-cn"], "required_fields": ["stock_status"], "constraints": [],
             "reason": "检查本地观测", "parent_step": 3},
            "c4",
        ),
        call("finish_decision", {"stop_reason": "以本地观测降级完成。", "pending_questions": []}, "c5"),
    ]
    agent = PurchaseDecisionAgent(
        FakeProvider(responses), tools(database),
        preference_memory=LongTermPreferenceStore(tmp_path / "preferences.json"),
    )
    report = await agent.run("U2724D 现在有库存吗？")
    assert "web_search" in report.tools_used
    assert any("Web Search" in item for item in report.degraded_states)
    assert report.candidates[0].fields[0].status == "matched"
