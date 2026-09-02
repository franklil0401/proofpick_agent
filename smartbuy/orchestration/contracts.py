"""Shared, versioned contracts for ProofPick orchestration adapters."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Awaitable, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from smartbuy.domain import DecisionReport, ResearchMode
from smartbuy.memory import LongTermPreferenceStore


ORCHESTRATION_CONTRACT_VERSION = "proofpick-orchestration-v1"
EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


class OrchestratorKind(StrEnum):
    REACT = "react"
    LANGGRAPH = "langgraph"


class OrchestrationStatus(StrEnum):
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


class OrchestratorRequest(BaseModel):
    """Input shared by the legacy ReAct and opt-in LangGraph adapters."""

    model_config = ConfigDict(extra="forbid")

    contract_version: str = ORCHESTRATION_CONTRACT_VERSION
    query: str = Field(min_length=1, max_length=2_000)
    session_id: str | None = Field(default=None, max_length=128)
    user_id: str | None = Field(default=None, max_length=128)
    thread_id: str | None = Field(default=None, max_length=128)
    use_long_term_memory: bool = False
    mode: ResearchMode = ResearchMode.TRUSTED
    resume_value: Any = None
    clarification_question: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_contract(self) -> OrchestratorRequest:
        if self.contract_version != ORCHESTRATION_CONTRACT_VERSION:
            raise ValueError("unsupported orchestration contract version")
        if self.resume_value is not None and not self.thread_id:
            raise ValueError("thread_id is required when resuming")
        return self


class OrchestratorResult(BaseModel):
    """Output shared by both adapters; interrupted runs never contain a report."""

    model_config = ConfigDict(extra="forbid")

    contract_version: str = ORCHESTRATION_CONTRACT_VERSION
    orchestrator: OrchestratorKind
    status: OrchestrationStatus
    thread_id: str
    report: DecisionReport | None = None
    interrupt: dict[str, Any] | None = None
    resumed: bool = False

    @model_validator(mode="after")
    def validate_result(self) -> OrchestratorResult:
        if self.status == OrchestrationStatus.COMPLETED and self.report is None:
            raise ValueError("completed orchestration requires a report")
        if self.status == OrchestrationStatus.INTERRUPTED and self.report is not None:
            raise ValueError("interrupted orchestration cannot expose a report")
        return self


class CompatibleAgent(Protocol):
    """Narrow V1 surface reused by both adapters without copying business rules."""

    preference_memory: LongTermPreferenceStore

    async def run(
        self,
        query: str,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        use_long_term_memory: bool = False,
        mode: ResearchMode = ResearchMode.TRUSTED,
        thread_id: str | None = None,
        event_callback: EventCallback | None = None,
    ) -> DecisionReport: ...


class Orchestrator(Protocol):
    kind: OrchestratorKind
    preference_memory: LongTermPreferenceStore

    async def run(
        self,
        request: OrchestratorRequest,
        *,
        event_callback: EventCallback | None = None,
    ) -> OrchestratorResult: ...


async def emit_event(callback: EventCallback | None, event: dict[str, Any]) -> None:
    """Emit only an already-sanitized public event."""
    if callback is None:
        return
    result = callback(event)
    if result is not None:
        await result
