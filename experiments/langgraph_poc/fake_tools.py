"""Scriptable local tools with bounded retry behavior for the PoC."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from .contracts import ToolResult


RETRYABLE_ERRORS = {"429", "5xx", "timeout"}
NON_RETRYABLE_ERRORS = {"401", "403"}


@dataclass(frozen=True)
class FakeToolError(Exception):
    category: str


class FakeToolRegistry:
    """Execute deterministic fixture responses; never performs I/O or HTTP."""

    external_api_calls = 0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._attempts: dict[str, int] = {}
        self.call_spans: list[dict[str, float | str]] = []

    def attempts_for(self, tool: str) -> int:
        with self._lock:
            return self._attempts.get(tool, 0)

    def _next_attempt(self, tool: str) -> int:
        with self._lock:
            attempt = self._attempts.get(tool, 0) + 1
            self._attempts[tool] = attempt
        return attempt

    @staticmethod
    def _default_candidates(tool: str, fixture: dict[str, Any]) -> list[str]:
        if tool == "kb_search_targeted":
            return list(fixture.get("targeted_candidates", fixture.get("sql_candidates", [])))
        key = {
            "text2sql": "sql_candidates",
            "kb_search": "kb_candidates",
        }.get(tool)
        return list(fixture.get(key, [])) if key else list(fixture.get("candidate_pool", []))

    @staticmethod
    def _default_evidence(tool: str, candidates: list[str]) -> list[dict[str, Any]]:
        if not tool.startswith("kb_search"):
            return []
        return [
            {
                "model_id": model_id,
                "field": "fixture_fact",
                "evidence_id": f"poc:{model_id}",
                "source_id": f"poc-source:{model_id}",
            }
            for model_id in candidates
        ]

    def _execute_once(
        self,
        tool: str,
        fixture: dict[str, Any],
        *,
        timeout_ms: float,
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        attempt = self._next_attempt(tool)
        scripts = fixture.get("scripts", {}).get(tool, [])
        scripted = scripts[attempt - 1] if attempt <= len(scripts) else {}
        category = scripted.get("error")
        if category:
            raise FakeToolError(str(category))

        delay_ms = float(scripted.get("delay_ms", fixture.get("delays_ms", {}).get(tool, 0.0)))
        if delay_ms > timeout_ms:
            raise FakeToolError("timeout")
        started = time.perf_counter()
        if delay_ms:
            time.sleep(delay_ms / 1000.0)
        ended = time.perf_counter()
        with self._lock:
            self.call_spans.append({"tool": tool, "start": started, "end": ended})

        candidates = list(scripted.get("candidates", self._default_candidates(tool, fixture)))
        evidence = list(scripted.get("evidence", self._default_evidence(tool, candidates)))
        cost = float(scripted.get("estimated_cost_cny", fixture.get("tool_costs", {}).get(tool, 0.0)))
        return candidates, evidence, cost

    def execute_with_retry(
        self,
        tool: str,
        fixture: dict[str, Any],
        *,
        max_attempts: int,
        timeout_ms: float,
    ) -> ToolResult:
        started = time.perf_counter()
        attempts = 0
        last_error: str | None = None
        candidates: list[str] = []
        evidence: list[dict[str, Any]] = []
        cost = 0.0
        status = "completed"
        degraded = False

        while attempts < max(1, max_attempts):
            attempts += 1
            try:
                candidates, evidence, cost = self._execute_once(
                    tool, fixture, timeout_ms=timeout_ms
                )
                if tool.startswith("kb_search") and fixture.get("reranker_degraded"):
                    status = "degraded"
                    degraded = True
                    last_error = "reranker_5xx"
                break
            except FakeToolError as exc:
                last_error = exc.category
                if exc.category in NON_RETRYABLE_ERRORS:
                    status = "failed"
                    break
                if exc.category == "unavailable":
                    status = "unavailable"
                    degraded = True
                    break
                if exc.category not in RETRYABLE_ERRORS or attempts >= max_attempts:
                    status = "failed"
                    degraded = True
                    break

        duration_ms = (time.perf_counter() - started) * 1000.0
        return {
            "tool_call_id": f"{fixture.get('case_id', 'poc-case')}:{tool}",
            "tool": tool,
            "status": status,  # type: ignore[typeddict-item]
            "candidate_ids": candidates,
            "evidence": evidence,
            "attempts": attempts,
            "retry_count": max(0, attempts - 1),
            "duration_ms": round(duration_ms, 3),
            "estimated_cost_cny": cost,
            "degraded": degraded or status != "completed",
            "error_category": last_error,
            "summary": f"{tool}: {status}; candidates={len(candidates)}; attempts={attempts}",
        }
