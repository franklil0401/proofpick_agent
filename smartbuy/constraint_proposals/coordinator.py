"""Durable, repository-external clarification coordination for both orchestrators."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from smartbuy.constraints import ConstraintSet
from smartbuy.memory import LongTermPreferenceStore
from smartbuy.observability import agent_monitor
from smartbuy.orchestration.contracts import (
    EventCallback,
    Orchestrator,
    OrchestratorRequest,
    OrchestratorResult,
    OrchestrationStatus,
    emit_event,
)

from .engine import NaturalConstraintEngine
from .models import (
    ClarificationState,
    ConstraintResolution,
    PendingClarification,
    ProposalAction,
    ProposalStatus,
)
from .settings import NaturalConstraintSettings


class ClarificationStateError(RuntimeError):
    """Raised when a pending clarification is missing or cannot be trusted."""


def _identity_hash(*, user_id: str | None, session_id: str | None, thread_id: str) -> str:
    raw = "\0".join((user_id or "anonymous", session_id or "stateless", thread_id))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ClarificationStore:
    """Strict JSON store; it never uses Pickle and must live outside the repository."""

    def __init__(self, root: Path, *, repository_root: Path) -> None:
        self.root = root.resolve()
        repository = repository_root.resolve()
        if self.root == repository or repository in self.root.parents:
            raise ValueError("clarification store must be outside the repository")

    def _path(self, identity_hash: str) -> Path:
        return self.root / f"{identity_hash}.json"

    def save(self, pending: PendingClarification) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self._path(pending.identity_hash)
        handle, temporary_name = tempfile.mkstemp(
            prefix=".clarification-", suffix=".json", dir=self.root
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(pending.model_dump(mode="json"), stream, ensure_ascii=False)
                stream.write("\n")
            Path(temporary_name).replace(target)
        finally:
            temporary = Path(temporary_name)
            if temporary.exists():
                temporary.unlink()

    def load(self, identity_hash: str) -> PendingClarification:
        path = self._path(identity_hash)
        if not path.is_file():
            raise ClarificationStateError("pending clarification does not exist")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            pending = PendingClarification.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ClarificationStateError("pending clarification is invalid") from exc
        if pending.identity_hash != identity_hash:
            raise ClarificationStateError("clarification identity does not match")
        return pending

    def clear(self, identity_hash: str) -> None:
        self._path(identity_hash).unlink(missing_ok=True)


class ClarificationCoordinator:
    """Resolve constraints before tools run and persist only pending proposal state."""

    def __init__(
        self,
        engine: NaturalConstraintEngine,
        store: ClarificationStore,
        *,
        context_loader: Callable[[str | None], tuple[ConstraintSet | None, int]],
        preference_memory: LongTermPreferenceStore,
    ) -> None:
        self.engine = engine
        self.store = store
        self.context_loader = context_loader
        self.preference_memory = preference_memory

    @staticmethod
    def identity(request: OrchestratorRequest) -> str:
        if not request.thread_id:
            raise ValueError("thread_id is required for clarification")
        return _identity_hash(
            user_id=request.user_id,
            session_id=request.session_id,
            thread_id=request.thread_id,
        )

    async def prepare(self, request: OrchestratorRequest) -> ConstraintResolution:
        previous, source_turn = self.context_loader(request.session_id)
        preferences = (
            self.preference_memory.recall(
                request.user_id, requested=request.use_long_term_memory
            )
            if request.user_id
            else {}
        )
        resolution = await self.engine.resolve(
            request.query,
            source_turn=source_turn,
            previous=previous,
            preferences=preferences,
        )
        if resolution.clarification_state == ClarificationState.PENDING:
            self.store.save(
                PendingClarification(
                    identity_hash=self.identity(request),
                    created_at=datetime.now(UTC).isoformat(),
                    resolution=resolution,
                )
            )
        return resolution

    async def resume(self, request: OrchestratorRequest) -> ConstraintResolution:
        pending = self.store.load(self.identity(request))
        unresolved_fields = {
            item.field
            for item in pending.resolution.proposals
            if item.proposal_id in pending.resolution.pending_proposal_ids
            and item.normalized_value is None
        }
        if unresolved_fields and isinstance(request.resume_value, str):
            followups = self.engine.parser.parse(
                request.resume_value,
                source_turn=pending.resolution.source_turn + 1,
                previous_fields=unresolved_fields,
            )
            concrete = [
                item.model_copy(update={"action": ProposalAction.CONFIRM})
                for item in followups
                if item.field in unresolved_fields
                and item.status == ProposalStatus.SUPPORTED
                and item.normalized_value is not None
            ]
            if concrete:
                constraint_set, concrete, diff = self.engine._apply(  # noqa: SLF001
                    pending.resolution.constraint_set,
                    concrete,
                )
                original = [
                    item.model_copy(
                        update={
                            "status": ProposalStatus.INVALID,
                            "active": False,
                            "reason": "resolved_by_followup_value",
                        }
                    )
                    if item.proposal_id in pending.resolution.pending_proposal_ids
                    else item
                    for item in pending.resolution.proposals
                ]
                return pending.resolution.model_copy(
                    update={
                        "proposals": [*original, *concrete],
                        "constraint_set": constraint_set,
                        "clarification_state": ClarificationState.CONFIRMED,
                        "clarification_question": None,
                        "pending_proposal_ids": [],
                        "diff": [*pending.resolution.diff, *diff],
                    }
                )
        return self.engine.confirm(pending.resolution, request.resume_value)

    def clear(self, request: OrchestratorRequest) -> None:
        self.store.clear(self.identity(request))


class ClarifyingOrchestrator:
    """Default-off proposal gate shared by the ReAct and LangGraph paths."""

    def __init__(
        self,
        delegate: Orchestrator,
        coordinator: ClarificationCoordinator | None,
        settings: NaturalConstraintSettings,
    ) -> None:
        self.delegate = delegate
        self.coordinator = coordinator
        self.settings = settings
        self.kind = delegate.kind
        self.preference_memory = delegate.preference_memory

    @staticmethod
    async def _emit_resolution(
        callback: EventCallback | None, resolution: ConstraintResolution
    ) -> None:
        payload = {
            "type": "constraint_proposals_resolved",
            "status": resolution.clarification_state.value,
            "proposal_count": len(resolution.proposals),
            "active_constraint_count": len(resolution.constraint_set.active()),
            "proposal_statuses": [item.status.value for item in resolution.proposals],
            "proposals": [
                {
                    "field": item.field,
                    "operator": item.operator.value if item.operator else None,
                    "status": item.status.value,
                    "action": item.action.value,
                    "active": item.active,
                }
                for item in resolution.proposals
            ],
            "diff": [item.model_dump(mode="json") for item in resolution.diff],
            "provider_calls": resolution.provider_calls,
            "estimated_cost_cny": resolution.estimated_cost_cny,
        }
        agent_monitor.record_constraint_event(payload)
        await emit_event(callback, payload)

    async def run(
        self,
        request: OrchestratorRequest,
        *,
        event_callback: EventCallback | None = None,
    ) -> OrchestratorResult:
        if not request.use_natural_constraints:
            return await self.delegate.run(request, event_callback=event_callback)
        if not self.settings.enabled:
            raise RuntimeError("natural constraint feature is not enabled")
        if self.coordinator is None:
            raise RuntimeError("natural constraint coordinator is unavailable")
        thread_id = request.thread_id or request.session_id or str(uuid.uuid4())
        scoped = request.model_copy(update={"thread_id": thread_id})
        if scoped.resume_value is None:
            resolution = await self.coordinator.prepare(scoped)
            await self._emit_resolution(event_callback, resolution)
            if resolution.clarification_state == ClarificationState.PENDING:
                await emit_event(
                    event_callback,
                    {
                        "type": "clarification_pending",
                        "status": "pending",
                        "question": resolution.clarification_question,
                        "pending_count": len(resolution.pending_proposal_ids),
                    },
                )
            delegated = scoped.model_copy(
                update={
                    "clarification_question": resolution.clarification_question,
                    "constraint_resolution": resolution,
                }
            )
        else:
            resolution = await self.coordinator.resume(scoped)
            await self._emit_resolution(event_callback, resolution)
            await emit_event(
                event_callback,
                {
                    "type": "clarification_resolved",
                    "status": resolution.clarification_state.value,
                    "active_constraint_count": len(resolution.constraint_set.active()),
                },
            )
            delegated = scoped.model_copy(
                update={
                    "query": resolution.query,
                    "clarification_question": None,
                    "constraint_resolution": resolution,
                }
            )
        result = await self.delegate.run(delegated, event_callback=event_callback)
        if result.status == OrchestrationStatus.COMPLETED:
            self.coordinator.clear(scoped)
        return result
