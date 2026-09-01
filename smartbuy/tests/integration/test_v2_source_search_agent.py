from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from smartbuy.agent import PurchaseDecisionAgent
from smartbuy.db.build_database import build_database
from smartbuy.memory import LongTermPreferenceStore
from smartbuy.observability import UsageLedger
from smartbuy.tools import EvidenceCheckTool, Text2SQLTool, ToolResult, WebSearchTool


class FakeProvider:
    def __init__(self, calls):
        self.calls = list(calls)
        self.ledger = UsageLedger()

    async def chat(self, *_args, **_kwargs):
        if not self.calls:
            return SimpleNamespace(data={"role": "assistant", "content": ""})
        return SimpleNamespace(data=self.calls.pop(0))


class EmptyKB:
    name = "kb_search"
    schema = {
        "type": "function",
        "function": {
            "name": "kb_search",
            "description": "fake",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    async def invoke(self, _arguments):
        return ToolResult(tool=self.name, status="success", summary="无本地命中", data={"hits": []})


class FakeSourceSearch:
    name = "source_search"
    schema = {
        "type": "function",
        "function": {
            "name": "source_search",
            "description": "fake source discovery",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    def __init__(self) -> None:
        self.calls = 0

    async def invoke(self, _arguments):
        self.calls += 1
        return ToolResult(
            tool=self.name,
            status="success",
            summary="找到 1 条目标地区官方来源候选。",
            data={
                "provider": "zhipu",
                "status": "success",
                "search_executed": True,
                "requested_count": 10,
                "raw_result_count": 1,
                "scanned_result_count": 1,
                "usable_result_count": 1,
                "navigation_candidates": [],
                "estimated_cost_cny": 0.03,
                "cache_status": "miss",
                "usable_candidates": [
                    {
                        "url": "https://www.dell.com/zh-cn/example/unknown-model",
                        "status": "region_matched",
                        "usable_for_evidence": False,
                        "usable_for_checker": False,
                    }
                ],
            },
        )


def call(name: str, arguments: dict, call_id: str) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


@pytest.mark.asyncio
async def test_agent_explicit_source_search_is_audited_but_not_promoted(tmp_path) -> None:
    database = tmp_path / "catalog.sqlite"
    build_database(database)
    responses = [
        call(
            "set_requirements",
            {
                "summary": "查找目录外型号",
                "task_type": "fact",
                "hard_constraints": [
                    {"field": "model_id", "operator": "eq", "value": "UnknownModel"}
                ],
                "soft_preferences": [],
                "required_fields": ["usb_c_video"],
                "excluded_model_ids": [],
                "pending_questions": [],
            },
            "c1",
        ),
        call(
            "source_search",
            {
                "query": "UnknownModel CN official USB-C",
                "product_category": "monitor",
                "target_model": "UnknownModel",
                "target_fields": ["usb_c_video"],
                "region": "CN",
                "allowed_domains": ["dell.com"],
                "max_results": 10,
                "trigger_reason": "out_of_catalog_model",
            },
            "c2",
        ),
        call(
            "text2sql",
            {
                "sql": "SELECT model_id FROM products WHERE model_id = 'not-in-catalog'",
                "filters": [{"field": "model_id", "operator": "eq", "value": "not-in-catalog"}],
                "reason": "确认本地目录没有该型号",
            },
            "c3",
        ),
        call("finish_decision", {"stop_reason": "目录外型号未形成证据", "pending_questions": []}, "c4"),
    ]
    tools = {
        "text2sql": Text2SQLTool(database),
        "kb_search": EmptyKB(),
        "evidence_check": EvidenceCheckTool(database),
        "web_search": WebSearchTool(),
        "source_search": FakeSourceSearch(),
    }
    events = []

    async def callback(event):
        events.append(event)

    agent = PurchaseDecisionAgent(
        FakeProvider(responses),
        tools,
        preference_memory=LongTermPreferenceStore(tmp_path / "preferences.json"),
    )
    report = await agent.run("请查找目录外 UnknownModel 的官方 USB-C 资料", event_callback=callback)
    payload = report.model_dump(mode="json")

    assert "source_search" in report.tools_used
    assert report.recommended_model_ids == []
    assert "https://www.dell.com/zh-cn/example/unknown-model" not in json.dumps(
        payload, ensure_ascii=False
    )
    source_events = [item for item in events if item["type"].startswith("source_search_")]
    assert [item["type"] for item in source_events] == [
        "source_search_started",
        "source_search_completed",
    ]
    assert source_events[-1]["usable_result_count"] == 1
    assert "query" not in source_events[-1]


@pytest.mark.asyncio
async def test_agent_source_search_task_budget_is_bounded(tmp_path) -> None:
    database = tmp_path / "catalog.sqlite"
    build_database(database)
    arguments = {
        "query": "UnknownModel CN official USB-C",
        "product_category": "monitor",
        "target_model": "UnknownModel",
        "target_fields": ["usb_c_video"],
        "region": "CN",
        "allowed_domains": ["dell.com"],
        "trigger_reason": "out_of_catalog_model",
    }
    responses = [
        call(
            "set_requirements",
            {
                "summary": "查找目录外型号",
                "task_type": "fact",
                "hard_constraints": [],
                "soft_preferences": [],
                "required_fields": ["usb_c_video"],
                "excluded_model_ids": [],
                "pending_questions": [],
            },
            "c1",
        ),
        call("source_search", arguments, "c2"),
        call("source_search", arguments, "c3"),
        call("source_search", arguments, "c4"),
    ]
    source_tool = FakeSourceSearch()
    source_tool.settings = SimpleNamespace(max_tool_invocations_per_task=2)
    tools = {
        "text2sql": Text2SQLTool(database),
        "kb_search": EmptyKB(),
        "evidence_check": EvidenceCheckTool(database),
        "web_search": WebSearchTool(),
        "source_search": source_tool,
    }
    agent = PurchaseDecisionAgent(
        FakeProvider(responses),
        tools,
        preference_memory=LongTermPreferenceStore(tmp_path / "preferences.json"),
    )
    report = await agent.run("请查找目录外 UnknownModel 的官方 USB-C 资料")
    source_traces = [item for item in report.trace if item.tool == "source_search"]
    assert source_tool.calls == 2
    assert len(source_traces) == 3
    assert source_traces[-1].status == "failed"
    assert "次数上限" in source_traces[-1].result_summary
