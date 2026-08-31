"""Deterministic parser standing in for qwen-plus during the PoC."""

from __future__ import annotations

from typing import Any


class FakeProvider:
    """Return fixture-defined routes without network or model calls."""

    external_api_calls = 0
    estimated_cost_cny = 0.0

    def __init__(self) -> None:
        self.parse_calls = 0

    def parse(self, question: str, fixture: dict[str, Any]) -> dict[str, Any]:
        self.parse_calls += 1
        return {
            "task_kind": str(fixture.get("task_kind", "mixed")),
            "needs_clarification": bool(fixture.get("needs_clarification", False)),
            "question": question,
        }
