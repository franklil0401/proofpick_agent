from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from smartbuy.agent import PurchaseDecisionAgent
from smartbuy.db.build_database import build_database
from smartbuy.domain import ResearchMode
from smartbuy.domain_packs.loader import DEFAULT_MONITOR_PACK, DomainPackLoader
from smartbuy.memory import LongTermPreferenceStore
from smartbuy.observability import UsageLedger
from smartbuy.open_research import (
    OpenResearchService,
    OpenResearchSettings,
    StaticHTMLExtractor,
    TemporaryEvidenceStore,
    URLSafetyPolicy,
)
from smartbuy.source_search import SourceCandidate, SourceCandidateStatus
from smartbuy.tools import (
    EvidenceCheckTool,
    Text2SQLTool,
    ToolResult,
    WebExtractorTool,
    WebSearchTool,
)


OPEN_PAGE = """<!doctype html><html lang="en-US"><head>
<title>BenQ PD3226G | 32 inch 4K UHD 144Hz Monitor</title></head><body>
<h1>PD3226G 32 inch 4K UHD 144Hz</h1>
<p>Thunderbolt 4 carries video and delivers up to 90W of power. USB-C compatible.</p>
<table><tr><th>Resolution</th><td>3840x2160</td></tr></table>
</body></html>"""


async def public_resolver(_hostname: str) -> list[str]:
    return ["93.184.216.34"]


class FakeProvider:
    def __init__(self, calls):
        self.calls = list(calls)
        self.ledger = UsageLedger()
        self.tool_names: list[list[str]] = []

    async def chat(self, *_args, **kwargs):
        self.tool_names.append(
            [item["function"]["name"] for item in kwargs.get("tools", [])]
        )
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
        return ToolResult(tool=self.name, status="success", summary="无本地命中")


class FakeSourceSearch:
    name = "source_search"
    schema = {
        "type": "function",
        "function": {
            "name": "source_search",
            "description": "fake",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    async def invoke(self, _arguments):
        item = SourceCandidate(
            title="BenQ PD3226G official",
            url="https://www.benq.com/en-us/monitor/creative-pro/pd3226g.html",
            hostname="www.benq.com",
            site_name="BenQ",
            queried_at="2026-09-02T00:00:00Z",
            local_request_id="request-open",
            provider="fake",
            engine="fake",
            target_model="PD3226G",
            target_region="US",
            observed_region="US",
            status=SourceCandidateStatus.REGION_MATCHED,
        )
        return ToolResult(
            tool=self.name,
            status="success",
            summary="找到 1 条目标地区官方来源候选。",
            data={
                "provider": "fake",
                "status": "success",
                "search_executed": True,
                "requested_count": 10,
                "raw_result_count": 1,
                "scanned_result_count": 1,
                "usable_result_count": 1,
                "navigation_candidates": [],
                "estimated_cost_cny": 0.0,
                "cache_status": "miss",
                "usable_candidates": [item.model_dump(mode="json")],
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
async def test_open_mode_agent_extracts_but_never_recommends(tmp_path) -> None:
    database = tmp_path / "catalog.sqlite"
    build_database(database)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=OPEN_PAGE,
                headers={"content-type": "text/html; charset=utf-8"},
                request=request,
            )
        )
    )
    settings = OpenResearchSettings(enabled=True, evidence_root=tmp_path / "open-evidence")
    extractor = StaticHTMLExtractor(
        settings,
        safety_policy=URLSafetyPolicy(public_resolver),
        client=client,
    )
    service = OpenResearchService(
        settings,
        DomainPackLoader().load(DEFAULT_MONITOR_PACK),
        extractor,
        TemporaryEvidenceStore(settings.evidence_root),
    )
    url = "https://www.benq.com/en-us/monitor/creative-pro/pd3226g.html"
    responses = [
        call(
            "set_requirements",
            {
                "summary": "研究目录外 PD3226G 美国版",
                "task_type": "fact",
                "hard_constraints": [
                    {"field": "model_id", "operator": "eq", "value": "PD3226G"}
                ],
                "soft_preferences": [],
                "required_fields": ["resolution", "usb_c_power_delivery_w"],
                "excluded_model_ids": [],
                "pending_questions": [],
            },
            "c1",
        ),
        call(
            "source_search",
            {
                "query": "BenQ PD3226G US official specifications",
                "product_category": "monitor",
                "target_model": "PD3226G",
                "target_fields": ["resolution", "usb_c_power_delivery_w"],
                "region": "US",
                "allowed_domains": ["benq.com"],
                "trigger_reason": "out_of_catalog_model",
            },
            "c2",
        ),
        call(
            "web_extractor",
            {
                "source_url": url,
                "target_model": "PD3226G",
                "target_fields": ["resolution", "usb_c_power_delivery_w"],
                "region": "US",
                "allowed_domains": ["benq.com"],
                "provisional_product_id": "benq-pd3226g-us-open",
                "configuration": "PD3226G",
                "allow_region_discovery": False,
                "reason": "目录外型号需要官方正文证据",
            },
            "c3",
        ),
        call("finish_decision", {"stop_reason": "开放研究完成", "pending_questions": []}, "c4"),
    ]
    provider = FakeProvider(responses)
    tools = {
        "text2sql": Text2SQLTool(database),
        "kb_search": EmptyKB(),
        "evidence_check": EvidenceCheckTool(database),
        "web_search": WebSearchTool(),
        "source_search": FakeSourceSearch(),
        "web_extractor": WebExtractorTool(settings, service),
    }
    events: list[dict] = []

    async def callback(event):
        events.append(event)

    agent = PurchaseDecisionAgent(
        provider,
        tools,
        preference_memory=LongTermPreferenceStore(tmp_path / "preferences.json"),
    )
    report = await agent.run(
        "请开放研究 BenQ PD3226G 美国版的 4K 和供电规格",
        user_id="user-a",
        session_id="session-a",
        thread_id="thread-a",
        mode=ResearchMode.OPEN,
        event_callback=callback,
    )
    await client.aclose()

    assert report.mode == ResearchMode.OPEN
    assert report.open_research is not None
    assert report.open_research.status == "completed"
    assert report.open_research.trusted_eligible is False
    assert report.recommended_model_ids == []
    assert report.candidates == []
    assert report.constraint_verification is not None
    assert report.constraint_verification.candidate_pool_model_ids == []
    assert all("web_extractor" in names for names in provider.tool_names)
    event_types = [item["type"] for item in events]
    assert "web_extraction_started" in event_types
    assert "web_extraction_completed" in event_types
    monitor_events = [item for item in events if item["type"].startswith("web_extraction_")]
    assert url not in json.dumps(monitor_events, ensure_ascii=False)


def test_trusted_mode_tool_schema_excludes_web_extractor(tmp_path) -> None:
    database = tmp_path / "catalog.sqlite"
    build_database(database)
    provider = FakeProvider([])
    settings = OpenResearchSettings(enabled=True, evidence_root=tmp_path / "open-evidence")
    agent = PurchaseDecisionAgent(
        provider,
        {
            "text2sql": Text2SQLTool(database),
            "kb_search": EmptyKB(),
            "evidence_check": EvidenceCheckTool(database),
            "web_search": WebSearchTool(),
            "source_search": FakeSourceSearch(),
            "web_extractor": WebExtractorTool(settings, None),
        },
        preference_memory=LongTermPreferenceStore(tmp_path / "preferences.json"),
    )
    names = [item["function"]["name"] for item in agent._tool_schemas(ResearchMode.TRUSTED)]
    assert "web_extractor" not in names
