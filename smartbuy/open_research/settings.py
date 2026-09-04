"""Default-off, repository-external settings for Open Research."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_OPEN_EVIDENCE_ROOT = Path("C:/ai/proofpick-v2/open-evidence")


class OpenResearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    evidence_root: Path = DEFAULT_OPEN_EVIDENCE_ROOT
    ttl_seconds: int = Field(default=86_400, ge=60, le=604_800)
    connect_timeout_seconds: float = Field(default=5.0, ge=0.1, le=15.0)
    read_timeout_seconds: float = Field(default=10.0, ge=0.1, le=30.0)
    total_timeout_seconds: float = Field(default=20.0, ge=1.0, le=60.0)
    max_redirects: int = Field(default=3, ge=0, le=3)
    max_html_bytes: int = Field(default=5 * 1024 * 1024, ge=64 * 1024, le=5 * 1024 * 1024)
    max_pdf_bytes: int = Field(default=8 * 1024 * 1024, ge=64 * 1024, le=10 * 1024 * 1024)
    max_pdf_pages: int = Field(default=80, ge=1, le=100)
    max_snippets: int = Field(default=100, ge=1, le=100)
    max_related_fetches: int = Field(default=2, ge=0, le=3)

    @classmethod
    def from_environment(cls) -> OpenResearchSettings:
        raw = os.getenv("PROOFPICK_OPEN_RESEARCH_ENABLED", "false").strip().casefold()
        if raw not in {"true", "false"}:
            raise ValueError("PROOFPICK_OPEN_RESEARCH_ENABLED must be true or false")
        return cls(
            enabled=raw == "true",
            evidence_root=Path(
                os.getenv("PROOFPICK_OPEN_EVIDENCE_ROOT", str(DEFAULT_OPEN_EVIDENCE_ROOT))
            ),
        )

    def availability(self) -> dict[str, str]:
        return {
            "PROOFPICK_OPEN_RESEARCH_ENABLED": "enabled" if self.enabled else "disabled",
            "temporary_evidence_root": "configured" if self.evidence_root else "missing",
        }
