"""Default-off gateway that binds category routing to system-owned runtimes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict

from smartbuy.domain_packs.category_router import CategoryRoute, CategoryRouteStatus, CategoryRouter
from smartbuy.orchestration.contracts import (
    EventCallback,
    Orchestrator,
    OrchestratorRequest,
    OrchestratorResult,
    emit_event,
)


@dataclass(frozen=True)
class DomainRuntimeContext:
    domain_id: str
    domain_pack_version: str
    data_version: str
    index_version: str | None
    orchestrator: Orchestrator


class DomainGatewayResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    route: CategoryRoute
    orchestration: OrchestratorResult | None = None


class DomainAgentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False

    @classmethod
    def from_environment(cls) -> DomainAgentSettings:
        raw = os.getenv("PROOFPICK_DOMAIN_AGENT_ENABLED", "false").strip().casefold()
        if raw not in {"true", "false"}:
            raise ValueError("PROOFPICK_DOMAIN_AGENT_ENABLED must be true or false")
        return cls(enabled=raw == "true")


class DomainRuntimeRegistry:
    """The system, never an LLM, owns Pack/Data/Index bindings."""

    def __init__(self) -> None:
        self._contexts: dict[str, DomainRuntimeContext] = {}

    def register(self, context: DomainRuntimeContext) -> None:
        if context.domain_id in self._contexts:
            raise ValueError("domain runtime is already registered")
        self._contexts[context.domain_id] = context

    def get(self, domain_id: str) -> DomainRuntimeContext:
        try:
            return self._contexts[domain_id]
        except KeyError as exc:
            raise RuntimeError("domain runtime is unavailable") from exc

    def list(self) -> tuple[str, ...]:
        return tuple(sorted(self._contexts))


class DomainAgentGateway:
    def __init__(
        self,
        router: CategoryRouter,
        runtimes: DomainRuntimeRegistry,
        settings: DomainAgentSettings,
    ) -> None:
        self.router = router
        self.runtimes = runtimes
        self.settings = settings

    async def run(
        self,
        request: OrchestratorRequest,
        *,
        explicit_domain_id: str | None = None,
        allow_open: bool = False,
        event_callback: EventCallback | None = None,
    ) -> DomainGatewayResult:
        if not self.settings.enabled:
            route = CategoryRoute(status=CategoryRouteStatus.UNSUPPORTED, reason="domain_agent_disabled")
            await emit_event(event_callback, {"type": "category_route", "status": "disabled"})
            return DomainGatewayResult(route=route)
        route = self.router.route(
            request.query, explicit_domain_id=explicit_domain_id, allow_open=allow_open
        )
        await emit_event(
            event_callback,
            {
                "type": "category_route",
                "status": route.status.value,
                "domain_id": route.domain_id,
                "reason": route.reason,
            },
        )
        if route.status != CategoryRouteStatus.RESOLVED or route.domain_id is None:
            return DomainGatewayResult(route=route)
        context = self.runtimes.get(route.domain_id)
        # User text and LLM payloads have no path to these system-owned values.
        if context.domain_id != route.domain_id:
            raise RuntimeError("domain runtime identity mismatch")
        await emit_event(
            event_callback,
            {
                "type": "domain_runtime_selected",
                "domain_id": context.domain_id,
                "domain_pack_version": context.domain_pack_version,
                "data_version": context.data_version,
                "index_version": context.index_version,
            },
        )
        result = await context.orchestrator.run(request, event_callback=event_callback)
        return DomainGatewayResult(route=route, orchestration=result)
