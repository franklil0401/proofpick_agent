"""Opt-in LangGraph shell around the existing, authoritative V1 workflow."""

from __future__ import annotations

import asyncio
import uuid
from contextvars import ContextVar
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from smartbuy.domain import DecisionReport, ResearchMode
from smartbuy.orchestration.checkpoints import (
    CHECKPOINT_STATE_VERSION,
    CheckpointBackend,
    ThreadIdentity,
)
from smartbuy.orchestration.contracts import (
    CompatibleAgent,
    EventCallback,
    ORCHESTRATION_CONTRACT_VERSION,
    OrchestratorKind,
    OrchestratorRequest,
    OrchestratorResult,
    OrchestrationStatus,
    emit_event,
)
from smartbuy.orchestration.safety import SafetyGateError, fail_closed_report, validate_checker_terminal


class LangGraphState(TypedDict, total=False):
    state_version: str
    contract_version: str
    clarification_question: str | None
    clarification_answer: Any
    report: dict[str, Any]
    checker_terminal_completed: bool
    checker_terminal_status: str
    final_report: dict[str, Any]


class IncompatibleCheckpointError(RuntimeError):
    pass


class LangGraphInitializationError(RuntimeError):
    pass


class LangGraphOrchestrator:
    """Graph lifecycle adapter; V1 agent remains the only business workflow implementation."""

    kind = OrchestratorKind.LANGGRAPH

    def __init__(self, agent: CompatibleAgent, checkpoint_backend: CheckpointBackend) -> None:
        self.agent = agent
        self.preference_memory = agent.preference_memory
        self.checkpoint_backend = checkpoint_backend
        self._graph: Any = None
        self._initialize_lock = asyncio.Lock()
        self._callback: ContextVar[EventCallback | None] = ContextVar(
            "proofpick_orchestration_callback", default=None
        )
        self._request: ContextVar[OrchestratorRequest | None] = ContextVar(
            "proofpick_orchestration_request", default=None
        )

    async def _emit(self, event_type: str, **payload: Any) -> None:
        event = {"type": event_type, **payload}
        await emit_event(self._callback.get(), event)

    async def _prepare(self, state: LangGraphState) -> dict[str, Any]:
        if state.get("state_version") != CHECKPOINT_STATE_VERSION:
            raise IncompatibleCheckpointError("checkpoint state version is not supported")
        if state.get("contract_version") != ORCHESTRATION_CONTRACT_VERSION:
            raise IncompatibleCheckpointError("orchestration contract version is not supported")
        request = self._request.get()
        if request is None:
            raise RuntimeError("orchestration request context is unavailable")
        await self._emit(
            "graph_started",
            graph="proofpick-langgraph-compat-v1",
        )
        await self._emit("graph_node_completed", node="prepare", status="completed")
        return {"clarification_question": request.clarification_question}

    @staticmethod
    def _after_prepare(state: LangGraphState) -> str:
        return "clarify" if state.get("clarification_question") else "execute_react"

    async def _clarify(self, state: LangGraphState) -> dict[str, Any]:
        question = state.get("clarification_question")
        await self._emit(
            "interrupt_required",
            node="clarify",
            reason="active_clarification",
            question=question,
        )
        answer = interrupt(
            {
                "kind": "clarification",
                "question": question,
                "contract_version": ORCHESTRATION_CONTRACT_VERSION,
            }
        )
        await self._emit("interrupt_resumed", node="clarify", status="completed")
        return {"clarification_answer": answer}

    async def _execute_react(self, state: LangGraphState) -> dict[str, Any]:
        request = self._request.get()
        if request is None:
            raise RuntimeError("orchestration request context is unavailable")
        await self._emit("graph_node_started", node="execute_react", status="running")
        arguments = {
            "session_id": request.session_id,
            "user_id": request.user_id,
            "use_long_term_memory": request.use_long_term_memory,
            "event_callback": self._callback.get(),
        }
        if request.mode == ResearchMode.OPEN:
            arguments["mode"] = request.mode
        if request.thread_id is not None:
            arguments["thread_id"] = request.thread_id
        report = await self.agent.run(request.query, **arguments)
        await self._emit("graph_node_completed", node="execute_react", status="completed")
        return {"report": report.model_dump(mode="json")}

    async def _checker_terminal(self, state: LangGraphState) -> dict[str, Any]:
        await self._emit("checker_terminal_started", node="checker_terminal", status="running")
        report = DecisionReport.model_validate(state["report"])
        status = "passed"
        try:
            validate_checker_terminal(report)
            if report.constraint_verification and report.constraint_verification.degraded:
                status = "fail_closed"
                report = fail_closed_report(
                    report,
                    report.constraint_verification.degrade_reason
                    or "constraint_checker_degraded",
                )
        except SafetyGateError as exc:
            status = "fail_closed"
            report = fail_closed_report(report, str(exc))
        await self._emit(
            "checker_terminal_completed",
            node="checker_terminal",
            status=status,
            recommendation_count=len(report.recommended_model_ids),
        )
        return {
            "report": report.model_dump(mode="json"),
            "checker_terminal_completed": True,
            "checker_terminal_status": status,
        }

    async def _report(self, state: LangGraphState) -> dict[str, Any]:
        if not state.get("checker_terminal_completed"):
            raise SafetyGateError("report_node_requires_checker_terminal")
        report = DecisionReport.model_validate(state["report"])
        if report.recommended_model_ids and state.get("checker_terminal_status") != "passed":
            raise SafetyGateError("recommendation_requires_passed_checker_terminal")
        await self._emit("graph_node_completed", node="report", status="completed")
        await self._emit("graph_completed", status="completed")
        return {"final_report": report.model_dump(mode="json")}

    def _build_graph(self, checkpointer: Any) -> Any:
        builder = StateGraph(LangGraphState)
        builder.add_node("prepare", self._prepare)
        builder.add_node("clarify", self._clarify)
        builder.add_node("execute_react", self._execute_react)
        builder.add_node("checker_terminal", self._checker_terminal)
        builder.add_node("report", self._report)
        builder.add_edge(START, "prepare")
        builder.add_conditional_edges(
            "prepare",
            self._after_prepare,
            {"clarify": "clarify", "execute_react": "execute_react"},
        )
        builder.add_edge("clarify", "execute_react")
        builder.add_edge("execute_react", "checker_terminal")
        builder.add_edge("checker_terminal", "report")
        builder.add_edge("report", END)
        return builder.compile(checkpointer=checkpointer)

    async def _ensure_graph(self) -> Any:
        if self._graph is None:
            async with self._initialize_lock:
                if self._graph is None:
                    try:
                        checkpointer = await self.checkpoint_backend.start()
                        self._graph = self._build_graph(checkpointer)
                    except Exception as exc:
                        raise LangGraphInitializationError(
                            f"LangGraph initialization failed: {type(exc).__name__}"
                        ) from exc
        return self._graph

    @staticmethod
    def _identity(request: OrchestratorRequest, thread_id: str) -> ThreadIdentity:
        return ThreadIdentity(
            user_id=request.user_id or "anonymous",
            session_id=request.session_id or "stateless",
            thread_id=thread_id,
        )

    @staticmethod
    def _config(identity: ThreadIdentity) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": identity.storage_key},
            "recursion_limit": 12,
        }

    async def _validate_resume_version(self, graph: Any, config: dict[str, Any]) -> None:
        snapshot = await graph.aget_state(config)
        values = snapshot.values or {}
        if not values:
            raise IncompatibleCheckpointError("checkpoint does not exist")
        if values.get("state_version") != CHECKPOINT_STATE_VERSION:
            raise IncompatibleCheckpointError("checkpoint state version is not supported")

    async def run(
        self,
        request: OrchestratorRequest,
        *,
        event_callback: EventCallback | None = None,
    ) -> OrchestratorResult:
        graph = await self._ensure_graph()
        thread_id = request.thread_id or request.session_id or str(uuid.uuid4())
        identity = self._identity(request, thread_id)
        config = self._config(identity)
        callback_token = self._callback.set(event_callback)
        request_token = self._request.set(request)
        resumed = request.resume_value is not None
        try:
            if resumed:
                await self._validate_resume_version(graph, config)
                await self._emit("checkpoint_resumed", status="started")
                state = await graph.ainvoke(Command(resume=request.resume_value), config=config)
            else:
                state = await graph.ainvoke(
                    {
                        "state_version": CHECKPOINT_STATE_VERSION,
                        "contract_version": ORCHESTRATION_CONTRACT_VERSION,
                        "clarification_question": request.clarification_question,
                        "checker_terminal_completed": False,
                    },
                    config=config,
                )
            if "__interrupt__" in state:
                interrupts = state["__interrupt__"]
                payload = interrupts[0].value if interrupts else {"kind": "unknown"}
                await self._emit("checkpoint_saved", status="interrupted")
                return OrchestratorResult(
                    orchestrator=self.kind,
                    status=OrchestrationStatus.INTERRUPTED,
                    thread_id=thread_id,
                    interrupt=payload,
                    resumed=resumed,
                )
            report = DecisionReport.model_validate(state["final_report"])
            await self._emit("checkpoint_saved", status="completed")
            return OrchestratorResult(
                orchestrator=self.kind,
                status=OrchestrationStatus.COMPLETED,
                thread_id=thread_id,
                report=report,
                resumed=resumed,
            )
        finally:
            self._request.reset(request_token)
            self._callback.reset(callback_token)

    async def clear_checkpoint(self, request: OrchestratorRequest) -> None:
        thread_id = request.thread_id or request.session_id
        if not thread_id:
            raise ValueError("thread_id or session_id is required to clear a checkpoint")
        await self.checkpoint_backend.clear(self._identity(request, thread_id))

    async def close(self) -> None:
        await self.checkpoint_backend.close()
