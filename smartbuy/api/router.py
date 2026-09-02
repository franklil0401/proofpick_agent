"""Sanitized HTTP/SSE and memory endpoints for the Stage 4 Agent."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from smartbuy.agent import PurchaseDecisionAgent
from smartbuy.config import load_bailian_settings
from smartbuy.constraint_proposals.coordinator import (
    ClarificationCoordinator,
    ClarificationStore,
    ClarifyingOrchestrator,
)
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.constraint_proposals.provider import QwenConstraintProposalProvider
from smartbuy.constraint_proposals.settings import NaturalConstraintSettings
from smartbuy.db.build_database import DEFAULT_OUTPUT
from smartbuy.domain_packs import (
    DomainPackLoader,
    DomainPackSettings,
    DomainPackValidationError,
)
from smartbuy.domain_packs.loader import DEFAULT_MONITOR_PACK
from smartbuy.domain_packs.orchestrator import DomainPackOrchestrator
from smartbuy.memory import LongTermPreferenceStore
from smartbuy.observability import UsageLedger, agent_monitor
from smartbuy.open_research import (
    OpenResearchService,
    OpenResearchSettings,
    ResearchMode,
    StaticHTMLExtractor,
    TemporaryEvidenceStore,
)
from smartbuy.orchestration import (
    OrchestratorRequest,
    OrchestrationStatus,
    OrchestratorSelector,
    OrchestratorSettings,
    ReactOrchestrator,
)
from smartbuy.orchestration.checkpoints import SqliteCheckpointBackend
from smartbuy.orchestration.contracts import Orchestrator
from smartbuy.orchestration.langgraph_adapter import LangGraphOrchestrator
from smartbuy.providers import BailianProvider, ZhipuSourceSearchProvider
from smartbuy.product_packs import (
    ProductPackRuntimeSettings,
    ProductPackValidationError,
    resolve_product_snapshot,
)
from smartbuy.retrieval.knowledge_base import DEFAULT_INDEX_DIR
from smartbuy.source_search import SourceSearchSettings
from smartbuy.tools import (
    EvidenceCheckTool,
    KBSearchTool,
    SourceSearchTool,
    Text2SQLTool,
    WebExtractorTool,
    WebSearchTool,
)


router = APIRouter(prefix="/api/smartbuy", tags=["SmartBuy"])
_agent: PurchaseDecisionAgent | None = None
_orchestrator: Orchestrator | OrchestratorSelector | None = None
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SmartBuyChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    stream: bool = True
    session_id: str | None = Field(default=None, max_length=128)
    user_id: str | None = Field(default=None, max_length=128)
    thread_id: str | None = Field(default=None, max_length=128)
    resume_value: str | bool | dict[str, Any] | None = None
    use_long_term_memory: bool = False
    use_natural_constraints: bool = False
    mode: ResearchMode = ResearchMode.TRUSTED


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
        try:
            product_pack_settings = ProductPackRuntimeSettings.from_environment()
            published = resolve_product_snapshot(product_pack_settings)
        except (ProductPackValidationError, ValueError) as exc:
            agent_monitor.record_orchestration_event(
                {
                    "type": "product_pack_failed",
                    "status": "initialization_fail_closed",
                    "reason": type(exc).__name__,
                }
            )
            raise
        if published:
            agent_monitor.record_orchestration_event(
                {
                    "type": "product_pack_selected",
                    "status": "validated",
                    "data_version": published.data_version,
                    "manifest_hash": published.manifest_hash,
                }
            )
        if published:
            # A published Product Pack is one immutable snapshot. Allowing legacy
            # path overrides here could mix a V1 database with V2 evidence/indexes.
            database_path = published.database_path
            index_path = published.index_dir
        else:
            database_path = Path(os.getenv("SMARTBUY_DB_PATH", str(DEFAULT_OUTPUT)))
            index_path = Path(os.getenv("SMARTBUY_INDEX_PATH", str(DEFAULT_INDEX_DIR)))
        memory_path = Path(
            os.getenv("SMARTBUY_MEMORY_PATH", "C:/ai/smartbuy-stage4/preferences.json")
        )
        kb_search = (
            KBSearchTool(
                settings,
                provider,
                index_dir=index_path,
                evidence_path=published.evidence_path,
                sources_path=published.sources_path,
                collection_name=published.collection_name,
            )
            if published
            else KBSearchTool(settings, provider, index_dir=index_path)
        )
        tools = {
            "text2sql": Text2SQLTool(database_path),
            "kb_search": kb_search,
            "evidence_check": EvidenceCheckTool(database_path),
            "web_search": WebSearchTool(),
        }
        source_settings = SourceSearchSettings.from_environment()
        if source_settings.enabled:
            source_provider = (
                ZhipuSourceSearchProvider(source_settings)
                if source_settings.api_key
                else None
            )
            tools["source_search"] = SourceSearchTool(source_settings, source_provider)
        open_settings = OpenResearchSettings.from_environment()
        if open_settings.enabled:
            monitor_pack = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
            extractor = StaticHTMLExtractor(open_settings)
            evidence_store = TemporaryEvidenceStore(
                open_settings.evidence_root, enabled=open_settings.enabled
            )
            open_service = OpenResearchService(
                open_settings,
                monitor_pack,
                extractor,
                evidence_store,
            )
            tools["web_extractor"] = WebExtractorTool(open_settings, open_service)
        _agent = PurchaseDecisionAgent(
            provider,
            tools,
            preference_memory=LongTermPreferenceStore(memory_path),
        )
    return _agent


def set_smartbuy_agent(agent: PurchaseDecisionAgent | None) -> None:
    """Test seam; production uses the lazy process singleton."""
    global _agent, _orchestrator
    _agent = agent
    _orchestrator = None


def get_smartbuy_orchestrator() -> Orchestrator | OrchestratorSelector:
    global _orchestrator
    if _orchestrator is None:
        settings = OrchestratorSettings.from_environment()
        agent = get_smartbuy_agent()

        def langgraph_factory() -> LangGraphOrchestrator:
            backend = SqliteCheckpointBackend(
                settings.checkpoint_path,
                repository_root=PROJECT_ROOT,
            )
            return LangGraphOrchestrator(agent, backend)

        selected: Orchestrator | OrchestratorSelector = OrchestratorSelector(
            ReactOrchestrator(agent),
            langgraph_factory,
            settings,
        )
        domain_settings = DomainPackSettings.from_environment()
        if domain_settings.enabled:
            try:
                pack = DomainPackLoader().load(domain_settings.pack_path)
            except DomainPackValidationError as exc:
                agent_monitor.record_orchestration_event(
                    {
                        "type": "domain_pack_failed",
                        "requested": domain_settings.domain_id,
                        "selected": None,
                        "status": "initialization_fail_closed",
                        "reason": type(exc).__name__,
                    }
                )
                raise
            if pack.domain_id != domain_settings.domain_id:
                raise DomainPackValidationError("requested domain does not match loaded pack")
            selected = DomainPackOrchestrator(selected, pack)
        natural_settings = NaturalConstraintSettings.from_environment()
        coordinator = None
        if natural_settings.enabled:
            monitor_pack = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
            proposal_provider = (
                QwenConstraintProposalProvider(agent.provider)
                if natural_settings.llm_fallback_enabled
                else None
            )
            proposal_engine = NaturalConstraintEngine(
                monitor_pack,
                proposal_provider,
                max_provider_calls=natural_settings.max_provider_calls,
                max_cost_cny=natural_settings.max_cost_cny,
            )
            clarification_store = ClarificationStore(
                natural_settings.clarification_root,
                repository_root=PROJECT_ROOT,
            )

            def constraint_context(session_id: str | None):
                if not session_id:
                    return None, 1
                snapshot = agent.session_memory.get(session_id)
                if snapshot is None:
                    return None, 1
                return snapshot.constraint_set.model_copy(deep=True), snapshot.turn_number + 1

            coordinator = ClarificationCoordinator(
                proposal_engine,
                clarification_store,
                context_loader=constraint_context,
                preference_memory=agent.preference_memory,
            )
        # Keep the gate installed even while disabled so an opt-in request can
        # never be silently interpreted by the legacy parser.
        selected = ClarifyingOrchestrator(selected, coordinator, natural_settings)
        _orchestrator = selected
    return _orchestrator


def set_smartbuy_orchestrator(
    orchestrator: Orchestrator | OrchestratorSelector | None,
) -> None:
    """Test seam for the V2 compatibility layer."""
    global _orchestrator
    _orchestrator = orchestrator


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
        elif event["type"].startswith(
            (
                "orchestrator_", "graph_", "checkpoint_", "interrupt_",
                "checker_terminal_", "domain_pack_", "product_pack_", "source_search_",
                "web_extraction_", "open_evidence_", "open_research_",
                "constraint_proposal", "clarification_",
            )
        ):
            await queue.put(event)

    async def execute() -> Any:
        try:
            return await get_smartbuy_orchestrator().run(
                OrchestratorRequest(
                    query=request.query,
                    session_id=request.session_id,
                    user_id=request.user_id,
                    thread_id=request.thread_id,
                    resume_value=request.resume_value,
                    use_long_term_memory=request.use_long_term_memory,
                    use_natural_constraints=request.use_natural_constraints,
                    mode=request.mode,
                ),
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
    result = await task
    if result is None:
        yield _sse({"type": "error", "error": "SmartBuy Agent 未完成；敏感错误细节已隐藏。"})
    elif result.status == OrchestrationStatus.INTERRUPTED:
        yield _sse(
            {
                "type": "done",
                "status": "interrupted",
                "thread_id": result.thread_id,
                "interrupt": result.interrupt,
            }
        )
    else:
        report = result.report
        assert report is not None
        yield _sse(
            {
                "type": "done",
                "final_output": report.to_markdown(),
                "report": report.model_dump(mode="json"),
            }
        )
    yield "data: [DONE]\n\n"


@router.post("/chat")
async def chat(request: SmartBuyChatRequest):
    if request.stream:
        return StreamingResponse(_stream(request), media_type="text/event-stream")
    try:
        result = await get_smartbuy_orchestrator().run(
            OrchestratorRequest(
                query=request.query,
                session_id=request.session_id,
                user_id=request.user_id,
                thread_id=request.thread_id,
                resume_value=request.resume_value,
                use_long_term_memory=request.use_long_term_memory,
                use_natural_constraints=request.use_natural_constraints,
                mode=request.mode,
            )
        )
    except Exception:
        raise HTTPException(status_code=503, detail="SmartBuy Agent unavailable; sensitive details suppressed") from None
    if result.status == OrchestrationStatus.INTERRUPTED:
        return {
            "status": "interrupted",
            "thread_id": result.thread_id,
            "interrupt": result.interrupt,
        }
    report = result.report
    assert report is not None
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
