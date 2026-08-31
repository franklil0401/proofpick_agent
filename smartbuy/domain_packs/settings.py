"""Default-off settings for the V2 Domain Pack compatibility path."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from smartbuy.domain_packs.loader import DEFAULT_MONITOR_PACK


class DomainPackSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    domain_id: str = "monitor"
    pack_path: Path = DEFAULT_MONITOR_PACK

    @classmethod
    def from_environment(cls) -> DomainPackSettings:
        raw = os.getenv("PROOFPICK_DOMAIN_PACK_ENABLED", "false").strip().casefold()
        if raw not in {"true", "false"}:
            raise ValueError("PROOFPICK_DOMAIN_PACK_ENABLED must be true or false")
        return cls(
            enabled=raw == "true",
            domain_id=os.getenv("PROOFPICK_DOMAIN_ID", "monitor").strip(),
            pack_path=Path(os.getenv("PROOFPICK_DOMAIN_PACK_PATH", str(DEFAULT_MONITOR_PACK))),
        )
