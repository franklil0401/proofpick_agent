"""JSON-safe state and tool contracts used only by the LangGraph PoC."""

from __future__ import annotations

import json
import operator
from typing import Annotated, Any, Literal, TypedDict


ToolStatus = Literal["completed", "degraded", "failed", "unavailable"]


class ToolResult(TypedDict):
    tool_call_id: str
    tool: str
    status: ToolStatus
    candidate_ids: list[str]
    evidence: list[dict[str, Any]]
    attempts: int
    retry_count: int
    duration_ms: float
    estimated_cost_cny: float
    degraded: bool
    error_category: str | None
    summary: str


class PocEvent(TypedDict):
    event: str
    node: str
    status: str
    summary: str
    parent_step: str | None


def append_items(left: list[Any], right: list[Any]) -> list[Any]:
    """Append reducer for parallel graph branches."""
    return [*left, *right]


class AgentState(TypedDict, total=False):
    run_id: str
    case_id: str
    question: str
    fixture: dict[str, Any]
    task_kind: str
    needs_clarification: bool
    clarification_answer: str | None
    constraint_set: dict[str, Any]
    limits: dict[str, float | int]
    tool_attempt_budgets: dict[str, int]
    force_fail_closed_reason: str | None
    started_monotonic: float
    react_step_count: Annotated[int, operator.add]
    tool_call_count: Annotated[int, operator.add]
    retry_count: Annotated[int, operator.add]
    estimated_cost_cny: Annotated[float, operator.add]
    tool_results: Annotated[list[ToolResult], append_items]
    events: Annotated[list[PocEvent], append_items]
    visited_nodes: Annotated[list[str], append_items]
    candidate_pool_model_ids: list[str]
    evidence_summary: dict[str, Any]
    verification: dict[str, Any]
    checker_executed: bool
    checker_degraded: bool
    final_report: dict[str, Any]
    stop_reason: str


TOOL_ORDER = {
    "text2sql": 0,
    "kb_search": 1,
    "kb_search_targeted": 2,
    "evidence_check": 3,
}


def deterministic_merge(results: list[ToolResult]) -> dict[str, Any]:
    """Merge parallel ToolResults without depending on completion order."""
    ordered = sorted(
        results,
        key=lambda item: (
            TOOL_ORDER.get(item["tool"], 99),
            item["tool"],
            item["tool_call_id"],
            json.dumps(item["candidate_ids"], ensure_ascii=False, sort_keys=True),
        ),
    )
    candidates: list[str] = []
    evidence: list[dict[str, Any]] = []
    statuses: dict[str, str] = {}
    degraded_tools: list[str] = []
    seen_calls: set[str] = set()
    for item in ordered:
        if item["tool_call_id"] in seen_calls:
            continue
        seen_calls.add(item["tool_call_id"])
        statuses[item["tool"]] = item["status"]
        if item["degraded"] or item["status"] in {"degraded", "failed", "unavailable"}:
            degraded_tools.append(item["tool"])
        for model_id in item["candidate_ids"]:
            if model_id not in candidates:
                candidates.append(model_id)
        evidence.extend(item["evidence"])
    evidence.sort(
        key=lambda item: (
            str(item.get("model_id", "")),
            str(item.get("field", "")),
            str(item.get("evidence_id", "")),
        )
    )
    deduplicated_evidence: list[dict[str, Any]] = []
    seen_evidence: set[str] = set()
    for item in evidence:
        identity = str(item.get("evidence_id") or json.dumps(item, sort_keys=True))
        if identity in seen_evidence:
            continue
        seen_evidence.add(identity)
        deduplicated_evidence.append(item)
    return {
        "candidate_pool_model_ids": candidates,
        "evidence": deduplicated_evidence,
        "tool_statuses": statuses,
        "degraded_tools": list(dict.fromkeys(degraded_tools)),
    }


def event(
    name: str,
    node: str,
    status: str,
    summary: str,
    *,
    parent_step: str | None = None,
) -> PocEvent:
    """Create a bounded, content-free event suitable for SSE/Monitor mapping."""
    return {
        "event": name[:64],
        "node": node[:64],
        "status": status[:24],
        "summary": summary[:160],
        "parent_step": parent_step[:64] if parent_step else None,
    }
