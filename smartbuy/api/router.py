"""Sanitized HTTP/SSE and memory endpoints for the Stage 4 Agent."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from smartbuy.agent import PurchaseDecisionAgent
from smartbuy.config import load_bailian_settings
from smartbuy.db.build_database import DEFAULT_OUTPUT
from smartbuy.memory import LongTermPreferenceStore
from smartbuy.observability import UsageLedger, agent_monitor
from smartbuy.providers import BailianProvider
from smartbuy.tools import EvidenceCheckTool, KBSearchTool, Text2SQLTool, WebSearchTool


router = APIRouter(prefix="/api/smartbuy", tags=["SmartBuy"])
_agent: PurchaseDecisionAgent | None = None


class SmartBuyChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    stream: bool = True
    session_id: str | None = Field(default=None, max_length=128)
    user_id: str | None = Field(default=None, max_length=128)
    use_long_term_memory: bool = False


class PreferenceUpdate(BaseModel):
    preferences: dict[str, Any]
    explicitly_confirmed: bool = False


class PreferenceDelete(BaseModel):
    fields: list[str] | None = None


class PreferenceEnabled(BaseModel):
    enabled: bool


def get_smartbuy_agent() -> PurchaseDecisionAgent:
    global _agent
    if _agent is None:
        settings = load_bailian_settings()
        provider = BailianProvider(settings, ledger=UsageLedger(), timeout_seconds=30.0)
        tools = {
            "text2sql": Text2SQLTool(DEFAULT_OUTPUT),
            "kb_search": KBSearchTool(settings, provider),
            "evidence_check": EvidenceCheckTool(DEFAULT_OUTPUT),
            "web_search": WebSearchTool(),
        }
        _agent = PurchaseDecisionAgent(provider, tools)
    return _agent


def set_smartbuy_agent(agent: PurchaseDecisionAgent | None) -> None:
    """Test seam; production uses the lazy process singleton."""
    global _agent
    _agent = agent


def _sse(event: dict[str, Any]) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False, default=str) + "\n\n"


async def _stream(request: SmartBuyChatRequest) -> AsyncIterator[str]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def callback(event: dict[str, Any]) -> None:
        if event["type"] == "tool_observation":
            trace = event["trace"]
            await queue.put(
                {
                    "type": "tool_call",
                    "tool_name": trace["tool"],
                    "arguments": json.dumps(trace["arguments_summary"], ensure_ascii=False),
                    "mode": "json",
                }
            )
            await queue.put(
                {
                    "type": "tool_output",
                    "title": trace["tool"],
                    "output": f"[{trace['status']}] {trace['result_summary']}\n下一步：{trace['next_action']}",
                }
            )
        elif event["type"] == "constraint_check_started":
            await queue.put(event)
        elif event["type"] == "constraint_check_completed":
            await queue.put(event)

    async def execute() -> Any:
        try:
            return await get_smartbuy_agent().run(
                request.query,
                session_id=request.session_id,
                user_id=request.user_id,
                use_long_term_memory=request.use_long_term_memory,
                event_callback=callback,
            )
        except Exception:
            return None

    task = asyncio.create_task(execute())
    yield _sse({"type": "start", "message": "SmartBuy Agent 已启动"})
    while not task.done() or not queue.empty():
        try:
            event = await asyncio.wait_for(queue.get(), timeout=0.2)
        except TimeoutError:
            continue
        yield _sse(event)
    report = await task
    if report is None:
        yield _sse({"type": "error", "error": "SmartBuy Agent 未完成；敏感错误细节已隐藏。"})
    else:
        yield _sse({"type": "done", "final_output": report.to_markdown(), "report": report.model_dump(mode="json")})
    yield "data: [DONE]\n\n"


@router.post("/chat")
async def chat(request: SmartBuyChatRequest):
    if request.stream:
        return StreamingResponse(_stream(request), media_type="text/event-stream")
    try:
        report = await get_smartbuy_agent().run(
            request.query,
            session_id=request.session_id,
            user_id=request.user_id,
            use_long_term_memory=request.use_long_term_memory,
        )
    except Exception:
        raise HTTPException(status_code=503, detail="SmartBuy Agent unavailable; sensitive details suppressed") from None
    return {"report": report.model_dump(mode="json"), "markdown": report.to_markdown()}


@router.get("/monitor")
async def monitor() -> dict[str, Any]:
    return agent_monitor.snapshot()


def _preferences() -> LongTermPreferenceStore:
    return get_smartbuy_agent().preference_memory


@router.get("/memory/{user_id}")
async def view_memory(user_id: str) -> dict[str, Any]:
    return _preferences().view(user_id)


@router.put("/memory/{user_id}")
async def update_memory(user_id: str, request: PreferenceUpdate) -> dict[str, Any]:
    try:
        return _preferences().upsert(
            user_id, request.preferences, explicitly_confirmed=request.explicitly_confirmed
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.delete("/memory/{user_id}")
async def delete_memory(user_id: str, request: PreferenceDelete | None = None) -> dict[str, Any]:
    return _preferences().delete(user_id, request.fields if request else None)


@router.post("/memory/{user_id}/enabled")
async def enable_memory(user_id: str, request: PreferenceEnabled) -> dict[str, Any]:
    return _preferences().set_enabled(user_id, request.enabled)
