"""Unified sanitized Stage 6 evaluation ledger."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EvaluationLedgerRecord(BaseModel):
    """One model/tool/final event without prompts, credentials or private text."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    case_id: str
    experiment_group: Literal[
        "direct_llm",
        "fixed_rag",
        "agentic_rag",
        "agentic_rag_checker",
        "failure",
        "memory",
        "cache",
    ]
    repetition: int = Field(ge=1)
    data_version: str
    config_hash: str
    model: str | None = None
    tool: str | None = None
    step: int = Field(ge=0)
    parent_step: int | None = None
    started_at: str
    ended_at: str
    duration_ms: float = Field(ge=0)
    status: Literal["success", "failed", "degraded", "unavailable"]
    retry_count: int = Field(default=0, ge=0)
    cache_hit: bool | None = None
    degraded: bool = False
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost_cny: float = Field(default=0.0, ge=0)
    error_category: str | None = None
    final_metrics: dict[str, Any] | None = None


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class EvaluationLedger:
    """Collect records and write one deterministic JSONL artifact at the end."""

    def __init__(self) -> None:
        self.records: list[EvaluationLedgerRecord] = []

    def add(self, record: EvaluationLedgerRecord) -> None:
        self.records.append(record)

    def extend(self, records: list[EvaluationLedgerRecord]) -> None:
        self.records.extend(records)

    def write(self, path: Path | str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = "".join(
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
            for item in self.records
        )
        target.write_text(text, encoding="utf-8", newline="\n")
