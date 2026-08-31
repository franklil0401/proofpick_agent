"""Explicit orchestration feature selection with sanitized audit events."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from smartbuy.observability import agent_monitor
from smartbuy.orchestration.contracts import (
    EventCallback,
    Orchestrator,
    OrchestratorKind,
    OrchestratorRequest,
    OrchestratorResult,
    emit_event,
)
from smartbuy.orchestration.langgraph_adapter import LangGraphInitializationError


def _explicit_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be an explicit boolean")


@dataclass(frozen=True)
class OrchestratorSettings:
    selected: OrchestratorKind = OrchestratorKind.REACT
    allow_initialization_fallback: bool = False
    checkpoint_path: Path = Path("C:/ai/proofpick-v2/checkpoints.sqlite3")

    @classmethod
    def from_environment(cls) -> OrchestratorSettings:
        raw = os.getenv("PROOFPICK_ORCHESTRATOR", OrchestratorKind.REACT.value).strip().lower()
        try:
            selected = OrchestratorKind(raw)
        except ValueError as exc:
            raise ValueError("PROOFPICK_ORCHESTRATOR must be react or langgraph") from exc
        return cls(
            selected=selected,
            allow_initialization_fallback=_explicit_bool(
                "PROOFPICK_LANGGRAPH_FALLBACK_TO_REACT", False
            ),
            checkpoint_path=Path(
                os.getenv(
                    "PROOFPICK_CHECKPOINT_PATH",
                    "C:/ai/proofpick-v2/checkpoints.sqlite3",
                )
            ),
        )


class OrchestratorSelector:
    """Select exactly one adapter; only explicit init fallback may switch engines."""

    def __init__(
        self,
        react: Orchestrator,
        langgraph_factory: Callable[[], Orchestrator],
        settings: OrchestratorSettings,
    ) -> None:
        self.react = react
        self.langgraph_factory = langgraph_factory
        self.settings = settings
        self._langgraph: Orchestrator | None = None

    @property
    def preference_memory(self):
        return self.react.preference_memory

    async def _record(
        self,
        event_callback: EventCallback | None,
        event_type: str,
        *,
        requested: OrchestratorKind,
        selected: OrchestratorKind | None,
        status: str,
        reason: str | None = None,
    ) -> None:
        payload = {
            "type": event_type,
            "requested": requested.value,
            "selected": selected.value if selected else None,
            "status": status,
            "reason": reason,
        }
        agent_monitor.record_orchestration_event(payload)
        await emit_event(event_callback, payload)

    def _selected_orchestrator(self) -> Orchestrator:
        if self.settings.selected == OrchestratorKind.REACT:
            return self.react
        if self._langgraph is None:
            self._langgraph = self.langgraph_factory()
        return self._langgraph

    async def run(
        self,
        request: OrchestratorRequest,
        *,
        event_callback: EventCallback | None = None,
    ) -> OrchestratorResult:
        requested = self.settings.selected
        try:
            selected = self._selected_orchestrator()
        except Exception as exc:
            await self._record(
                event_callback,
                "orchestrator_failed",
                requested=requested,
                selected=None,
                status="initialization_failed",
                reason=type(exc).__name__,
            )
            if requested != OrchestratorKind.LANGGRAPH or not self.settings.allow_initialization_fallback:
                raise
            await self._record(
                event_callback,
                "orchestrator_fallback",
                requested=requested,
                selected=OrchestratorKind.REACT,
                status="explicit_fallback",
                reason="langgraph_factory_failed",
            )
            return await self.react.run(request, event_callback=event_callback)

        await self._record(
            event_callback,
            "orchestrator_selected",
            requested=requested,
            selected=selected.kind,
            status="selected",
        )
        try:
            return await selected.run(request, event_callback=event_callback)
        except LangGraphInitializationError as exc:
            await self._record(
                event_callback,
                "orchestrator_failed",
                requested=requested,
                selected=OrchestratorKind.LANGGRAPH,
                status="initialization_failed",
                reason=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
            )
            if not self.settings.allow_initialization_fallback:
                raise
            await self._record(
                event_callback,
                "orchestrator_fallback",
                requested=requested,
                selected=OrchestratorKind.REACT,
                status="explicit_fallback",
                reason="langgraph_initialization_failed",
            )
            return await self.react.run(request, event_callback=event_callback)
        except Exception as exc:
            await self._record(
                event_callback,
                "orchestrator_failed",
                requested=requested,
                selected=selected.kind,
                status="runtime_failed",
                reason=type(exc).__name__,
            )
            raise
