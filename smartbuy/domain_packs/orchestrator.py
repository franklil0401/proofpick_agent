"""Default-off Domain Pack validation around the existing orchestrator."""

from __future__ import annotations

from smartbuy.domain_packs.loader import DomainPackValidationError, LoadedDomainPack
from smartbuy.domain_packs.v1_adapter import V1CompatibilityAdapter
from smartbuy.observability import agent_monitor
from smartbuy.orchestration.contracts import (
    EventCallback,
    Orchestrator,
    OrchestratorRequest,
    OrchestratorResult,
    OrchestrationStatus,
    emit_event,
)
from smartbuy.orchestration.safety import fail_closed_report


class DomainPackOrchestrator:
    """Validate V1 I/O through V2 contracts without changing V1 execution."""

    def __init__(self, underlying: Orchestrator, pack: LoadedDomainPack) -> None:
        self.underlying = underlying
        self.pack = pack
        self.adapter = V1CompatibilityAdapter(pack)

    @property
    def preference_memory(self):
        return self.underlying.preference_memory

    async def _record(
        self,
        callback: EventCallback | None,
        event_type: str,
        *,
        status: str,
        reason: str | None = None,
    ) -> None:
        payload = {
            "type": event_type,
            "requested": self.pack.domain_id,
            "selected": self.pack.version,
            "status": status,
            "reason": reason,
        }
        agent_monitor.record_orchestration_event(payload)
        await emit_event(callback, payload)

    async def run(
        self,
        request: OrchestratorRequest,
        *,
        event_callback: EventCallback | None = None,
    ) -> OrchestratorResult:
        self.adapter.from_v1_request(request)
        await self._record(event_callback, "domain_pack_selected", status="validated")
        result = await self.underlying.run(request, event_callback=event_callback)
        if result.status == OrchestrationStatus.INTERRUPTED:
            return result
        assert result.report is not None
        try:
            report = self.adapter.round_trip_report(result.report)
        except DomainPackValidationError as exc:
            await self._record(
                event_callback,
                "domain_pack_failed",
                status="fail_closed",
                reason=type(exc).__name__,
            )
            report = fail_closed_report(result.report, "domain_pack_validation_failed")
        else:
            await self._record(event_callback, "domain_pack_completed", status="compatible")
        return result.model_copy(update={"report": report})
