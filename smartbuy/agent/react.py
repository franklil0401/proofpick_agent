"""A bounded qwen-plus Tool Calling loop with sanitized, auditable observations."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import sqlite3
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from smartbuy.agent.ranking import rank_compliant_candidates
from smartbuy.agent.reporting import build_report
from smartbuy.constraints import (
    CandidateConstraintVerifier,
    ConstraintNormalizer,
    ConstraintOperator as GateOperator,
    ConstraintSet,
    ConstraintStrength,
    VERIFIER_VERSION,
)
from smartbuy.constraint_proposals.models import ConstraintResolution
from smartbuy.decision_core.requirements import audit_requirement_coverage
from smartbuy.domain_packs import DomainPackLoader, DEFAULT_MONITOR_PACK
from smartbuy.identity import resolve_catalog_identity
from smartbuy.domain import (
    AgentLimits,
    AgentState,
    ConstraintOperator,
    ConstraintSpec,
    DecisionReport,
    EvidenceReference,
    FieldAssessment,
    ResearchMode,
    ToolTrace,
    UserRequirements,
)
from smartbuy.memory import LongTermPreferenceStore, SessionMemoryStore
from smartbuy.observability import agent_monitor
from smartbuy.tools import ToolResult
from smartbuy.open_research.models import OpenResearchReport


EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


SYSTEM_PROMPT = """你是 SmartBuy 显示器消费决策 Agent。你必须通过工具观察结果逐步规划，不能凭记忆补全商品事实。
规则：
1. 首次调用 set_requirements，区分硬约束、软偏好、必要字段和待确认项；连续追问要覆盖被修改的旧条件。
   task_type 必须标成 fact/filter/comparison/dynamic/unrelated；“哪款满足”是 filter，“A 和 B 哪个”是 comparison。
2. 简单官方事实只用 kb_search；参数筛选先用 text2sql，再基于候选型号用 kb_search 核验官方资料，最后用 evidence_check 检查字段完整性。
3. 下一跳必须依赖上一跳候选、缺失字段或冲突；不得无目的重复搜索。
4. 证据的 matched/not_matched/unknown/conflict 只能采用 evidence_check 结果，不能用 Reranker 分数替代。
5. Web Search unavailable 时继续 KB + SQL；不得虚构动态价格或库存。
6. 候选存在但未执行 evidence_check 时不得 finish。关键字段 unknown/conflict 时不得声称完全满足。
7. 不输出隐藏思维链。工具 reason 只写一句可公开的行动理由，不超过 200 字。
8. 必须在预算和最大步骤内调用 finish_decision；若证据不足应明确拒答。
9. 你提出的约束只是建议；只有 provenance gate 从用户当前输入、会话确认或已启用偏好中确定的约束有效。
10. finish_decision 后系统仍会对完整工具候选池强制运行 Constraint Checker；你不能跳过、覆盖或修改其结果。
可查询表：products、price_observations、source_records、evidence_records。SQL 只能是一条 SELECT。
"""


SET_REQUIREMENTS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "set_requirements",
        "description": "结构化当前需求；这是每轮任务的第一个工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "maxLength": 300},
                "task_type": {
                    "type": "string",
                    "enum": ["fact", "filter", "comparison", "dynamic", "unrelated"],
                },
                "hard_constraints": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "operator": {"type": "string", "enum": ["eq", "lte", "gte", "in", "not_in"]},
                            "value": {},
                            "hard": {"type": "boolean"},
                        },
                        "required": ["field", "operator", "value"],
                    },
                },
                "soft_preferences": {"type": "array", "items": {"type": "string"}},
                "required_fields": {"type": "array", "items": {"type": "string"}},
                "excluded_model_ids": {"type": "array", "items": {"type": "string"}},
                "pending_questions": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "summary", "task_type", "hard_constraints", "soft_preferences", "required_fields", "pending_questions"
            ],
            "additionalProperties": False,
        },
    },
}


FINISH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "finish_decision",
        "description": "证据充分或已确认无法补足时停止；报告由工具观察确定性生成。",
        "parameters": {
            "type": "object",
            "properties": {
                "stop_reason": {"type": "string", "maxLength": 300},
                "pending_questions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["stop_reason", "pending_questions"],
            "additionalProperties": False,
        },
    },
}


class PurchaseDecisionAgent:
    """Execute a bounded public-observation loop; no model reasoning is logged or returned."""

    def __init__(
        self,
        provider: Any,
        tools: dict[str, Any],
        *,
        limits: AgentLimits | None = None,
        session_memory: SessionMemoryStore | None = None,
        preference_memory: LongTermPreferenceStore | None = None,
        constraint_normalizer: ConstraintNormalizer | None = None,
        constraint_verifier: CandidateConstraintVerifier | None = None,
        enable_constraint_checker: bool = True,
    ) -> None:
        self.provider = provider
        self.tools = tools
        self.limits = limits or AgentLimits()
        self.session_memory = session_memory or SessionMemoryStore()
        self.preference_memory = preference_memory or LongTermPreferenceStore()
        self.constraint_normalizer = constraint_normalizer or ConstraintNormalizer()
        self.requirement_pack = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
        expected = {"text2sql", "kb_search", "evidence_check", "web_search"}
        missing = expected - set(tools)
        if missing:
            raise ValueError(f"missing required tools: {sorted(missing)}")
        database_path = getattr(tools["text2sql"], "database_path", None)
        if enable_constraint_checker and constraint_verifier is None and database_path is None:
            raise ValueError("constraint_verifier is required when Text2SQL has no database_path")
        self.enable_constraint_checker = enable_constraint_checker
        self.constraint_verifier = (
            constraint_verifier
            or (CandidateConstraintVerifier(database_path) if enable_constraint_checker else None)
        )

    @property
    def tool_schemas(self) -> list[dict[str, Any]]:
        return self._tool_schemas(ResearchMode.TRUSTED)

    def _tool_schemas(self, mode: ResearchMode) -> list[dict[str, Any]]:
        names = [
            name
            for name in sorted(self.tools)
            if name != "web_extractor" or mode == ResearchMode.OPEN
        ]
        return [SET_REQUIREMENTS_SCHEMA, *[self.tools[name].schema for name in names], FINISH_SCHEMA]

    @staticmethod
    def _safe_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        if name == "text2sql":
            safe["sql"] = " ".join(str(arguments.get("_executed_sql", "")).split())[:3000]
            safe["executed_sql"] = safe["sql"]
            safe["suggested_sql"] = " ".join(str(arguments.get("sql", "")).split())[:500]
            safe["effective_filters"] = list(arguments.get("filters", []))[:30]
            safe["execution_mode"] = "deterministic_template"
            safe["filter_count"] = len(arguments.get("filters", []))
        elif name in {"kb_search", "web_search"}:
            safe["query_summary"] = str(arguments.get("query", ""))[:160]
            safe["model_ids"] = list(arguments.get("model_ids", []))[:10]
            safe["required_fields"] = list(arguments.get("required_fields", []))[:15]
        elif name == "source_search":
            safe["target_model"] = str(arguments.get("target_model", ""))[:100]
            safe["target_fields"] = list(arguments.get("target_fields", []))[:15]
            safe["region"] = str(arguments.get("region", ""))[:8]
            safe["allowed_domains"] = list(arguments.get("allowed_domains", []))[:10]
            safe["trigger_reason"] = str(arguments.get("trigger_reason", ""))[:40]
        elif name == "web_extractor":
            safe["target_model"] = str(arguments.get("target_model", ""))[:100]
            safe["target_fields"] = list(arguments.get("target_fields", []))[:15]
            safe["region"] = str(arguments.get("region", ""))[:8]
            safe["source_candidate_observed"] = bool(arguments.get("_source_candidate"))
            safe["allow_region_discovery"] = bool(arguments.get("allow_region_discovery", False))
        elif name == "evidence_check":
            safe["model_ids"] = list(arguments.get("model_ids", []))[:10]
            safe["required_fields"] = list(arguments.get("required_fields", []))[:15]
            safe["constraint_count"] = len(arguments.get("constraints", []))
        elif name == "set_requirements":
            safe["summary"] = str(arguments.get("summary", ""))[:200]
            safe["required_fields"] = list(arguments.get("required_fields", []))[:15]
            safe["constraint_count"] = len(arguments.get("hard_constraints", []))
        elif name == "finish_decision":
            safe["agent_requested_stop"] = True
        if arguments.get("reason"):
            safe["reason"] = str(arguments["reason"])[:200]
        return safe

    @staticmethod
    def _usage(provider: Any, start_index: int) -> dict[str, Any]:
        ledger = getattr(provider, "ledger", None)
        if ledger is None:
            return {"call_count": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_cny": 0.0}
        records = ledger.snapshot()[start_index:]
        return {
            "call_count": len(records),
            "successful_calls": sum(bool(item["success"]) for item in records),
            "degraded_calls": sum(bool(item["degraded"]) for item in records),
            "input_tokens": sum(int(item["input_tokens"]) for item in records),
            "output_tokens": sum(int(item["output_tokens"]) for item in records),
            "estimated_cost_cny": round(sum(float(item["estimated_cost_cny"]) for item in records), 8),
        }

    async def _emit(self, callback: EventCallback | None, event: dict[str, Any]) -> None:
        if callback is None:
            return
        result = callback(event)
        if inspect.isawaitable(result):
            await result

    async def _incomplete_requirements_report(
        self, state: AgentState, coverage: Any, started: float,
        callback: EventCallback | None, usage: dict[str, Any] | None = None,
    ) -> DecisionReport:
        unresolved = [row for row in coverage.obligations if not row["resolved"]]
        questions = [
            f"请确认可执行的要求：{row['source_text']}（{row['reason']}）。"
            for row in unresolved
        ]
        report = DecisionReport(
            request_summary=state.query[:300], task_type="filter",
            constraint_set=state.constraint_set,
            hard_constraints=self._legacy_constraints(state.constraint_set),
            clarification_state="pending", pending_questions=questions,
            abstained=True, recommended_model_ids=[],
            stop_reason="明确硬要求尚未完整绑定，已暂停；不能按部分条件宣称完全满足。",
            trace=state.traces, tool_call_count=state.tool_call_count,
            usage={
                **(usage or {"call_count": 0, "input_tokens": 0, "output_tokens": 0,
                             "estimated_cost_cny": 0.0}),
                "result_status": "needs_clarification",
                "requirement_coverage": coverage.public(),
            },
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        await self._emit(callback, {"type": "requirement_coverage", "status": "pending",
                                   "reason": "incomplete_user_requirements"})
        await self._emit(callback, {"type": "report", "report": report.model_dump(mode="json")})
        return report

    @staticmethod
    def _legacy_constraints(constraint_set: ConstraintSet) -> list[ConstraintSpec]:
        output: list[ConstraintSpec] = []
        operator_map = {
            GateOperator.EQ: ConstraintOperator.EQ,
            GateOperator.LTE: ConstraintOperator.LTE,
            GateOperator.GTE: ConstraintOperator.GTE,
            GateOperator.IN: ConstraintOperator.IN,
            GateOperator.NOT_IN: ConstraintOperator.NOT_IN,
        }
        for item in constraint_set.active(hard_only=True, supported_only=True):
            if item.operator == GateOperator.RANGE and isinstance(item.normalized_value, list):
                output.extend(
                    [
                        ConstraintSpec(
                            field=item.field,
                            operator=ConstraintOperator.GTE,
                            value=item.normalized_value[0],
                        ),
                        ConstraintSpec(
                            field=item.field,
                            operator=ConstraintOperator.LTE,
                            value=item.normalized_value[1],
                        ),
                    ]
                )
            elif item.operator in operator_map:
                output.append(
                    ConstraintSpec(
                        field=item.field,
                        operator=operator_map[item.operator],
                        value=item.normalized_value,
                    )
                )
        return output

    @staticmethod
    def _gated_locators(query: str, constraints: list[ConstraintSpec]) -> list[ConstraintSpec]:
        compact = re.sub(r"[^a-z0-9]", "", query.lower())
        output: list[ConstraintSpec] = []
        for item in constraints:
            if item.field not in {"model_id", "model_name"}:
                continue
            values = item.value if isinstance(item.value, list) else [item.value]
            accepted = []
            for value in values:
                tokens = [token for token in re.split(r"[^a-z0-9]+", str(value).lower()) if len(token) >= 4]
                if any(token in compact for token in tokens):
                    accepted.append(value)
            if accepted:
                output.append(
                    ConstraintSpec(
                        field=item.field,
                        operator=ConstraintOperator.IN if len(accepted) > 1 else ConstraintOperator.EQ,
                        value=accepted if len(accepted) > 1 else accepted[0],
                    )
                )
        return output

    @staticmethod
    def _deterministic_filters(constraint_set: ConstraintSet) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = []
        for item in constraint_set.active(hard_only=True, supported_only=True):
            if item.operator == GateOperator.RANGE and isinstance(item.normalized_value, list):
                filters.extend(
                    [
                        {"field": item.field, "operator": "gte", "value": item.normalized_value[0]},
                        {"field": item.field, "operator": "lte", "value": item.normalized_value[1]},
                    ]
                )
            elif item.operator == GateOperator.CONTAINS_ALL:
                continue
            elif item.field == "resolution" and item.operator == GateOperator.GTE:
                continue
            elif item.operator.value in {"eq", "lte", "gte", "in", "not_in"}:
                filters.append(
                    {
                        "field": item.field,
                        "operator": item.operator.value,
                        "value": item.normalized_value,
                    }
                )
        return filters

    @staticmethod
    def _remember_candidate(
        state: AgentState, model_id: str, row: dict[str, Any], source: str
    ) -> None:
        if not model_id or (
            state.product_scope is not None and not state.product_scope.permits(model_id)
        ):
            return
        existing = state.candidate_pool_rows.get(model_id, {})
        state.candidate_pool_rows[model_id] = {
            **existing,
            **{key: value for key, value in row.items() if value is not None},
            "model_id": model_id,
        }
        sources = state.candidate_pool_sources.setdefault(model_id, [])
        if source not in sources:
            sources.append(source)

    def _start_state(
        self,
        query: str,
        session_id: str,
        user_id: str | None,
        mode: ResearchMode,
        thread_id: str | None,
    ) -> tuple[AgentState, UserRequirements | None, ConstraintSet | None]:
        previous = self.session_memory.get(session_id)
        if previous is None:
            return AgentState(
                session_id=session_id,
                user_id=user_id,
                query=query,
                mode=mode,
                thread_id=thread_id,
            ), None, None
        previous_requirements = previous.requirements.model_copy(deep=True)
        previous_constraints = previous.constraint_set.model_copy(deep=True)
        previous.query = query
        previous.user_id = user_id or previous.user_id
        previous.mode = mode
        previous.thread_id = thread_id
        previous.turn_number += 1
        previous.traces = []
        previous.degraded_states = []
        previous.tool_call_count = 0
        previous.stop_reason = None
        previous.finished = False
        previous.constraint_verification = None
        previous.ranked_eligible_model_ids = []
        previous.candidate_explanations = {}
        previous.source_candidates = {}
        previous.open_research = None
        return previous, previous_requirements, previous_constraints

    async def _invoke_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        state: AgentState,
        previous_requirements: UserRequirements | None,
        previous_constraints: ConstraintSet | None,
        preferences: dict[str, Any],
    ) -> ToolResult:
        if name == "set_requirements":
            try:
                current = UserRequirements.model_validate(arguments)
            except ValidationError:
                return ToolResult(
                    tool=name, status="failed", error_code="INVALID_REQUIREMENTS",
                    summary="需求结构未通过 Schema 校验。",
                )
            current.task_type = self._infer_task_type(state.query, current.task_type)
            model_proposals = [
                item.model_dump(mode="json") for item in current.hard_constraints
            ]
            current = self._augment_requirements(state.query, current)
            if state.constraint_resolution is not None:
                state.constraint_set = state.constraint_resolution.constraint_set.model_copy(
                    deep=True
                )
                active_fields = {item.field for item in state.constraint_set.active()}
                state.constraint_set.rejected_model_constraints.extend(
                    sorted(
                        {
                            str(item.get("field", "unknown"))
                            for item in model_proposals
                            if item.get("field") not in active_fields
                            and item.get("field") not in {"model_id", "model_name"}
                        }
                    )
                )
            else:
                state.constraint_set = self.constraint_normalizer.build(
                    state.query,
                    source_turn=state.turn_number,
                    previous=previous_constraints,
                    preferences=preferences,
                    model_proposals=model_proposals,
                )
            state.constraint_set = self._gate_non_purchase_constraints(
                state.constraint_set,
                current.task_type,
            )
            current_locators = self._gated_locators(state.query, current.hard_constraints)
            previous_locators = (
                [
                    item
                    for item in previous_requirements.hard_constraints
                    if item.field in {"model_id", "model_name"}
                ]
                if previous_requirements else []
            )
            if state.product_scope is not None:
                # Catalog-owned identities, never a model's shared-token match.
                locators = [ConstraintSpec(
                    field="model_id", operator=ConstraintOperator.IN,
                    value=list(state.product_scope.product_ids),
                )] if (
                    state.product_scope.include_product_ids or state.product_scope.include_family_ids
                ) else []
            else:
                locators = current_locators or previous_locators
            current.hard_constraints = [*locators, *self._legacy_constraints(state.constraint_set)]
            current.required_fields = list(
                dict.fromkeys(
                    [
                        *current.required_fields,
                        *(item.field for item in state.constraint_set.active()),
                    ]
                )
            )
            for item in state.constraint_set.active():
                if item.ambiguous or not item.supported:
                    current.pending_questions.append(item.note or f"无法确定性处理约束：{item.field}")
                if item.hard_or_soft == ConstraintStrength.SOFT and item.source_text not in current.soft_preferences:
                    current.soft_preferences.append(item.source_text)
            merged = (
                self.session_memory.merge_requirements(previous_requirements, current)
                if previous_requirements else current
            )
            merged.hard_constraints = [*locators, *self._legacy_constraints(state.constraint_set)]
            merged.required_fields = list(
                dict.fromkeys([*merged.required_fields, *(item.field for item in state.constraint_set.active())])
            )
            state.requirements = merged
            coverage = audit_requirement_coverage(
                state.query, state.constraint_set, self.requirement_pack,
                purchase=current.task_type in {"filter", "dynamic"},
            )
            if not coverage.complete:
                state.finished = True
                state.stop_reason = "明确硬要求尚未完整绑定，暂停以等待澄清。"
                return ToolResult(
                    tool=name, status="failed", error_code="INCOMPLETE_USER_REQUIREMENTS",
                    summary=state.stop_reason, data={"requirement_coverage": coverage.public()},
                )
            return ToolResult(
                tool=name,
                status="success",
                summary=(
                    "已由 provenance gate 建立带来源约束；"
                    f"active={len(state.constraint_set.active())}，"
                    f"rejected_model_fields={len(state.constraint_set.rejected_model_constraints)}。"
                ),
                data={
                    "requirements": state.requirements.model_dump(mode="json"),
                    "constraint_set": state.constraint_set.model_dump(mode="json"),
                },
            )
        if name == "finish_decision":
            observed = {
                trace.tool
                for trace in state.traces
                if trace.status in {"success", "degraded", "unavailable"}
            }
            if state.candidate_rows and not state.assessments:
                return ToolResult(
                    tool=name, status="failed", error_code="EVIDENCE_CHECK_REQUIRED",
                    summary="已有候选但尚未执行字段级证据核验，不能结束。",
                )
            if (
                not state.candidate_rows
                and not state.kb_hits
                and state.open_research is None
                and not ({"text2sql", "evidence_check", "source_search", "web_extractor"} & observed)
            ):
                return ToolResult(
                    tool=name, status="failed", error_code="OBSERVATION_REQUIRED",
                    summary="尚无工具观察结果，不能结束。",
                )
            state.requirements.pending_questions = list(arguments.get("pending_questions", []))
            statuses = {item.status.value for items in state.assessments.values() for item in items}
            successful_sql = any(
                trace.tool == "text2sql" and trace.status in {"success", "degraded"} for trace in state.traces
            )
            if state.mode == ResearchMode.OPEN and state.open_research is not None:
                state.stop_reason = (
                    "Open Research 已完成字段级临时证据核验；结果保持 provisional，"
                    "未进入 Trusted 推荐集合。"
                )
            elif "unknown" in statuses or "conflict" in statuses:
                state.stop_reason = "字段级证据存在 unknown 或 conflict，已停止并拒绝标记为完全满足。"
            elif state.assessments:
                state.stop_reason = "候选字段四态核验完成，达到显式停止条件。"
            elif successful_sql and not state.candidate_rows:
                state.stop_reason = "只读结构化查询没有满足条件的候选，已安全停止。"
            elif state.kb_hits:
                state.stop_reason = "知识库证据检索完成，达到显式停止条件。"
            else:
                state.stop_reason = "证据链无法继续补足，已安全停止。"
            state.finished = True
            return ToolResult(tool=name, status="success", summary="已满足显式停止条件。", data={"finished": True})
        tool = self.tools.get(name)
        if tool is None:
            return ToolResult(
                tool=name, status="failed", error_code="TOOL_NOT_ALLOWED", summary="工具不在白名单中。",
            )
        if name == "source_search":
            source_limit = int(
                getattr(getattr(tool, "settings", None), "max_tool_invocations_per_task", 2)
            )
            prior_source_calls = sum(trace.tool == "source_search" for trace in state.traces)
            if prior_source_calls >= source_limit:
                return ToolResult(
                    tool=name,
                    status="failed",
                    error_code="SOURCE_SEARCH_TASK_BUDGET_EXHAUSTED",
                    summary="已达到单任务 Source Search 次数上限，未继续联网。",
                )
        if name == "web_extractor":
            if state.mode != ResearchMode.OPEN:
                return ToolResult(
                    tool=name,
                    status="failed",
                    error_code="OPEN_MODE_REQUIRED",
                    summary="Web Extractor 只能在显式 Open Mode 中运行。",
                )
            source_url = str(arguments.get("source_url", ""))
            source_candidate = state.source_candidates.get(source_url)
            if source_candidate is None:
                return ToolResult(
                    tool=name,
                    status="failed",
                    error_code="OBSERVED_SOURCE_CANDIDATE_REQUIRED",
                    summary="URL 不在本轮 Source Search 候选中，安全门已阻断。",
                )
            arguments["_source_candidate"] = source_candidate
            arguments["_user_id"] = state.user_id
            arguments["_session_id"] = state.session_id
            arguments["_thread_id"] = state.thread_id or state.session_id
            arguments["_request_id"] = uuid.uuid4().hex
        observed = [
            trace.tool for trace in state.traces if trace.status in {"success", "degraded", "unavailable"}
        ]
        if not state.requirements.summary:
            return ToolResult(
                tool=name, status="failed", error_code="REQUIREMENTS_REQUIRED",
                summary="必须先调用 set_requirements。",
            )
        hard_flow = state.requirements.task_type in {"filter", "comparison", "dynamic"}
        structured_fact_check = bool(
            state.requirements.task_type == "fact"
            and re.search(
                r"\d+(?:\.\d+)?\s*(?:w|hz|mm|kg|英寸).*还是.*\d+(?:\.\d+)?",
                state.query.lower(),
            )
        )
        sql_attempted = any(trace.tool == "text2sql" for trace in state.traces)
        sql_succeeded = "text2sql" in observed
        if name == "kb_search" and structured_fact_check and not sql_succeeded:
            return ToolResult(
                tool=name, status="failed", error_code="STRUCTURED_FACT_REQUIRED",
                summary="数值来源冲突问题必须先读取结构化字段，再检索原始来源。",
            )
        if name == "kb_search" and hard_flow and not sql_succeeded and not sql_attempted:
            return ToolResult(
                tool=name, status="failed", error_code="SQL_CANDIDATES_REQUIRED",
                summary="组合约束任务必须先由 Text2SQL 产生候选。",
            )
        if (
            name == "kb_search"
            and state.requirements.task_type == "dynamic"
            and {"price_cny", "stock_status"} & set(state.requirements.required_fields)
            and "web_search" not in observed
        ):
            return ToolResult(
                tool=name, status="failed", error_code="WEB_STATUS_REQUIRED",
                summary="动态价格或库存必须先观察 Web Search 的可用状态。",
            )
        if name == "evidence_check" and hard_flow:
            stable_spec_fields = {
                "region", "display_size_inch", "resolution", "refresh_rate_hz", "panel_type", "is_oled",
                "has_usb_c", "usb_c_video", "usb_c_power_delivery_w", "stand_adjustment", "width_mm",
                "weight_kg", "warranty",
            }
            needs_kb = bool(
                stable_spec_fields
                & {item.field for item in state.requirements.hard_constraints}
            )
            source_observed = (
                "kb_search" in observed
                if needs_kb
                else "kb_search" in observed or "web_search" in observed
            )
            if not source_observed or (sql_succeeded and not state.candidate_rows):
                return ToolResult(
                    tool=name, status="failed", error_code="DEPENDENT_EVIDENCE_REQUIRED",
                    summary="Evidence Check 必须依赖 SQL 候选和针对候选的 KB 证据。",
                )
        if name == "evidence_check" and not hard_flow:
            if structured_fact_check and (
                not sql_succeeded or not state.candidate_rows or "kb_search" not in observed
            ):
                return ToolResult(
                    tool=name, status="failed", error_code="DEPENDENT_EVIDENCE_REQUIRED",
                    summary="数值来源冲突核验必须依赖 SQL 候选和针对候选的 KB 证据。",
                )
            fact_fields = {
                "model_id", "model_name", "brand", "display_size_inch", "resolution", "refresh_rate_hz",
                "panel_type", "width_mm", "weight_kg",
            }
            if set(state.requirements.required_fields).issubset(fact_fields):
                return ToolResult(
                    tool=name, status="failed", error_code="KB_FACT_SUFFICIENT",
                    summary=(
                        "简单官方事实必须先由 KB Search 取证。"
                        if not state.kb_hits
                        else "简单官方事实已由 KB 命中，应直接结束而非增加工具调用。"
                    ),
                )
        if name == "text2sql":
            state_constraints = state.requirements.hard_constraints
            locator_constraints = [item for item in state_constraints if item.field in {"model_id", "model_name"}]
            if locator_constraints:
                # For named-model verification/comparison, SQL selects the named candidates;
                # Evidence Check, not SQL, decides whether each requested property is satisfied.
                filters = [item.model_dump(mode="json", exclude={"hard"}) for item in locator_constraints]
            else:
                filters = self._deterministic_filters(state.constraint_set)
            if state.product_scope is not None:
                filters.append({"field": "model_id", "operator": "in",
                                "value": list(state.product_scope.product_ids)})
            arguments["filters"] = filters
            arguments["_deterministic_filters"] = True
            arguments["_allow_full_pool"] = True
        elif name == "evidence_check":
            eligibility_constraints = [
                item for item in state.requirements.hard_constraints if item.field not in {"model_id", "model_name"}
            ]
            identity_fields = {"model_id", "model_name", "brand"}
            if eligibility_constraints:
                required_fields = [item.field for item in eligibility_constraints]
                required_fields.extend(
                    field
                    for field in state.requirements.required_fields
                    if field in {"price_cny", "stock_status", "observed_at"}
                )
            else:
                required_fields = [
                    field for field in state.requirements.required_fields if field not in identity_fields
                ]
            arguments["required_fields"] = list(dict.fromkeys(required_fields))
            arguments["constraints"] = [
                item.model_dump(mode="json") for item in eligibility_constraints
            ]
        elif name == "source_search":
            required = set(arguments.get("target_fields") or [])
            locally_bound = {item.field for item in state.kb_hits if item.field}
            arguments["_local_evidence_checked"] = bool(
                {"kb_search", "evidence_check"} & set(observed)
            )
            arguments["_local_evidence_sufficient"] = bool(
                required and required.issubset(locally_bound)
            )
        if name in {"kb_search", "evidence_check"} and hard_flow and state.candidate_pool_rows:
            arguments["model_ids"] = list(state.candidate_pool_rows)[:10]
        if name in {"kb_search", "evidence_check"} and state.product_scope is not None:
            proposed_ids = arguments.get("model_ids") or state.product_scope.product_ids
            arguments["model_ids"] = [
                item for item in proposed_ids if state.product_scope.permits(item)
            ]
            if not arguments["model_ids"]:
                return ToolResult(tool=name, status="failed", error_code="EMPTY_CANDIDATE_SCOPE",
                                  summary="工具请求没有范围内的可信配置，未扩大为全库检索。")
        try:
            result = await asyncio.wait_for(tool.invoke(arguments), timeout=self.limits.tool_timeout_seconds)
        except TimeoutError:
            result = ToolResult(
                tool=name, status="failed", error_code="TOOL_TIMEOUT", summary="工具超过单次执行时限。",
            )
        if state.product_scope is not None and name in {"text2sql", "kb_search", "evidence_check"}:
            result = result.model_copy(deep=True)
            scope = state.product_scope
            removed = 0
            for key in ("rows", "hits"):
                if key in result.data:
                    original = result.data[key]
                    result.data[key] = [row for row in original if scope.permits(str(row.get("model_id", "")))]
                    removed += len(original) - len(result.data[key])
            if "models" in result.data:
                original = result.data["models"]
                result.data["models"] = {key: value for key, value in original.items() if scope.permits(key)}
                removed += len(original) - len(result.data["models"])
            if removed:
                result.degraded = True
                result.summary = f"工具返回 {removed} 项范围外配置，已在观察结果进入状态前阻断。"
                result.data["scope_rejected_count"] = removed
        if name == "text2sql" and result.data.get("rows") is not None:
            arguments["_executed_sql"] = result.data.get("sql", "")
            state.candidate_rows = result.data["rows"]
            for row in state.candidate_rows:
                model_id = str(row.get("model_id", ""))
                self._remember_candidate(state, model_id, row, "text2sql")
        elif name == "kb_search":
            for hit in result.data.get("hits", []):
                if not all(hit.get(key) for key in ("source_id", "source_url", "model_id", "region")):
                    continue
                bindings = hit.get("evidence_bindings") or [
                    {
                        "evidence_id": None,
                        "source_id": hit["source_id"],
                        "source_url": hit["source_url"],
                        "field": None,
                    }
                ]
                for binding in bindings:
                    state.kb_hits.append(
                        EvidenceReference(
                            evidence_id=binding.get("evidence_id"),
                            source_id=binding.get("source_id") or hit["source_id"],
                            source_url=binding.get("source_url") or hit["source_url"],
                            source_type=hit.get("source_type") or "knowledge_base",
                            model_id=hit["model_id"],
                            region=hit["region"],
                            field=binding.get("field"),
                            location=hit.get("section"),
                            effective_time=hit.get("accessed_at"),
                        )
                    )
                self._remember_candidate(
                    state,
                    str(hit["model_id"]),
                    {"model_id": hit["model_id"], "region": hit["region"]},
                    "kb_search",
                )
        elif name == "evidence_check":
            for model_id, items in result.data.get("models", {}).items():
                state.assessments[model_id] = [FieldAssessment.model_validate(item) for item in items]
                state.verified_fields[model_id] = [item.field for item in state.assessments[model_id]]
                self._remember_candidate(state, str(model_id), {"model_id": model_id}, "evidence_check")
        elif name == "source_search":
            for group in ("usable_candidates", "navigation_candidates"):
                for candidate in result.data.get(group, []):
                    url = str(candidate.get("url", ""))
                    if url:
                        state.source_candidates[url] = dict(candidate)
        elif name == "web_extractor" and result.data.get("report"):
            try:
                state.open_research = OpenResearchReport.model_validate(result.data["report"])
            except ValidationError:
                return ToolResult(
                    tool=name,
                    status="failed",
                    error_code="INVALID_OPEN_RESEARCH_RESULT",
                    summary="Open Research 输出未通过 Schema 校验，未进入报告。",
                )
        if result.degraded or result.status in {"degraded", "unavailable"}:
            state.degraded_states.append(f"{name}: {result.summary}")
        return result

    @staticmethod
    def _infer_task_type(
        query: str, declared: str
    ) -> str:
        normalized = query.lower()
        if any(token in normalized for token in ("阳台", "浇水器", "与显示器无关")):
            return "unrelated"
        if any(token in normalized for token in ("当前价格", "现在", "库存", "多少钱")):
            return "dynamic"
        # A factual verification subtask cannot erase an explicit purchase
        # instruction. The model's declared task type has no authority here.
        if re.search(r"筛选|筛出|挑选|选购|(?<!不)(?<!不要)推荐", normalized):
            return "filter"
        # “60W 还是 65W” asks for one factual field; it is not a product
        # comparison and must retain Evidence Check's conflict/unknown state.
        factual_alternative = bool(
            re.search(r"\d+(?:\.\d+)?\s*(?:w|hz|mm|kg|英寸).*还是.*\d+(?:\.\d+)?", normalized)
        )
        if factual_alternative:
            return "fact"
        if ("还是" in normalized and not factual_alternative) or (
            any(token in normalized for token in ("比较", "中，哪", "中哪", "哪个", "哪台"))
            and any(token in normalized for token in (" 和 ", "与", "和", "中"))
        ):
            return "comparison"
        if any(token in normalized for token in ("比较", "对比", "差别", "不同")):
            return "comparison"
        if any(token in normalized for token in (
            "只查", "请查", "查询", "核验", "给证据", "怎么样", "有什么", "支持哪些", "是什么", "分别是多少",
        )):
            return "fact"
        if any(token in normalized for token in ("是否", "能否", "有没有")):
            if re.search(r"\d+(?:\.\d+)?\s*(?:w|hz|mm|kg|英寸|寸|元)", normalized):
                return "filter"
            if not any(token in normalized for token in ("推荐", "筛选", "找", "哪款", "满足")):
                return "fact"
        if any(token in normalized for token in ("找", "哪款", "预算", "至少", "不低于", "不超过", "满足", "以内")):
            return "filter"
        return declared

    @staticmethod
    def _augment_requirements(query: str, requirements: UserRequirements) -> UserRequirements:
        """Normalize explicit user wording into fields; this parses requirements, not final eligibility."""
        normalized = query.lower().replace(" ", "")
        requested_fields: set[str] = set()
        field_markers = {
            "brand": ("品牌",),
            "panel_type": ("面板", "ips", "va"),
            "display_size_inch": ("尺寸", "英寸", "寸"),
            "resolution": ("分辨率", "4k", "5k", "8k", "uhd", "qhd"),
            "refresh_rate_hz": ("刷新率", "hz"),
            "has_usb_c": ("usb-c", "usb c", "type-c", "type c"),
            "usb_c_video": ("usb-c视频", "usb-c传视频", "视频输入", "能传视频"),
            "usb_c_power_delivery_w": ("供电", "pd"),
            "stand_adjustment": ("支架", "升降", "旋转"),
            "width_mm": ("宽度",),
            "weight_kg": ("重量", "kg"),
            "warranty": ("保修",),
            "camera": ("摄像头",),
            "face_recognition": ("人脸识别",),
        }
        for field, markers in field_markers.items():
            if any(marker in normalized for marker in markers):
                requested_fields.add(field)
        # This is a legacy response adapter, not a second input parser. All
        # supported values come from the same provenance-aware normalizer.
        constraints = {
            item.field: item for item in requirements.hard_constraints
            if item.field in {"model_id", "model_name"}
        }
        if requirements.task_type in {"filter", "dynamic"}:
            normalized_set = ConstraintNormalizer().build(query, source_turn=1)
            parsed = PurchaseDecisionAgent._legacy_constraints(normalized_set)
        else:
            parsed = []
        requirements.hard_constraints = [*constraints.values(), *parsed]
        requirements.required_fields = list(
            dict.fromkeys([
                *requirements.required_fields, *sorted(requested_fields),
                *(item.field for item in requirements.hard_constraints),
            ])
        )
        return requirements

    @staticmethod
    def _gate_non_purchase_constraints(
        constraint_set: ConstraintSet,
        task_type: str,
    ) -> ConstraintSet:
        if task_type not in {"fact", "comparison", "unrelated"}:
            return constraint_set
        gated = constraint_set.model_copy(deep=True)
        for item in gated.constraints:
            if item.provenance.value == "current_input" and item.hard_or_soft.value == "hard":
                item.active = False
                item.note = "query_field_not_purchase_constraint"
        return gated

    def _preflight_clarification_reason(self, query: str) -> str | None:
        compact = re.sub(r"\s+", "", query.casefold())
        if any(
            marker in compact
            for marker in (
                "别太大", "别太小", "大一点", "小一点", "高一点", "低一点",
                "久一点", "轻一点", "便宜一点", "窄一点", "窄一些",
                "强一点", "强一些", "好一点", "好一些", "性能强一点",
                "性能强一些", "通话好一点", "通话好一些", "不能太高", "不要太重",
            )
        ) and not re.search(r"\d", compact):
            return "qualitative_threshold_missing"

        database_path = getattr(self.tools.get("text2sql"), "database_path", None)
        if not database_path:
            return None
        if re.search(r"(?:只推荐|只要|必须|要求).{0,12}(?:kvm|切换器)", compact, flags=re.I):
            return "unsupported_constraint"

        scope = self._catalog_scope(query)
        return (
            scope.resolution_reason
            if scope is not None and scope.clarification_required else None
        )

    def _catalog_scope(self, query: str):
        database_path = getattr(self.tools.get("text2sql"), "database_path", None)
        if not database_path:
            return None
        try:
            connection = sqlite3.connect(
                f"file:{getattr(database_path, 'as_posix', lambda: str(database_path))()}?mode=ro",
                uri=True, timeout=1.0,
            )
            connection.row_factory = sqlite3.Row
            try:
                rows = [dict(row) for row in connection.execute(
                    "SELECT model_id, model_name, brand, region FROM products"
                )]
            finally:
                connection.close()
            return resolve_catalog_identity(query, rows)
        except (OSError, sqlite3.Error):
            return None

    @staticmethod
    def _next_action(name: str, result: ToolResult, state: AgentState) -> str:
        if result.status == "failed":
            return "根据错误码选择受控降级或安全停止。"
        if name == "set_requirements":
            return "按问题类型选择 KB 或只读 SQL。"
        if name == "text2sql":
            return "用返回的候选型号核验官方资料与缺失字段。"
        if name == "kb_search":
            return "根据命中片段执行字段级 Evidence Check 或补查缺失项。"
        if name == "evidence_check":
            return "根据四态结果补查 unknown/conflict，或明确结束/拒答。"
        if name == "web_search":
            return "Web 不可用，回到 KB + SQL 稳定链路。"
        if name == "source_search":
            if state.mode == ResearchMode.OPEN:
                return "选择已验证的官方 Source Candidate，调用 Web Extractor 获取正文；摘要仍不能成为证据。"
            return "只把 URL 元数据保留为来源候选；不得转成 Evidence 或 Checker 输入。"
        if name == "web_extractor":
            return "根据临时证据四态生成 Open Research 报告；不得加入 Trusted 推荐集合。"
        return "停止并生成经过 Schema 校验的报告。"

    async def run(
        self,
        query: str,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        use_long_term_memory: bool = False,
        mode: ResearchMode = ResearchMode.TRUSTED,
        thread_id: str | None = None,
        event_callback: EventCallback | None = None,
        constraint_resolution: ConstraintResolution | None = None,
    ) -> DecisionReport:
        started = time.perf_counter()
        session_id = session_id or str(uuid.uuid4())
        state, previous_requirements, previous_constraints = self._start_state(
            query, session_id, user_id, mode, thread_id
        )
        state.constraint_resolution = constraint_resolution
        state.product_scope = self._catalog_scope(query)
        preflight_reason = (
            self._preflight_clarification_reason(query)
            if constraint_resolution is None else None
        )
        if state.product_scope is not None and state.product_scope.clarification_required:
            preflight_reason = state.product_scope.resolution_reason
        if preflight_reason is not None:
            return DecisionReport(
                request_summary=query[:200],
                task_type="filter",
                clarification_state="pending",
                pending_questions=[
                    "请明确具体商品配置、地区或可执行的数值阈值。"
                ],
                abstained=True,
                stop_reason="输入存在未消解歧义；未调用模型、检索工具或 Checker。",
                tool_call_count=0,
                usage={
                    "call_count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "estimated_cost_cny": 0.0,
                    "result_status": "needs_clarification",
                    "clarification_reason": preflight_reason,
                },
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        preferences = (
            self.preference_memory.recall(user_id, requested=use_long_term_memory) if user_id else {}
        )
        initial_type = self._infer_task_type(query, "filter")
        initial_constraints = (
            constraint_resolution.constraint_set.model_copy(deep=True)
            if constraint_resolution is not None
            else self.constraint_normalizer.build(
                query, source_turn=state.turn_number,
                previous=previous_constraints, preferences=preferences,
            )
        )
        state.constraint_set = self._gate_non_purchase_constraints(initial_constraints, initial_type)
        coverage = audit_requirement_coverage(
            query, state.constraint_set, self.requirement_pack,
            purchase=initial_type in {"filter", "dynamic"},
        )
        if not coverage.complete:
            return await self._incomplete_requirements_report(state, coverage, started, event_callback)
        previous_context = {
            "requirements": previous_requirements.model_dump(mode="json") if previous_requirements else None,
            "previous_candidates": [row.get("model_id") for row in state.candidate_rows[:10]],
            "confirmed_preferences": preferences,
        }
        system_prompt = SYSTEM_PROMPT
        if "source_search" in self.tools:
            system_prompt += (
                "11. source_search 只用于用户明确要求、目录外型号、动态来源发现，或本地取证后仍缺字段；"
                "返回项只是 Source Candidate，不能当成规格事实、Evidence 或 Checker 输入。\n"
            )
        if "web_extractor" in self.tools and state.mode == ResearchMode.OPEN:
            system_prompt += (
                "12. 当前为 Open Mode：目录外型号必须先 source_search，再对本轮观察到的候选调用 web_extractor；"
                "只有正文片段可形成请求级 open evidence。Open 商品永远不能标为 Trusted eligible。\n"
            )
        if not self.enable_constraint_checker:
            system_prompt = system_prompt.replace(
                "10. finish_decision 后系统仍会对完整工具候选池强制运行 Constraint Checker；你不能跳过、覆盖或修改其结果。",
                "10. 本实验关闭最终 Constraint Checker；必须如实保留 Evidence Check 的四态结果。",
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": "可用的脱敏会话上下文：" + json.dumps(previous_context, ensure_ascii=False)},
            {"role": "user", "content": query},
        ]
        ledger = getattr(self.provider, "ledger", None)
        ledger_start = len(ledger.snapshot()) if ledger is not None else 0
        correction_sent = False
        for step in range(1, self.limits.max_steps + 1):
            usage = self._usage(self.provider, ledger_start)
            if float(usage["estimated_cost_cny"]) >= self.limits.max_task_cost_cny:
                state.stop_reason = "达到单任务 API 成本预算，安全停止。"
                state.degraded_states.append("agent: cost budget reached")
                break
            try:
                response = await self.provider.chat(
                    messages,
                    tools=self._tool_schemas(state.mode),
                    tool_choice="auto",
                    temperature=0.0,
                    max_tokens=800,
                )
            except Exception:
                state.stop_reason = "模型调用失败，已在不暴露底层敏感错误的情况下停止。"
                state.degraded_states.append("agent: qwen-plus unavailable")
                break
            assistant_message = response.data
            messages.append(assistant_message)
            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                if not correction_sent and step < self.limits.max_steps:
                    messages.append({"role": "system", "content": "必须通过白名单工具继续，并用 finish_decision 明确停止。"})
                    correction_sent = True
                    continue
                state.stop_reason = "模型未选择工具，Agent 安全停止。"
                break
            for call in tool_calls:
                if state.tool_call_count >= self.limits.max_tool_calls:
                    state.stop_reason = "达到工具调用总预算，安全停止。"
                    state.finished = True
                    break
                function = call.get("function") or {}
                name = str(function.get("name", ""))
                raw_arguments = function.get("arguments", "{}")
                tool_started = time.perf_counter()
                try:
                    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError
                except (ValueError, TypeError, json.JSONDecodeError):
                    arguments = {}
                    result = ToolResult(
                        tool=name or "unknown", status="failed", error_code="INVALID_TOOL_ARGUMENTS",
                        summary="工具参数不是有效 JSON 对象。",
                    )
                else:
                    if name == "source_search":
                        raw_requested_count = arguments.get("max_results", 10)
                        started_event = {
                            "type": "source_search_started",
                            "provider": "zhipu",
                            "status": "started",
                            "search_executed": False,
                            "requested_count": (
                                raw_requested_count
                                if isinstance(raw_requested_count, int)
                                and not isinstance(raw_requested_count, bool)
                                else 0
                            ),
                        }
                        agent_monitor.record_source_search_event(started_event)
                        await self._emit(event_callback, started_event)
                    elif name == "web_extractor":
                        started_event = {
                            "type": "web_extraction_started",
                            "status": "started",
                            "mode": "open",
                            "target_field_count": len(arguments.get("target_fields", [])),
                        }
                        agent_monitor.record_open_research_event(started_event)
                        await self._emit(event_callback, started_event)
                    result = await self._invoke_tool(
                        name,
                        arguments,
                        state,
                        previous_requirements,
                        previous_constraints,
                        preferences,
                    )
                if name == "source_search":
                    source_data = result.data
                    completed_event = {
                        "type": "source_search_completed",
                        "provider": str(source_data.get("provider", "zhipu"))[:32],
                        "status": str(source_data.get("status", result.status))[:40],
                        "search_executed": bool(source_data.get("search_executed", False)),
                        "requested_count": int(source_data.get("requested_count", 0) or 0),
                        "raw_result_count": int(source_data.get("raw_result_count", 0) or 0),
                        "scanned_result_count": int(source_data.get("scanned_result_count", 0) or 0),
                        "usable_result_count": int(source_data.get("usable_result_count", 0) or 0),
                        "navigation_result_count": len(source_data.get("navigation_candidates", [])),
                        "cache_status": str(source_data.get("cache_status", ""))[:20],
                        "degraded": bool(result.degraded),
                        "estimated_cost_cny": float(
                            source_data.get("estimated_cost_cny", 0.0) or 0.0
                        ),
                        "error_category": result.error_code,
                    }
                    agent_monitor.record_source_search_event(completed_event)
                    await self._emit(event_callback, completed_event)
                elif name == "web_extractor":
                    open_report = result.data.get("report", {})
                    extraction = result.data.get("extraction", {})
                    completed_event = {
                        "type": "web_extraction_completed",
                        "status": str(extraction.get("status", result.status))[:40],
                        "mode": "open",
                        "http_status": extraction.get("http_status"),
                        "redirect_count": len(extraction.get("redirect_chain", [])),
                        "snippet_count": len(extraction.get("snippets", [])),
                        "temporary_evidence_count": int(
                            open_report.get("temporary_evidence_count", 0) or 0
                        ),
                        "unknown_field_count": len(open_report.get("unknown_fields", [])),
                        "conflict_field_count": len(open_report.get("conflict_fields", [])),
                        "trusted_eligible": False,
                        "degraded": bool(result.degraded),
                        "error_category": result.error_code,
                    }
                    agent_monitor.record_open_research_event(completed_event)
                    await self._emit(event_callback, completed_event)
                state.tool_call_count += 1
                parent_step = arguments.get("parent_step") if isinstance(arguments.get("parent_step"), int) else None
                if name == "kb_search":
                    actual_parent = next(
                        (item.step for item in reversed(state.traces) if item.tool == "text2sql"), None
                    )
                    parent_step = actual_parent if actual_parent is not None else parent_step
                elif name == "evidence_check":
                    actual_parent = next(
                        (item.step for item in reversed(state.traces) if item.tool == "kb_search"), None
                    )
                    parent_step = actual_parent if actual_parent is not None else parent_step
                trace = ToolTrace(
                    step=step,
                    parent_step=parent_step,
                    task_summary=state.requirements.summary or query[:160],
                    tool=name or "unknown",
                    arguments_summary=self._safe_arguments(name, arguments),
                    status=result.status,
                    result_summary=result.summary,
                    next_action=self._next_action(name, result, state),
                    stop_or_degrade_reason=(result.summary if result.status in {"failed", "degraded", "unavailable"} else None),
                    duration_ms=round((time.perf_counter() - tool_started) * 1000, 3),
                )
                state.traces.append(trace)
                await self._emit(
                    event_callback,
                    {"type": "tool_observation", "trace": trace.model_dump(mode="json")},
                )
                compact = result.compact()
                encoded = json.dumps(compact, ensure_ascii=False, default=str)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", f"call-{state.tool_call_count}"),
                        "name": name,
                        "content": encoded[:18_000],
                    }
                )
                if result.error_code == "UNSUPPORTED_FILTERS":
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "这些字段不在结构化 Schema 中，不得再次尝试 Text2SQL 或全表扫描。"
                                "下一步用 kb_search（model_ids 可为空）检索字段，再用 evidence_check 判断 unknown。"
                            ),
                        }
                    )
                if name == "evidence_check" and result.status == "success":
                    messages.append(
                        {
                            "role": "system",
                            "content": "字段四态核验已完成。若无明确的未解决查询目标，下一步必须调用 finish_decision。",
                        }
                    )
                if state.finished:
                    break
            if state.finished:
                break
        if not state.stop_reason:
            state.stop_reason = "达到最大 ReAct 步骤数，安全停止。"
            state.degraded_states.append("agent: maximum step limit reached")
        coverage = audit_requirement_coverage(
            state.query, state.constraint_set, self.requirement_pack,
            purchase=state.requirements.task_type in {"filter", "dynamic"},
        )
        if not coverage.complete:
            return await self._incomplete_requirements_report(
                state, coverage, started, event_callback, self._usage(self.provider, ledger_start)
            )
        # Evidence sufficiency is a runtime invariant. If the model exhausted its
        # bounded loop after obtaining KB candidates but skipped Evidence Check,
        # execute one deterministic, whitelisted fallback instead of fabricating
        # a conclusion. This does not call the LLM and remains fully auditable.
        if (
            state.requirements.task_type in {"filter", "comparison", "dynamic"}
            and state.candidate_pool_rows
            and state.kb_hits
            and not state.assessments
            and state.tool_call_count < self.limits.max_tool_calls
        ):
            fallback_arguments = {
                "model_ids": list(state.candidate_pool_rows)[:10],
                "required_fields": list(state.requirements.required_fields),
                "constraints": [
                    item.model_dump(mode="json")
                    for item in state.requirements.hard_constraints
                    if item.field not in {"model_id", "model_name"}
                ],
                "reason": "有界循环结束前未完成字段证据核验，执行确定性白名单回退。",
            }
            fallback_started = time.perf_counter()
            fallback = await self._invoke_tool(
                "evidence_check",
                fallback_arguments,
                state,
                previous_requirements,
                previous_constraints,
                preferences,
            )
            state.tool_call_count += 1
            parent_step = next(
                (item.step for item in reversed(state.traces) if item.tool == "kb_search"),
                None,
            )
            fallback_trace = ToolTrace(
                step=self.limits.max_steps + 1,
                parent_step=parent_step,
                task_summary=state.requirements.summary or query[:160],
                tool="evidence_check",
                arguments_summary=self._safe_arguments("evidence_check", fallback_arguments),
                status=fallback.status,
                result_summary=fallback.summary,
                next_action="将字段四态结果交给确定性复核器；不再请求模型规划。",
                stop_or_degrade_reason=(
                    "模型在有界循环内未完成 Evidence Check；运行时执行白名单回退。"
                ),
                duration_ms=round((time.perf_counter() - fallback_started) * 1000, 3),
            )
            state.traces.append(fallback_trace)
            state.degraded_states.append(
                "agent: bounded loop omitted evidence_check; deterministic fallback executed"
            )
            await self._emit(
                event_callback,
                {"type": "tool_observation", "trace": fallback_trace.model_dump(mode="json")},
            )
        pool_model_ids = [
            item for item in state.candidate_pool_rows
            if state.product_scope is None or state.product_scope.permits(item)
        ]
        if self.enable_constraint_checker:
            assert self.constraint_verifier is not None
            await self._emit(
                event_callback,
                {
                    "type": "constraint_check_started",
                    "verifier_version": VERIFIER_VERSION,
                    "candidate_pool_count": len(pool_model_ids),
                },
            )
            constraint_started = time.perf_counter()
            try:
                state.constraint_verification = self.constraint_verifier.verify_candidates(
                    state.constraint_set, pool_model_ids
                )
            except Exception:
                state.constraint_verification = self.constraint_verifier.fail_closed(
                    state.constraint_set,
                    pool_model_ids,
                    "Constraint Checker 异常，已 fail closed；敏感错误细节未记录。",
                )
            state.constraint_check_latency_ms = round(
                (time.perf_counter() - constraint_started) * 1000, 3
            )
            await self._emit(
                event_callback,
                {
                    "type": "constraint_check_completed",
                    "verification": state.constraint_verification.model_dump(mode="json"),
                    "latency_ms": state.constraint_check_latency_ms,
                },
            )
            pre_rank_usage = self._usage(self.provider, ledger_start)
            if float(pre_rank_usage["estimated_cost_cny"]) >= self.limits.max_task_cost_cny:
                order = list(state.constraint_verification.eligible_model_ids)
                explanations: dict[str, str] = {}
                ranking_degraded = False
            else:
                order, explanations, ranking_degraded = await rank_compliant_candidates(
                    self.provider,
                    state.constraint_verification,
                    state.constraint_set.active(),
                )
            state.ranked_eligible_model_ids = order
            state.candidate_explanations = explanations
            if ranking_degraded:
                state.degraded_states.append("soft ranking: model unavailable; preserved verifier order")
            if state.requirements.task_type in {"filter", "comparison", "dynamic"}:
                if state.constraint_verification.degraded:
                    state.stop_reason = "Constraint Checker 降级并 fail closed，本次不输出合规推荐。"
                elif state.constraint_verification.eligible_model_ids:
                    state.stop_reason = "Constraint Checker 已独立复核完整工具候选池，最终推荐仅来自合规集合。"
                else:
                    state.stop_reason = "Constraint Checker 未找到所有硬约束均通过的候选，已安全停止。"
        else:
            state.constraint_verification = None
            state.constraint_check_latency_ms = 0.0
            state.ranked_eligible_model_ids = []
            state.candidate_explanations = {}
        self.session_memory.save(state)
        usage = self._usage(self.provider, ledger_start)
        usage["requirement_coverage"] = coverage.public()
        if state.product_scope is not None:
            # V1 responses keep their legacy identity envelope. Scope is enforced
            # internally and exposed as bounded audit metadata, not a partial V2
            # report identity that could imply a data/index migration.
            usage["candidate_scope"] = {
                "product_ids": state.product_scope.product_ids,
                "scope_type": state.product_scope.scope_type.value,
                "fingerprint": state.product_scope.fingerprint,
            }
        report = build_report(state, latency_ms=(time.perf_counter() - started) * 1000, usage=usage)
        agent_monitor.record(
            {
                "session_id": session_id,
                "latency_ms": report.latency_ms,
                "tool_call_count": report.tool_call_count,
                "tools": report.tools_used,
                "statuses": [trace.status for trace in report.trace],
                "stop_reason": report.stop_reason,
                "abstained": report.abstained,
                "estimated_cost_cny": usage.get("estimated_cost_cny", 0.0),
                "constraint_checker_version": (
                    state.constraint_verification.verifier_version
                    if state.constraint_verification else None
                ),
                "constraint_statuses": [
                    item.overall_status.value
                    for item in (
                        state.constraint_verification.candidates
                        if state.constraint_verification else []
                    )
                ],
                "constraint_degraded": (
                    state.constraint_verification.degraded
                    if state.constraint_verification else False
                ),
                "constraint_check_latency_ms": state.constraint_check_latency_ms,
                "constraint_candidates": [
                    {
                        "model_id": item.model_id,
                        "status": item.overall_status.value,
                        "eligible": item.eligible,
                        "violated_fields": item.violated_fields,
                        "unknown_fields": item.unknown_fields,
                        "conflict_fields": item.conflict_fields,
                        "constraint_results": [
                            {
                                "field": result.constraint.field,
                                "status": result.status.value,
                                "actual_value": result.actual_value,
                                "required_value": result.constraint.normalized_value,
                                "evidence_id": result.evidence_id,
                                "source_id": result.source_id,
                            }
                            for result in item.constraint_results
                        ],
                    }
                    for item in (
                        state.constraint_verification.candidates
                        if state.constraint_verification else []
                    )
                ],
            }
        )
        await self._emit(event_callback, {"type": "report", "report": report.model_dump(mode="json")})
        return report
