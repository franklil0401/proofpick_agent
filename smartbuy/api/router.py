"""Sanitized HTTP/SSE and memory endpoints for the Stage 4 Agent."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, Header, HTTPException
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
    DomainPackRegistry,
    DomainPackSettings,
    DomainPackValidationError,
)
from smartbuy.domain_packs.loader import DEFAULT_MONITOR_PACK
from smartbuy.domain_packs.orchestrator import DomainPackOrchestrator
from smartbuy.memory import DomainPreferenceMemoryStore, LongTermPreferenceStore
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
from smartbuy.api.portfolio_runtime import PortfolioRuntimeManager
from smartbuy.portfolio import load_demo_bundle


router = APIRouter(prefix="/api/smartbuy", tags=["SmartBuy"])
_agent: PurchaseDecisionAgent | None = None
_orchestrator: Orchestrator | OrchestratorSelector | None = None
_domain_memories: dict[str, DomainPreferenceMemoryStore] = {}
_portfolio_runtimes = PortfolioRuntimeManager()
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
    ranking_scenario: str | None = Field(default=None, max_length=64)
    ranking_preferences: dict[str, Any] = Field(default_factory=dict)
    ranking_weight_overrides: dict[str, float] | None = None
    ranking_use_memory: bool | None = None
    ranking_what_if: bool = False


class PortfolioRunRequest(BaseModel):
    domain_id: Literal["monitor", "laptop", "headphone"]
    mode: ResearchMode = ResearchMode.TRUSTED
    query: str = Field(min_length=1, max_length=2_000)
    session_id: str | None = Field(default=None, max_length=128)
    user_id: str | None = Field(default=None, max_length=128)
    use_long_term_memory: bool = False


class PreferenceUpdate(BaseModel):
    preferences: dict[str, Any]
    explicitly_confirmed: bool = False
    domain_id: str | None = None
    scope: Literal["global", "category"] = "category"
    expires_at: str | None = None


class PreferenceDelete(BaseModel):
    fields: list[str] | None = None
    domain_id: str | None = None
    scope: Literal["global", "category"] = "category"


class PreferenceEnabled(BaseModel):
    enabled: bool
    domain_id: str | None = None


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
                "ranking_",
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
                    ranking_scenario=request.ranking_scenario,
                    ranking_preferences=request.ranking_preferences,
                    ranking_weight_overrides=request.ranking_weight_overrides,
                    ranking_use_memory=request.ranking_use_memory,
                    ranking_what_if=request.ranking_what_if,
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
                ranking_scenario=request.ranking_scenario,
                ranking_preferences=request.ranking_preferences,
                ranking_weight_overrides=request.ranking_weight_overrides,
                ranking_use_memory=request.ranking_use_memory,
                ranking_what_if=request.ranking_what_if,
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


@router.get("/portfolio/capabilities")
async def portfolio_capabilities() -> dict[str, Any]:
    bundle = load_demo_bundle()
    return {
        "product": "ProofPick",
        "release_status": "v2_release_candidate",
        "online_domain_agent_enabled": _portfolio_runtimes.enabled(),
        "replay_available": True,
        "replay_disclosure": bundle.disclosure,
        "domains": {
            "monitor": {"configuration_count": 13, "online_route": "v1_compatible"},
            "laptop": {"configuration_count": 12, "online_route": "explicit_v2"},
            "headphone": {"configuration_count": 12, "online_route": "explicit_v2"},
        },
        "modes": {
            "trusted": "governed_evidence_and_mandatory_checker",
            "open": "dedicated_script_only_not_trusted_eligible",
        },
        "demo_count": len(bundle.demos),
    }


@router.post("/portfolio/run")
async def portfolio_run(
    request: PortfolioRunRequest,
    memory_identity: str | None = Header(default=None, alias="X-ProofPick-Identity"),
) -> dict[str, Any]:
    """Run an explicitly selected online domain without changing V1 defaults."""

    if request.use_long_term_memory:
        if request.user_id is None:
            raise HTTPException(status_code=422, detail={"code": "reliable_identity_required"})
        _require_v2_memory_identity(request.user_id, memory_identity)
    if request.mode == ResearchMode.OPEN:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "online_open_requires_explicit_script",
                "message": "Open Research 在线执行使用有界验收脚本；当前 UI 可安全回放已脱敏结果。",
            },
        )
    events: list[dict[str, Any]] = []

    async def callback(event: dict[str, Any]) -> None:
        allowed = {
            "type", "status", "domain_id", "domain_pack_version", "data_version",
            "index_version", "scope_type", "resolution_status", "candidate_count",
            "clarification_required", "query_intent", "requested_fields", "node",
            "reason", "scenario", "eligible_count", "ranking_degraded",
            "ranking_profile_version", "memory_enabled", "trace",
        }
        events.append({key: value for key, value in event.items() if key in allowed})

    try:
        if request.domain_id == "monitor":
            orchestrator = get_smartbuy_orchestrator()
            data_version = "monitor_v1_compatible_runtime"
            index_version = "monitor_v1_compatible_runtime"
        else:
            runtime = _portfolio_runtimes.get(request.domain_id)
            orchestrator = runtime.orchestrator
            data_version = runtime.data_version
            index_version = runtime.index_version
        result = await orchestrator.run(
            OrchestratorRequest(
                query=request.query,
                session_id=request.session_id,
                user_id=request.user_id,
                use_long_term_memory=request.use_long_term_memory,
                mode=request.mode,
            ),
            event_callback=callback,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "online_unavailable", "reason": type(exc).__name__},
        ) from None
    if result.status == OrchestrationStatus.INTERRUPTED:
        return {
            "status": "interrupted",
            "thread_id": result.thread_id,
            "interrupt": result.interrupt,
            "events": events,
        }
    assert result.report is not None
    return {
        "status": "completed",
        "domain_id": request.domain_id,
        "data_version": data_version,
        "index_version": index_version,
        "report": result.report.model_dump(mode="json"),
        "events": events,
    }


def _preferences() -> LongTermPreferenceStore:
    return get_smartbuy_agent().preference_memory


def _domain_preferences(domain_id: str) -> DomainPreferenceMemoryStore:
    if domain_id not in _domain_memories:
        pack = DomainPackRegistry(PROJECT_ROOT / "smartbuy" / "domain_packs").load(
            domain_id
        )
        root = Path(
            os.getenv("PROOFPICK_V2_MEMORY_PATH", "C:/ai/proofpick-v2/memory")
        ).resolve()
        try:
            root.relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("V2 memory path must stay outside the repository")
        _domain_memories[domain_id] = DomainPreferenceMemoryStore(root, pack)
    return _domain_memories[domain_id]


def _require_v2_memory_identity(user_id: str, identity: str | None) -> None:
    if identity is None or not hmac.compare_digest(user_id, identity):
        raise HTTPException(status_code=403, detail="memory identity does not match")


@router.get("/memory/{user_id}")
async def view_memory(
    user_id: str,
    domain_id: str | None = None,
    memory_identity: str | None = Header(default=None, alias="X-ProofPick-Identity"),
) -> dict[str, Any]:
    try:
        if domain_id:
            _require_v2_memory_identity(user_id, memory_identity)
        return (
            _domain_preferences(domain_id).view(user_id)
            if domain_id
            else _preferences().view(user_id)
        )
    except (ValueError, DomainPackValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.put("/memory/{user_id}")
async def update_memory(
    user_id: str,
    request: PreferenceUpdate,
    memory_identity: str | None = Header(default=None, alias="X-ProofPick-Identity"),
) -> dict[str, Any]:
    try:
        if request.domain_id:
            _require_v2_memory_identity(user_id, memory_identity)
            return _domain_preferences(request.domain_id).upsert(
                user_id,
                request.preferences,
                explicitly_confirmed=request.explicitly_confirmed,
                scope=request.scope,
                expires_at=request.expires_at,
            )
        return _preferences().upsert(
            user_id,
            request.preferences,
            explicitly_confirmed=request.explicitly_confirmed,
        )
    except (ValueError, DomainPackValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.delete("/memory/{user_id}")
async def delete_memory(
    user_id: str,
    request: PreferenceDelete | None = None,
    memory_identity: str | None = Header(default=None, alias="X-ProofPick-Identity"),
) -> dict[str, Any]:
    if request and request.domain_id:
        try:
            _require_v2_memory_identity(user_id, memory_identity)
            return _domain_preferences(request.domain_id).delete(
                user_id, request.fields, scope=request.scope
            )
        except (ValueError, DomainPackValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    return _preferences().delete(user_id, request.fields if request else None)


@router.post("/memory/{user_id}/enabled")
async def enable_memory(
    user_id: str,
    request: PreferenceEnabled,
    memory_identity: str | None = Header(default=None, alias="X-ProofPick-Identity"),
) -> dict[str, Any]:
    if request.domain_id:
        try:
            _require_v2_memory_identity(user_id, memory_identity)
            return _domain_preferences(request.domain_id).set_enabled(
                user_id, request.enabled
            )
        except (ValueError, DomainPackValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    return _preferences().set_enabled(user_id, request.enabled)
