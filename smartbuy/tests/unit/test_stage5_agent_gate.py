"""Agent integration regression proving the deterministic gate cannot be bypassed."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from smartbuy.agent import PurchaseDecisionAgent
from smartbuy.db.build_database import build_database
from smartbuy.domain import AgentLimits
from smartbuy.memory import LongTermPreferenceStore
from smartbuy.observability import UsageLedger
from smartbuy.observability.agent_events import AgentMonitor
from smartbuy.tools import EvidenceCheckTool, Text2SQLTool, ToolResult, WebSearchTool


class FakeProvider:
    def __init__(self, calls):
        self.calls = list(calls)
        self.ledger = UsageLedger()

    async def chat(self, *_args, **_kwargs):
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
        model_id = (arguments.get("model_ids") or ["dell-g2724d-cn"])[0]
        return ToolResult(
            tool=self.name,
            status="success",
            summary="命中官方事实卡。",
            data={
                "hits": [
                    {
                        "model_id": model_id,
                        "source_id": "src-dell-g2724d-cn-product",
                        "source_url": "https://example.com/dell-g2724d",
                        "source_type": "official_product",
                        "region": "CN",
                        "section": "显示规格",
                        "accessed_at": "2026-08-26",
                    }
                ]
            },
        )


def call(name, arguments, call_id):
    return {
        "role": "assistant",
        "content": "hidden text must not be persisted",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


@pytest.mark.asyncio
async def test_s4_014_full_pool_gate_recovers_model_despite_llm_size_invention(tmp_path):
    database = tmp_path / "catalog.sqlite"
    build_database(database)
    responses = [
        call(
            "set_requirements",
            {
                "summary": "中国版 QHD 120Hz 非 OLED 无 USB-C，模型额外猜测 32 英寸",
                "task_type": "filter",
                "hard_constraints": [
                    {"field": "region", "operator": "eq", "value": "CN"},
                    {"field": "resolution", "operator": "eq", "value": "2560x1440"},
                    {"field": "refresh_rate_hz", "operator": "gte", "value": 120},
                    {"field": "is_oled", "operator": "eq", "value": False},
                    {"field": "has_usb_c", "operator": "eq", "value": False},
                    {"field": "display_size_inch", "operator": "eq", "value": 32},
                ],
                "soft_preferences": [],
                "required_fields": [
                    "region", "resolution", "refresh_rate_hz", "is_oled", "has_usb_c",
                    "display_size_inch",
                ],
                "excluded_model_ids": [],
                "pending_questions": [],
            },
            "c1",
        ),
        call(
            "text2sql",
            {
                "sql": "SELECT model_id FROM products WHERE display_size_inch=32",
                "filters": [{"field": "display_size_inch", "operator": "eq", "value": 32}],
                "reason": "模型生成了错误的附加尺寸过滤",
            },
            "c2",
        ),
        call(
            "kb_search",
            {
                "query": "G2724D 官方规格",
                "model_ids": ["dell-g2724d-cn"],
                "required_fields": ["resolution", "refresh_rate_hz", "is_oled", "has_usb_c"],
                "reason": "核验候选",
                "parent_step": 2,
            },
            "c3",
        ),
        call(
            "evidence_check",
            {
                "model_ids": ["dell-g2724d-cn"],
                "required_fields": ["resolution", "refresh_rate_hz", "is_oled", "has_usb_c"],
                "constraints": [],
                "reason": "字段证据检查",
                "parent_step": 3,
            },
            "c4",
        ),
        call("finish_decision", {"stop_reason": "完成", "pending_questions": []}, "c5"),
    ]
    agent = PurchaseDecisionAgent(
        FakeProvider(responses),
        {
            "text2sql": Text2SQLTool(database),
            "kb_search": FakeKB(),
            "evidence_check": EvidenceCheckTool(database),
            "web_search": WebSearchTool(),
        },
        preference_memory=LongTermPreferenceStore(tmp_path / "preferences.json"),
    )
    events = []

    async def capture(event):
        events.append(event)

    report = await agent.run(
        "中国版 QHD、至少 120Hz、非 OLED 且没有 USB-C 的型号有哪些？",
        session_id="s4-014-stage5",
        event_callback=capture,
    )
    assert report.recommended_model_ids == ["dell-g2724d-cn"]
    assert report.constraint_verification.candidate_pool_model_ids == ["dell-g2724d-cn"]
    assert "display_size_inch" in report.constraint_set.rejected_model_constraints
    assert not [
        item for item in report.constraint_set.active(hard_only=True)
        if item.field == "display_size_inch"
    ]
    assert [event["type"] for event in events][-3:] == [
        "constraint_check_started", "constraint_check_completed", "report"
    ]
    serialized = report.model_dump_json()
    assert "hidden text must not be persisted" not in serialized


@pytest.mark.asyncio
async def test_bounded_loop_runs_auditable_evidence_fallback_for_unsupported_field(tmp_path):
    database = tmp_path / "catalog.sqlite"
    build_database(database)
    responses = [
        call(
            "set_requirements",
            {
                "summary": "查找支持内置摄像头人脸识别的型号",
                "task_type": "filter",
                "hard_constraints": [
                    {"field": "camera", "operator": "eq", "value": True},
                    {"field": "face_recognition", "operator": "eq", "value": True},
                ],
                "soft_preferences": [],
                "required_fields": ["camera", "face_recognition"],
                "excluded_model_ids": [],
                "pending_questions": [],
            },
            "c1",
        ),
        call(
            "text2sql",
            {"sql": "SELECT model_id FROM products", "filters": [], "reason": "建立候选池"},
            "c2",
        ),
        call(
            "kb_search",
            {
                "query": "内置摄像头 人脸识别 官方资料",
                "model_ids": [],
                "required_fields": ["camera", "face_recognition"],
                "reason": "检索非结构化字段",
                "parent_step": 2,
            },
            "c3",
        ),
    ]
    agent = PurchaseDecisionAgent(
        FakeProvider(responses),
        {
            "text2sql": Text2SQLTool(database),
            "kb_search": FakeKB(),
            "evidence_check": EvidenceCheckTool(database),
            "web_search": WebSearchTool(),
        },
        limits=AgentLimits(max_steps=3),
        preference_memory=LongTermPreferenceStore(tmp_path / "preferences.json"),
    )
    report = await agent.run("这些资料里哪款显示器支持内置摄像头的人脸识别？")
    assert report.abstained is True
    assert "evidence_check" in report.tools_used
    assert report.constraint_verification.eligible_model_ids == []
    assert any("deterministic fallback" in item for item in report.degraded_states)
    evidence_trace = next(item for item in report.trace if item.tool == "evidence_check")
    assert evidence_trace.parent_step is not None
    assert evidence_trace.stop_or_degrade_reason


@pytest.mark.asyncio
async def test_numeric_source_conflict_enforces_dependent_sql_kb_evidence_order(tmp_path):
    database = tmp_path / "catalog.sqlite"
    build_database(database)
    responses = [
        call(
            "set_requirements",
            {
                "summary": "核验 PD2705U 的 USB-C 供电冲突",
                "task_type": "fact",
                "hard_constraints": [
                    {"field": "model_id", "operator": "eq", "value": "benq-pd2705u-us"}
                ],
                "soft_preferences": [],
                "required_fields": ["usb_c_power_delivery_w"],
                "excluded_model_ids": [],
                "pending_questions": [],
            },
            "c1",
        ),
        call("evidence_check", {"model_ids": ["benq-pd2705u-us"]}, "c2"),
        call("kb_search", {"query": "PD2705U 60W 65W"}, "c3"),
        call("text2sql", {"sql": "SELECT model_id FROM products"}, "c4"),
        call(
            "kb_search",
            {"query": "PD2705U 60W 65W", "model_ids": ["benq-pd2705u-us"], "parent_step": 4},
            "c5",
        ),
        call("evidence_check", {"model_ids": ["benq-pd2705u-us"], "parent_step": 5}, "c6"),
        call("finish_decision", {"stop_reason": "证据存在冲突", "pending_questions": []}, "c7"),
    ]
    agent = PurchaseDecisionAgent(
        FakeProvider(responses),
        {
            "text2sql": Text2SQLTool(database),
            "kb_search": FakeKB(),
            "evidence_check": EvidenceCheckTool(database),
            "web_search": WebSearchTool(),
        },
        preference_memory=LongTermPreferenceStore(tmp_path / "preferences.json"),
    )
    report = await agent.run("PD2705U 的 USB-C 供电到底是 60W 还是 65W？")
    successful = [
        item.tool for item in report.trace
        if item.status in {"success", "degraded"}
        and item.tool in {"text2sql", "kb_search", "evidence_check"}
    ]
    assert successful == ["text2sql", "kb_search", "evidence_check"]
    assert report.abstained is True
    assert report.task_type == "fact"
    assert report.candidates[0].overall_status.value == "conflict"


def test_monitor_keeps_only_bounded_public_checker_details():
    monitor = AgentMonitor(max_runs=1)
    monitor.record(
        {
            "session_id": "stage5-monitor",
            "constraint_checker_version": "smartbuy-constraint-checker-v1",
            "constraint_candidates": [
                {
                    "model_id": "dell-u2723qe-cn",
                    "status": "passed",
                    "eligible": True,
                    "constraint_results": [
                        {
                            "field": "usb_c_power_delivery_w",
                            "status": "passed",
                            "actual_value": 90,
                            "required_value": 90,
                            "evidence_id": "ev-dell-u2723qe-cn-usb_c_power_delivery_w-01",
                            "source_id": "src-dell-u2723qe-cn-product",
                        }
                    ],
                }
            ],
        }
    )
    result = monitor.snapshot()["recent_runs"][0]["constraint_candidates"][0]
    assert result["constraint_results"] == [
        {
            "field": "usb_c_power_delivery_w",
            "status": "passed",
            "actual_value": 90,
            "required_value": 90,
            "evidence_id": "ev-dell-u2723qe-cn-usb_c_power_delivery_w-01",
            "source_id": "src-dell-u2723qe-cn-product",
        }
    ]
