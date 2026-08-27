"""Common, serializable result contract for auditable tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    tool: str
    status: Literal["success", "failed", "degraded", "unavailable"]
    data: dict[str, Any] = Field(default_factory=dict)
    summary: str
    degraded: bool = False
    retryable: bool = False
    error_code: str | None = None

    def compact(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)
