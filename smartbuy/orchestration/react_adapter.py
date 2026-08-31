"""Compatibility adapter around the unchanged V1 bounded ReAct agent."""

from __future__ import annotations

from smartbuy.orchestration.contracts import (
    CompatibleAgent,
    EventCallback,
    OrchestratorKind,
    OrchestratorRequest,
    OrchestratorResult,
    OrchestrationStatus,
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
        if request.resume_value is not None:
            raise ValueError("react orchestrator does not support checkpoint resume")
        report = await self.agent.run(
            request.query,
            session_id=request.session_id,
            user_id=request.user_id,
            use_long_term_memory=request.use_long_term_memory,
            event_callback=event_callback,
        )
        return OrchestratorResult(
            orchestrator=self.kind,
            status=OrchestrationStatus.COMPLETED,
            thread_id=request.thread_id or request.session_id or "react-stateless",
            report=report,
        )
