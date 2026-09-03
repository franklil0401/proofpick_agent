"""Compatibility adapter around the unchanged V1 bounded ReAct agent."""

from __future__ import annotations

from smartbuy.domain import ResearchMode
from smartbuy.orchestration.contracts import (
    CompatibleAgent,
    EventCallback,
    OrchestratorKind,
    OrchestratorRequest,
    OrchestratorResult,
    OrchestrationStatus,
    emit_event,
)


class ReactOrchestrator:
    kind = OrchestratorKind.REACT

    def __init__(self, agent: CompatibleAgent) -> None:
        self.agent = agent
        self.preference_memory = agent.preference_memory

    async def run(
        self,
        request: OrchestratorRequest,
        *,
        event_callback: EventCallback | None = None,
    ) -> OrchestratorResult:
        thread_id = request.thread_id or request.session_id or "react-stateless"
        if request.clarification_question and request.resume_value is None:
            await emit_event(
                event_callback,
                {
                    "type": "interrupt_required",
                    "node": "react_compat_clarification",
                    "reason": "active_clarification",
                    "question": request.clarification_question,
                },
            )
            return OrchestratorResult(
                orchestrator=self.kind,
                status=OrchestrationStatus.INTERRUPTED,
                thread_id=thread_id,
                interrupt={
                    "kind": "clarification",
                    "question": request.clarification_question,
                    "contract_version": request.contract_version,
                },
            )
        if request.resume_value is not None and request.constraint_resolution is None:
            raise ValueError("react resume requires a validated constraint resolution")
        if request.resume_value is not None:
            await emit_event(
                event_callback,
                {
                    "type": "interrupt_resumed",
                    "node": "react_compat_clarification",
                    "status": "completed",
                },
            )
        arguments = {
            "session_id": request.session_id,
            "user_id": request.user_id,
            "use_long_term_memory": request.use_long_term_memory,
            "event_callback": event_callback,
        }
        # Preserve the exact V1 call surface for default Trusted requests and
        # older compatible test/application agents.
        if request.mode == ResearchMode.OPEN:
            arguments["mode"] = request.mode
        if request.thread_id is not None:
            arguments["thread_id"] = request.thread_id
        if request.constraint_resolution is not None:
            arguments["constraint_resolution"] = request.constraint_resolution
        if getattr(self.agent, "supports_v2_ranking", False):
            arguments.update(
                {
                    "ranking_scenario": request.ranking_scenario,
                    "ranking_preferences": request.ranking_preferences,
                    "ranking_weight_overrides": request.ranking_weight_overrides,
                    "ranking_use_memory": request.ranking_use_memory,
                    "ranking_what_if": request.ranking_what_if,
                }
            )
        report = await self.agent.run(request.query, **arguments)
        return OrchestratorResult(
            orchestrator=self.kind,
            status=OrchestrationStatus.COMPLETED,
            thread_id=thread_id,
            report=report,
            resumed=request.resume_value is not None,
        )
