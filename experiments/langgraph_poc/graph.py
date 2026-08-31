"""Isolated LangGraph StateGraph for V2-1B feasibility testing."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from smartbuy.constraints import CandidateConstraintVerifier, ConstraintNormalizer

from .contracts import AgentState, ToolResult, deterministic_merge, event
from .fake_provider import FakeProvider
from .fake_tools import FakeToolRegistry


AS_OF = datetime(2026, 8, 27, 0, 0, tzinfo=UTC)
DEFAULT_LIMITS: dict[str, float | int] = {
    "max_steps": 6,
    "max_tool_calls": 8,
    "max_latency_ms": 2_000.0,
    "max_cost_cny": 0.0,
    "max_retries": 2,
    "tool_timeout_ms": 500.0,
}


class SafetyGateBypassError(RuntimeError):
    """Raised if any report path is invoked without the deterministic gate."""


def _bounded_reason(value: object) -> str:
    return str(value).replace("\r", " ").replace("\n", " ")[:160]


class LangGraphPoc:
    """A removable graph that never imports into the production application."""

    def __init__(
        self,
        database_path: Path | str,
        *,
        checkpointer: BaseCheckpointSaver | None = None,
        provider: FakeProvider | None = None,
        tools: FakeToolRegistry | None = None,
        verifier_factory: Callable[[], CandidateConstraintVerifier] | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.provider = provider or FakeProvider()
        self.tools = tools or FakeToolRegistry()
        self.checkpointer = checkpointer or InMemorySaver()
        self.verifier_factory = verifier_factory or (
            lambda: CandidateConstraintVerifier(self.database_path, as_of=AS_OF)
        )
        self.nodes = self._create_nodes()
        self.graph = self._build_graph()

    @staticmethod
    def _node_update(name: str, event_name: str, status: str, summary: str) -> dict[str, Any]:
        return {
            "visited_nodes": [name],
            "events": [event(event_name, name, status, summary)],
        }

    @staticmethod
    def _elapsed_ms(state: AgentState) -> float:
        return (time.perf_counter() - float(state["started_monotonic"])) * 1000.0

    @staticmethod
    def _limit(state: AgentState, name: str) -> float:
        return float(state["limits"][name])

    def _remaining_latency_ms(self, state: AgentState) -> float:
        return max(0.0, self._limit(state, "max_latency_ms") - self._elapsed_ms(state))

    @staticmethod
    def _attempt_budgets(state: AgentState, tool_names: list[str]) -> dict[str, int]:
        remaining = max(
            0,
            int(state["limits"]["max_tool_calls"]) - int(state.get("tool_call_count", 0)) - 1,
        )
        if not tool_names or remaining < len(tool_names):
            return {}
        per_tool = max(1, remaining // len(tool_names))
        maximum = int(state["limits"]["max_retries"]) + 1
        return {name: min(per_tool, maximum) for name in tool_names}

    def _tool_node(self, tool: str) -> Callable[[AgentState], dict[str, Any]]:
        def run(state: AgentState) -> dict[str, Any]:
            budget = int(state.get("tool_attempt_budgets", {}).get(tool, 1))
            timeout_ms = min(
                self._limit(state, "tool_timeout_ms"), self._remaining_latency_ms(state)
            )
            result = self.tools.execute_with_retry(
                tool,
                state["fixture"],
                max_attempts=budget,
                timeout_ms=timeout_ms,
            )
            status = result["status"]
            update = self._node_update(
                tool,
                "tool_completed" if status == "completed" else "tool_degraded",
                status,
                result["summary"],
            )
            update.update(
                {
                    "tool_results": [result],
                    "tool_call_count": result["attempts"],
                    "retry_count": result["retry_count"],
                    "estimated_cost_cny": result["estimated_cost_cny"],
                }
            )
            return update

        return run

    def _create_nodes(self) -> dict[str, Callable[[AgentState], dict[str, Any]]]:
        normalizer = ConstraintNormalizer()

        def parse_requirements(state: AgentState) -> dict[str, Any]:
            parsed = self.provider.parse(state["question"], state["fixture"])
            constraint_set = normalizer.build(state["question"], source_turn=1)
            update = self._node_update(
                "parse_requirements", "requirements_parsed", "completed", "需求已类型化"
            )
            update.update(
                {
                    "task_kind": parsed["task_kind"],
                    "needs_clarification": parsed["needs_clarification"],
                    "constraint_set": constraint_set.model_dump(mode="json"),
                    "react_step_count": 1,
                }
            )
            if int(state["limits"]["max_steps"]) < 1:
                update["force_fail_closed_reason"] = "max_steps_exceeded"
            return update

        def clarify(state: AgentState) -> dict[str, Any]:
            answer = interrupt(
                {
                    "kind": "clarification_required",
                    "question": str(
                        state["fixture"].get("clarification_question", "请确认关键约束")
                    )[:160],
                }
            )
            update = self._node_update(
                "clarify", "clarification_resumed", "completed", "用户已确认澄清项"
            )
            update.update(
                {
                    "clarification_answer": _bounded_reason(answer),
                    "needs_clarification": False,
                }
            )
            return update

        def route_task(state: AgentState) -> dict[str, Any]:
            update = self._node_update(
                "route_task", "agent_step", "completed", f"route={state['task_kind']}"
            )
            if state.get("force_fail_closed_reason"):
                return update
            if int(state.get("react_step_count", 0)) >= int(state["limits"]["max_steps"]):
                update["force_fail_closed_reason"] = "max_steps_exceeded"
                return update
            tools = ["kb_search"] if state["task_kind"] == "fact" else ["text2sql", "kb_search"]
            budgets = self._attempt_budgets(state, tools)
            if len(budgets) != len(tools):
                update["force_fail_closed_reason"] = "max_tool_calls_exceeded"
                return update
            update["tool_attempt_budgets"] = budgets
            update["react_step_count"] = 1
            return update

        def fan_out(state: AgentState) -> dict[str, Any]:
            return self._node_update(
                "parallel_fan_out", "parallel_started", "completed", "SQL 与 KB 并行"
            )

        def merge_results(state: AgentState) -> dict[str, Any]:
            merged = deterministic_merge(state.get("tool_results", []))
            if state.get("task_kind") == "fact":
                source = next(
                    (item for item in state.get("tool_results", []) if item["tool"] == "kb_search"),
                    None,
                )
            else:
                source = next(
                    (item for item in state.get("tool_results", []) if item["tool"] == "text2sql"),
                    None,
                )
            candidate_pool = list(source["candidate_ids"]) if source else []
            candidate_pool = list(dict.fromkeys(candidate_pool))
            update = self._node_update(
                "merge_results",
                "tool_results_merged",
                "completed",
                f"候选池 {len(candidate_pool)} 个",
            )
            update.update(
                {
                    "candidate_pool_model_ids": candidate_pool,
                    "evidence_summary": merged,
                }
            )
            if state.get("task_kind") != "fact" and (
                source is None or source["status"] not in {"completed", "degraded"}
            ):
                update["force_fail_closed_reason"] = "structured_candidate_pool_unavailable"
            if int(state.get("tool_call_count", 0)) > int(state["limits"]["max_tool_calls"]):
                update["force_fail_closed_reason"] = "max_tool_calls_exceeded"
            if float(state.get("estimated_cost_cny", 0.0)) > self._limit(state, "max_cost_cny"):
                update["force_fail_closed_reason"] = "cost_limit_exceeded"
            if self._elapsed_ms(state) > self._limit(state, "max_latency_ms"):
                update["force_fail_closed_reason"] = "latency_limit_exceeded"
            if (
                state.get("task_kind") != "fact"
                and not update.get("force_fail_closed_reason")
                and int(state.get("react_step_count", 0))
                >= int(state["limits"]["max_steps"])
            ):
                update["force_fail_closed_reason"] = "max_steps_exceeded"
            if state.get("task_kind") != "fact" and not update.get("force_fail_closed_reason"):
                remaining = int(state["limits"]["max_tool_calls"]) - int(
                    state.get("tool_call_count", 0)
                )
                if remaining < 2:
                    update["force_fail_closed_reason"] = "max_tool_calls_exceeded"
                else:
                    existing = dict(state.get("tool_attempt_budgets", {}))
                    existing["kb_search_targeted"] = 1
                    update["tool_attempt_budgets"] = existing
                    update["react_step_count"] = 1
            return update

        def checkpoint_pause(state: AgentState) -> dict[str, Any]:
            answer = interrupt(
                {
                    "kind": "checkpoint_resume",
                    "completed_tools": [item["tool"] for item in state.get("tool_results", [])],
                }
            )
            return {
                **self._node_update(
                    "checkpoint_pause", "checkpoint_resumed", "completed", "从检查点恢复"
                ),
                "clarification_answer": _bounded_reason(answer),
            }

        def evidence_check(state: AgentState) -> dict[str, Any]:
            remaining = int(state["limits"]["max_tool_calls"]) - int(
                state.get("tool_call_count", 0)
            )
            if remaining < 1:
                return {
                    **self._node_update(
                        "evidence_check",
                        "tool_degraded",
                        "failed",
                        "证据检查因工具预算不足被阻断",
                    ),
                    "force_fail_closed_reason": "max_tool_calls_exceeded",
                }
            result: ToolResult = {
                "tool_call_id": f"{state['case_id']}:evidence_check",
                "tool": "evidence_check",
                "status": "completed",
                "candidate_ids": list(state.get("candidate_pool_model_ids", [])),
                "evidence": list(state.get("evidence_summary", {}).get("evidence", [])),
                "attempts": 1,
                "retry_count": 0,
                "duration_ms": 0.0,
                "estimated_cost_cny": 0.0,
                "degraded": False,
                "error_category": None,
                "summary": "evidence_check: completed",
            }
            return {
                **self._node_update(
                    "evidence_check", "tool_completed", "completed", "证据四态检查已完成"
                ),
                "tool_results": [result],
                "tool_call_count": 1,
            }

        def constraint_gate(state: AgentState) -> dict[str, Any]:
            constraint_set = normalizer.build(state["question"], source_turn=1)
            pool = list(state.get("candidate_pool_model_ids", []))
            verifier = self.verifier_factory()
            reason = state.get("force_fail_closed_reason")
            degraded = False
            try:
                if state["fixture"].get("checker_error"):
                    raise RuntimeError("injected checker failure")
                if reason:
                    batch = verifier.fail_closed(constraint_set, pool, reason)
                    degraded = True
                else:
                    batch = verifier.verify_candidates(constraint_set, pool)
            except Exception as exc:  # checker boundary must fail closed for every runtime fault
                reason = f"constraint_checker_error:{type(exc).__name__}"
                batch = verifier.fail_closed(constraint_set, pool, reason)
                degraded = True
            verification = batch.model_dump(mode="json")
            events = [
                event(
                    "constraint_check_started",
                    "constraint_gate",
                    "completed",
                    f"检查 {len(pool)} 个完整候选",
                ),
                event(
                    "constraint_check_completed",
                    "constraint_gate",
                    "degraded" if degraded or batch.degraded else "completed",
                    f"合规 {len(batch.eligible_model_ids)} 个",
                ),
            ]
            return {
                "visited_nodes": ["constraint_gate"],
                "events": events,
                "verification": verification,
                "checker_executed": True,
                "checker_degraded": degraded or batch.degraded,
                "stop_reason": reason or "constraint_check_completed",
            }

        def build_report(state: AgentState) -> dict[str, Any]:
            if not state.get("checker_executed") or not state.get("verification"):
                raise SafetyGateBypassError("report path requires completed Constraint Checker")
            verified = state["verification"]
            eligible = list(verified.get("eligible_model_ids", []))
            attempted = list(state["fixture"].get("attempt_bypass_candidates", []))
            report = {
                "status": "completed",
                "recommended_model_ids": eligible,
                "blocked_bypass_candidates": [item for item in attempted if item not in eligible],
                "checker_executed": True,
                "checker_degraded": bool(state.get("checker_degraded")),
                "semantic_fingerprint": verified.get("semantic_fingerprint"),
                "degraded_tools": state.get("evidence_summary", {}).get("degraded_tools", []),
            }
            return {
                **self._node_update(
                    "build_report", "agent_completed", "completed", "仅输出 Checker 合规集合"
                ),
                "final_report": report,
                "stop_reason": "completed",
            }

        def safe_refusal(state: AgentState) -> dict[str, Any]:
            if not state.get("checker_executed") or not state.get("verification"):
                raise SafetyGateBypassError("refusal path requires completed Constraint Checker")
            report = {
                "status": "refused",
                "recommended_model_ids": [],
                "blocked_bypass_candidates": list(
                    state["fixture"].get("attempt_bypass_candidates", [])
                ),
                "checker_executed": True,
                "checker_degraded": bool(state.get("checker_degraded")),
                "semantic_fingerprint": state["verification"].get("semantic_fingerprint"),
                "degraded_tools": state.get("evidence_summary", {}).get("degraded_tools", []),
            }
            return {
                **self._node_update(
                    "safe_refusal", "agent_completed", "degraded", "无合规候选，安全拒答"
                ),
                "final_report": report,
                "stop_reason": state.get("stop_reason") or "no_eligible_candidate",
            }

        return {
            "parse_requirements": parse_requirements,
            "clarify": clarify,
            "route_task": route_task,
            "parallel_fan_out": fan_out,
            "text2sql": self._tool_node("text2sql"),
            "kb_search": self._tool_node("kb_search"),
            "kb_search_fact": self._tool_node("kb_search"),
            "kb_search_targeted": self._tool_node("kb_search_targeted"),
            "merge_results": merge_results,
            "merge_targeted": merge_results,
            "checkpoint_pause": checkpoint_pause,
            "evidence_check": evidence_check,
            "constraint_gate": constraint_gate,
            "build_report": build_report,
            "safe_refusal": safe_refusal,
        }

    @staticmethod
    def _after_parse(state: AgentState) -> str:
        if state.get("force_fail_closed_reason"):
            return "constraint_gate"
        return "clarify" if state.get("needs_clarification") else "route_task"

    @staticmethod
    def _after_route(state: AgentState) -> str:
        if state.get("force_fail_closed_reason"):
            return "constraint_gate"
        return "kb_search_fact" if state.get("task_kind") == "fact" else "parallel_fan_out"

    @staticmethod
    def _after_merge(state: AgentState) -> str:
        if state["fixture"].get("pause_after_tools"):
            return "checkpoint_pause"
        if state.get("force_fail_closed_reason"):
            return "evidence_check"
        if state.get("task_kind") != "fact":
            return "kb_search_targeted"
        return "evidence_check"

    @staticmethod
    def _after_checkpoint(state: AgentState) -> str:
        if state.get("force_fail_closed_reason") or state.get("task_kind") == "fact":
            return "evidence_check"
        return "kb_search_targeted"

    @staticmethod
    def _after_gate(state: AgentState) -> Literal["build_report", "safe_refusal"]:
        if state.get("checker_degraded"):
            return "safe_refusal"
        eligible = state.get("verification", {}).get("eligible_model_ids", [])
        return "build_report" if eligible else "safe_refusal"

    def _build_graph(self):
        builder = StateGraph(AgentState)
        for name, node in self.nodes.items():
            builder.add_node(name, node)
        builder.add_edge(START, "parse_requirements")
        builder.add_conditional_edges(
            "parse_requirements",
            self._after_parse,
            {
                "constraint_gate": "constraint_gate",
                "clarify": "clarify",
                "route_task": "route_task",
            },
        )
        builder.add_edge("clarify", "route_task")
        builder.add_conditional_edges(
            "route_task",
            self._after_route,
            {
                "constraint_gate": "constraint_gate",
                "kb_search_fact": "kb_search_fact",
                "parallel_fan_out": "parallel_fan_out",
            },
        )
        builder.add_edge("parallel_fan_out", "text2sql")
        builder.add_edge("parallel_fan_out", "kb_search")
        builder.add_edge(["text2sql", "kb_search"], "merge_results")
        builder.add_edge("kb_search_fact", "merge_results")
        builder.add_conditional_edges(
            "merge_results",
            self._after_merge,
            {
                "checkpoint_pause": "checkpoint_pause",
                "kb_search_targeted": "kb_search_targeted",
                "evidence_check": "evidence_check",
            },
        )
        builder.add_conditional_edges(
            "checkpoint_pause",
            self._after_checkpoint,
            {
                "kb_search_targeted": "kb_search_targeted",
                "evidence_check": "evidence_check",
            },
        )
        builder.add_edge("kb_search_targeted", "merge_targeted")
        builder.add_edge("merge_targeted", "evidence_check")
        builder.add_edge("evidence_check", "constraint_gate")
        builder.add_conditional_edges(
            "constraint_gate",
            self._after_gate,
            {"build_report": "build_report", "safe_refusal": "safe_refusal"},
        )
        builder.add_edge("build_report", END)
        builder.add_edge("safe_refusal", END)
        return builder.compile(checkpointer=self.checkpointer)

    def initial_state(
        self,
        fixture: dict[str, Any],
        *,
        limits: dict[str, float | int] | None = None,
        run_id: str | None = None,
    ) -> AgentState:
        configured_limits = {**DEFAULT_LIMITS, **(limits or {})}
        return {
            "run_id": run_id or str(uuid.uuid4()),
            "case_id": str(fixture.get("case_id", "poc-case")),
            "question": str(fixture["question"]),
            "fixture": fixture,
            "limits": configured_limits,
            "started_monotonic": time.perf_counter(),
            "react_step_count": 0,
            "tool_call_count": 0,
            "retry_count": 0,
            "estimated_cost_cny": 0.0,
            "tool_results": [],
            "events": [],
            "visited_nodes": [],
            "candidate_pool_model_ids": [],
            "checker_executed": False,
            "checker_degraded": False,
        }

    @staticmethod
    def config(thread_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": thread_id}}

    def invoke(
        self,
        fixture: dict[str, Any],
        *,
        thread_id: str,
        limits: dict[str, float | int] | None = None,
    ) -> AgentState:
        return self.graph.invoke(
            self.initial_state(fixture, limits=limits),
            config=self.config(thread_id),
        )

    def resume(self, *, thread_id: str, value: Any) -> AgentState:
        return self.graph.invoke(Command(resume=value), config=self.config(thread_id))

    def topology(self) -> dict[str, list[str]]:
        graph = self.graph.get_graph()
        return {
            "nodes": sorted(graph.nodes),
            "edges": sorted(f"{edge.source}->{edge.target}" for edge in graph.edges),
        }
