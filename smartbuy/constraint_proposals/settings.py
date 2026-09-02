"""Default-off settings for V2 natural constraints and clarification storage."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be an explicit boolean")


class NaturalConstraintSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    llm_fallback_enabled: bool = True
    clarification_root: Path = Path("C:/ai/proofpick-v2/clarifications")
    max_provider_calls: int = Field(default=1, ge=0, le=1)
    max_cost_cny: float = Field(default=0.05, gt=0.0, le=0.25)

    @classmethod
    def from_environment(cls) -> NaturalConstraintSettings:
        return cls(
            enabled=_bool_env("PROOFPICK_NATURAL_CONSTRAINTS_ENABLED", False),
            llm_fallback_enabled=_bool_env(
                "PROOFPICK_CONSTRAINT_LLM_FALLBACK_ENABLED", True
            ),
            clarification_root=Path(
                os.getenv(
                    "PROOFPICK_CLARIFICATION_ROOT",
                    "C:/ai/proofpick-v2/clarifications",
                )
            ),
        )
