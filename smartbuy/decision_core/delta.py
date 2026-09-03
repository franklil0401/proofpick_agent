"""Deterministic state-delta view over validated constraint proposals."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from smartbuy.constraint_proposals import ConstraintResolution, ProposalAction, ProposalStatus


class ConstraintDeltaAction(StrEnum):
    ADD = "add"
    REPLACE = "replace"
    REMOVE = "remove"
    CONFIRM = "confirm"
    REJECT = "reject"
    NO_CHANGE = "no_change"


class ConstraintDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str
    action: ConstraintDeltaAction
    before: list[dict] = Field(default_factory=list)
    after: list[dict] = Field(default_factory=list)
    proposal_id: str | None = None


class ConstraintDeltaResolver:
    @staticmethod
    def from_resolution(resolution: ConstraintResolution) -> list[ConstraintDelta]:
        output: list[ConstraintDelta] = []
        mapped = {
            ProposalAction.ADD: ConstraintDeltaAction.ADD,
            ProposalAction.OVERRIDE: ConstraintDeltaAction.REPLACE,
            ProposalAction.CANCEL: ConstraintDeltaAction.REMOVE,
            ProposalAction.CONFIRM: ConstraintDeltaAction.CONFIRM,
        }
        for item in resolution.diff:
            output.append(
                ConstraintDelta(
                    field=item.field,
                    action=mapped[item.action],
                    before=item.before,
                    after=item.after,
                    proposal_id=item.proposal_id,
                )
            )
        rejected = {
            item.field: item for item in resolution.proposals
            if item.status == ProposalStatus.INVALID
            and item.reason == "user_rejected_clarification"
        }
        output.extend(
            ConstraintDelta(
                field=field,
                action=ConstraintDeltaAction.REJECT,
                proposal_id=item.proposal_id,
            )
            for field, item in rejected.items()
        )
        if not output:
            output.append(
                ConstraintDelta(field="*", action=ConstraintDeltaAction.NO_CHANGE)
            )
        return output
