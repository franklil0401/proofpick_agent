"""Run the frozen four-group Stage 6 experiment with sanitized checkpoints."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from smartbuy.agent import PurchaseDecisionAgent
from smartbuy.config import load_bailian_settings
from smartbuy.constraints import CandidateConstraintVerifier, ConstraintNormalizer, ConstraintStrength
from smartbuy.db.build_database import DEFAULT_OUTPUT
from smartbuy.memory import LongTermPreferenceStore, SessionMemoryStore
from smartbuy.observability import EvaluationLedger, EvaluationLedgerRecord, UsageLedger
from smartbuy.providers import BailianProvider
from smartbuy.tools import EvidenceCheckTool, KBSearchTool, Text2SQLTool, WebSearchTool

from .stage6_scoring import score_group, score_stability


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = Path(__file__).with_name("stage6_natural_cases.jsonl")
CONFIG_PATH = Path(__file__).with_name("stage6_config.json")
EVIDENCE_PATH = PROJECT_ROOT / "smartbuy/data/processed/evidence_records.jsonl"
SOURCES_PATH = PROJECT_ROOT / "smartbuy/data/processed/source_records.jsonl"
RESULTS_PATH = PROJECT_ROOT / "smartbuy/data/processed/stage6_four_group_results.json"
SMOKE_PATH = PROJECT_ROOT / "smartbuy/data/processed/stage6_smoke_results.json"
LEDGER_PATH = PROJECT_ROOT / "smartbuy/data/processed/stage6_evaluation_ledger.jsonl"
CHECKPOINT_PATH = Path("C:/ai/smartbuy-stage6/four_group_checkpoint.jsonl")
AS_OF = datetime(2026, 8, 27, 0, 0, tzinfo=UTC)

GROUPS = ("direct_llm", "fixed_rag", "agentic_rag", "agentic_rag_checker")


class BaselineClaim(BaseModel):
    model_id: str
    field: str
    status: str
    value: Any = None
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class BaselineAnswer(BaseModel):
    model_ids: list[str] = Field(default_factory=list)
    abstained: bool
    claims: list[BaselineClaim] = Field(default_factory=list)
    unsupported_constraints: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    conflict_fields: list[str] = Field(default_factory=list)


ANSWER_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_evaluation_answer",
        "description": "提交结构化评测答案；这不是外部数据工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "model_ids": {"type": "array", "items": {"type": "string"}},
                "abstained": {"type": "boolean"},
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "model_id": {"type": "string"},
                            "field": {"type": "string"},
                            "status": {"type": "string", "enum": ["matched", "not_matched", "unknown", "conflict"]},
                            "value": {},
                            "evidence_ids": {"type": "array", "items": {"type": "string"}},
                            "source_ids": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["model_id", "field", "status", "evidence_ids", "source_ids"],
                        "additionalProperties": False,
                    },
                },
                "unsupported_constraints": {"type": "array", "items": {"type": "string"}},
                "unknown_fields": {"type": "array", "items": {"type": "string"}},
                "conflict_fields": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "model_ids", "abstained", "claims", "unsupported_constraints",
                "unknown_fields", "conflict_fields"
            ],
            "additionalProperties": False,
        },
    },
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_freeze() -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cases = load_jsonl(CASES_PATH)
    ids = [item["case_id"] for item in cases]
    splits = {name: sum(item["split"] == name for item in cases) for name in ("regression", "holdout")}
    errors: list[str] = []
    if len(cases) != 40:
        errors.append(f"natural case count is {len(cases)}, expected 40")
    if len(set(ids)) != len(ids):
        errors.append("duplicate natural case_id")
    if splits != {"regression": 16, "holdout": 24}:
        errors.append(f"unexpected split counts: {splits}")
    if _sha256(CASES_PATH) != config["dataset"]["natural_sha256"]:
        errors.append("natural suite SHA-256 does not match sealed config")
    for item in cases:
        missing = {
            "case_id", "split", "question", "category", "task_type", "expected_model_ids",
            "gold_evidence_ids", "required_fields", "required_tools", "should_abstain",
            "multihop", "expected_behavior",
        } - set(item)
        if missing:
            errors.append(f"{item.get('case_id', '?')} missing {sorted(missing)}")
    evidence_ids = {item["evidence_id"] for item in load_jsonl(EVIDENCE_PATH)}
    unknown_gold = sorted(
        {
            evidence_id
            for item in cases
            for evidence_id in item["gold_evidence_ids"]
            if evidence_id not in evidence_ids
        }
    )
    if unknown_gold:
        errors.append(f"unknown gold evidence ids: {unknown_gold}")
    if config["config_hash"] == "PENDING_SEAL":
        errors.append("config is not sealed")
    return {
        "passed": not errors,
        "errors": errors,
        "natural_case_count": len(cases),
        "split_counts": splits,
        "natural_sha256": _sha256(CASES_PATH),
        "config_hash": config["config_hash"],
    }


def _parse_baseline(message: dict[str, Any]) -> BaselineAnswer:
    calls = message.get("tool_calls") or []
    if len(calls) != 1:
        raise ValueError("baseline response did not contain exactly one schema submission")
    function = calls[0].get("function") or {}
    if function.get("name") != "submit_evaluation_answer":
        raise ValueError("baseline response selected an unexpected function")
    raw = function.get("arguments", "{}")
    payload = json.loads(raw) if isinstance(raw, str) else raw
    return BaselineAnswer.model_validate(payload)


def _usage_delta(ledger: UsageLedger, start: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records = ledger.snapshot()[start:]
    return (
        {
            "call_count": len(records),
            "input_tokens": sum(int(item["input_tokens"]) for item in records),
            "output_tokens": sum(int(item["output_tokens"]) for item in records),
            "estimated_cost_cny": round(sum(float(item["estimated_cost_cny"]) for item in records), 8),
        },
        records,
    )


def _evidence_maps() -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]]]:
    sources = {item["source_id"]: item for item in load_jsonl(SOURCES_PATH)}
    by_id: dict[str, dict[str, Any]] = {}
    by_model_field: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in load_jsonl(EVIDENCE_PATH):
        row = {**item, "region": sources.get(item["source_id"], {}).get("region")}
        by_id[item["evidence_id"]] = row
        by_model_field.setdefault((item["model_id"], item["normalized_field"]), []).append(row)
    return by_id, by_model_field


def _baseline_prediction(
    *,
    answer: BaselineAnswer,
    case: dict[str, Any],
    group: str,
    repetition: int,
    latency_ms: float,
    usage: dict[str, Any],
    usage_records: list[dict[str, Any]],
    retrieved_model_ids: list[str] | None,
    degraded_states: list[str] | None = None,
) -> dict[str, Any]:
    claims = [item.model_dump(mode="json") for item in answer.claims]
    return {
        "case_id": case["case_id"],
        "experiment_group": group,
        "repetition": repetition,
        "recommended_model_ids": list(dict.fromkeys(answer.model_ids)),
        "observed_model_ids": list(dict.fromkeys(answer.model_ids)),
        "abstained": answer.abstained,
        "claims": claims,
        "evidence_ids": list(dict.fromkeys(eid for item in claims for eid in item["evidence_ids"])),
        "source_ids": list(dict.fromkeys(sid for item in claims for sid in item["source_ids"])),
        "citation_pairs": [
            {"model_id": item["model_id"], "evidence_id": eid, "region": None}
            for item in claims for eid in item["evidence_ids"]
        ],
        "unsupported_constraints": answer.unsupported_constraints,
        "unknown_or_conflict_reported": bool(answer.unknown_fields or answer.conflict_fields),
        "retrieved_model_ids": retrieved_model_ids,
        "tools_used": [] if group == "direct_llm" else ["kb_search", "reranker"],
        "tool_call_count": 0 if group == "direct_llm" else 2,
        "multihop_pass": False,
        "tool_order_pass": False,
        "blocked_unauthorized_or_out_of_order": [],
        "degraded_states": degraded_states or [],
        "degradation_visible": bool(degraded_states),
        "limit_reached": False,
        "schema_pass": True,
        "latency_ms": round(latency_ms, 3),
        "usage": usage,
        "usage_records": usage_records,
        "error_category": None,
    }


async def _run_direct(
    provider: BailianProvider,
    case: dict[str, Any],
    repetition: int,
) -> dict[str, Any]:
    ledger_start = len(provider.ledger.snapshot())
    started = time.perf_counter()
    response = await provider.chat(
        [
            {
                "role": "system",
                "content": (
                    "你是四组公平评测中的 Direct LLM。只能依赖模型自身知识直接回答，"
                    "不得使用知识库、SQLite、Reranker、Memory 或 Constraint Checker。"
                    "不确定时必须 abstained=true；不要虚构来源或 evidence_id。"
                ),
            },
            {"role": "user", "content": case["question"]},
        ],
        tools=[ANSWER_TOOL],
        tool_choice={"type": "function", "function": {"name": "submit_evaluation_answer"}},
        temperature=0.0,
        max_tokens=800,
    )
    answer = _parse_baseline(response.data)
    usage, records = _usage_delta(provider.ledger, ledger_start)
    return _baseline_prediction(
        answer=answer,
        case=case,
        group="direct_llm",
        repetition=repetition,
        latency_ms=(time.perf_counter() - started) * 1000,
        usage=usage,
        usage_records=records,
        retrieved_model_ids=None,
    )


async def _run_fixed_rag(
    provider: BailianProvider,
    settings: Any,
    case: dict[str, Any],
    repetition: int,
    evidence_by_model_field: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    ledger_start = len(provider.ledger.snapshot())
    started = time.perf_counter()
    kb = KBSearchTool(settings, provider, vector_top_k=30, result_top_k=5)
    result = await kb.invoke(
        {
            "query": case["question"],
            "model_ids": [],
            "required_fields": case["required_fields"],
            "reason": "Fixed RAG 固定 Top-5 检索。",
        }
    )
    hits = result.data.get("hits", [])[:5]
    context_rows = []
    for hit in hits:
        bindings = hit.get("evidence_bindings") or [
            {
                "evidence_id": item["evidence_id"],
                "source_id": item["source_id"],
                "field": item["normalized_field"],
            }
            for field in case["required_fields"]
            for item in evidence_by_model_field.get((str(hit.get("model_id")), field), [])
        ]
        context_rows.append(
            {
                "rank": hit.get("rank"),
                "model_id": hit.get("model_id"),
                "region": hit.get("region"),
                "source_id": hit.get("source_id"),
                "source_url": hit.get("source_url"),
                "evidence_bindings": bindings,
                "snippet": hit.get("snippet", "")[:600],
            }
        )
    response = await provider.chat(
        [
            {
                "role": "system",
                "content": (
                    "你是四组公平评测中的 Fixed RAG。只能使用下面固定向量召回并经 Reranker"
                    "得到的 Top-5 证据；不得调用 SQL、ReAct、Memory 或 Constraint Checker。"
                    "只有 evidence_bindings 中出现的 ID 才能引用；证据不足时必须拒答。"
                ),
            },
            {"role": "system", "content": json.dumps(context_rows, ensure_ascii=False)},
            {"role": "user", "content": case["question"]},
        ],
        tools=[ANSWER_TOOL],
        tool_choice={"type": "function", "function": {"name": "submit_evaluation_answer"}},
        temperature=0.0,
        max_tokens=800,
    )
    answer = _parse_baseline(response.data)
    usage, records = _usage_delta(provider.ledger, ledger_start)
    return _baseline_prediction(
        answer=answer,
        case=case,
        group="fixed_rag",
        repetition=repetition,
        latency_ms=(time.perf_counter() - started) * 1000,
        usage=usage,
        usage_records=records,
        retrieved_model_ids=[str(hit.get("model_id")) for hit in hits if hit.get("model_id")],
        degraded_states=["reranker_degraded=true"] if result.degraded else [],
    )


def _multihop(report: Any) -> tuple[bool, bool]:
    traces = [
        item for item in report.trace
        if item.tool in {"text2sql", "kb_search", "evidence_check"}
        and item.status in {"success", "degraded"}
    ]
    tools = [item.tool for item in traces]
    ordered = (
        all(name in tools for name in ("text2sql", "kb_search", "evidence_check"))
        and tools.index("text2sql") < tools.index("kb_search") < tools.index("evidence_check")
    )
    dependent = ordered and all(
        item.parent_step is not None for item in traces if item.tool in {"kb_search", "evidence_check"}
    )
    return dependent, ordered


def _agent_prediction(
    report: Any,
    case: dict[str, Any],
    group: str,
    repetition: int,
    usage_records: list[dict[str, Any]],
) -> dict[str, Any]:
    multihop, order = _multihop(report)
    claims = []
    citation_pairs = []
    for candidate in report.candidates:
        for field in candidate.fields:
            evidence_ids = [item.evidence_id for item in field.evidence if item.evidence_id]
            source_ids = [item.source_id for item in field.evidence]
            claims.append(
                {
                    "model_id": candidate.model_id,
                    "field": field.field,
                    "status": field.status.value,
                    "value": field.actual_value,
                    "evidence_ids": evidence_ids,
                    "source_ids": source_ids,
                }
            )
            citation_pairs.extend(
                {"model_id": candidate.model_id, "evidence_id": item.evidence_id, "region": candidate.region}
                for item in field.evidence if item.evidence_id
            )
    for evidence in report.evidence:
        if evidence.evidence_id and not any(
            item["model_id"] == evidence.model_id
            and evidence.evidence_id in item["evidence_ids"]
            for item in claims
        ):
            claims.append(
                {
                    "model_id": evidence.model_id,
                    "field": evidence.field or "retrieved_fact",
                    "status": "matched",
                    "value": evidence.value,
                    "evidence_ids": [evidence.evidence_id],
                    "source_ids": [evidence.source_id],
                }
            )
            citation_pairs.append(
                {"model_id": evidence.model_id, "evidence_id": evidence.evidence_id, "region": evidence.region}
            )
    checker = report.constraint_verification
    checker_fingerprint = checker.semantic_fingerprint if checker else None
    retrieved = list(dict.fromkeys(item.model_id for item in report.evidence))[:5]
    unknown_or_conflict = bool(report.unresolved_facts) or any(
        item.overall_status.value in {"unknown", "conflict"} for item in report.candidates
    )
    unsupported = list(
        dict.fromkeys(
            item.field
            for item in report.constraint_set.active()
            if not item.supported or item.ambiguous
        )
    )
    return {
        "case_id": case["case_id"],
        "experiment_group": group,
        "repetition": repetition,
        "recommended_model_ids": report.recommended_model_ids,
        "observed_model_ids": list(
            dict.fromkeys(
                [
                    *report.recommended_model_ids,
                    *(item.model_id for item in report.candidates),
                    *(item.model_id for item in report.evidence),
                ]
            )
        ),
        "abstained": report.abstained,
        "claims": claims,
        "evidence_ids": list(dict.fromkeys(eid for item in claims for eid in item["evidence_ids"])),
        "source_ids": list(dict.fromkeys(sid for item in claims for sid in item["source_ids"])),
        "citation_pairs": citation_pairs,
        "unsupported_constraints": unsupported,
        "unknown_or_conflict_reported": unknown_or_conflict,
        "retrieved_model_ids": retrieved,
        "tools_used": report.tools_used,
        "tool_call_count": report.tool_call_count,
        "multihop_pass": multihop,
        "tool_order_pass": order,
        "blocked_unauthorized_or_out_of_order": [
            {"tool": item.tool, "blocked": True}
            for item in report.trace
            if item.status == "failed"
        ],
        "degraded_states": report.degraded_states,
        "degradation_visible": bool(report.degraded_states),
        "limit_reached": any(token in report.stop_reason for token in ("最大", "预算", "上限")),
        "schema_pass": report.report_version in {"smartbuy-decision-v2", "smartbuy-decision-v3"},
        "latency_ms": report.latency_ms,
        "usage": report.usage,
        "usage_records": usage_records,
        "error_category": None,
        "checker_fingerprint": checker_fingerprint,
        "public_trace": [item.model_dump(mode="json") for item in report.trace],
    }


async def _run_agent(
    provider: BailianProvider,
    settings: Any,
    case: dict[str, Any],
    repetition: int,
    *,
    checker_enabled: bool,
) -> dict[str, Any]:
    group = "agentic_rag_checker" if checker_enabled else "agentic_rag"
    ledger_start = len(provider.ledger.snapshot())
    tools = {
        "text2sql": Text2SQLTool(DEFAULT_OUTPUT),
        "kb_search": KBSearchTool(settings, provider),
        "evidence_check": EvidenceCheckTool(DEFAULT_OUTPUT),
        "web_search": WebSearchTool(),
    }
    agent = PurchaseDecisionAgent(
        provider,
        tools,
        session_memory=SessionMemoryStore(),
        preference_memory=LongTermPreferenceStore(
            f"C:/ai/smartbuy-stage6/preferences-{group}-r{repetition}.json"
        ),
        constraint_verifier=(
            CandidateConstraintVerifier(DEFAULT_OUTPUT, as_of=AS_OF)
            if checker_enabled else None
        ),
        enable_constraint_checker=checker_enabled,
    )
    report = await agent.run(
        case["question"], session_id=f"stage6-{group}-r{repetition}-{case['case_id']}"
    )
    _, records = _usage_delta(provider.ledger, ledger_start)
    return _agent_prediction(report, case, group, repetition, records)


def _attach_verification(prediction: dict[str, Any], case: dict[str, Any]) -> None:
    normalizer = ConstraintNormalizer()
    constraint_set = normalizer.build(case["question"], source_turn=1)
    hard = [
        item for item in constraint_set.active(hard_only=True)
        if item.hard_or_soft == ConstraintStrength.HARD
    ]
    prediction["has_hard_constraints"] = bool(hard)
    verifier = CandidateConstraintVerifier(DEFAULT_OUTPUT, as_of=AS_OF)
    recommended = prediction.get("recommended_model_ids", [])
    batch = verifier.verify_candidates(constraint_set, recommended)
    prediction["recommended_candidate_verifications"] = [
        {"model_id": item.model_id, "overall_status": item.overall_status.value}
        for item in batch.candidates
    ]
    prediction["hard_constraint_checks"] = [
        {
            "model_id": item.model_id,
            "field": result.constraint.field,
            "status": result.status.value,
        }
        for item in batch.candidates
        for result in item.constraint_results
        if result.constraint.hard_or_soft == ConstraintStrength.HARD
    ]


def _error_prediction(case: dict[str, Any], group: str, repetition: int, exc: Exception) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "experiment_group": group,
        "repetition": repetition,
        "recommended_model_ids": [],
        "observed_model_ids": [],
        "abstained": True,
        "claims": [],
        "evidence_ids": [],
        "source_ids": [],
        "citation_pairs": [],
        "unsupported_constraints": [],
        "unknown_or_conflict_reported": False,
        "retrieved_model_ids": None,
        "tools_used": [],
        "tool_call_count": 0,
        "multihop_pass": False,
        "tool_order_pass": False,
        "blocked_unauthorized_or_out_of_order": [],
        "degraded_states": ["evaluation task failed without sensitive details"],
        "degradation_visible": True,
        "limit_reached": False,
        "schema_pass": False,
        "latency_ms": 0.0,
        "usage": {"call_count": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_cny": 0.0},
        "usage_records": [],
        "error_category": type(exc).__name__,
    }


def _checkpoint_append(path: Path, prediction: dict[str, Any], config_hash: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"config_hash": config_hash, "prediction": prediction}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _checkpoint_load(path: Path, config_hash: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("config_hash") != config_hash:
            raise RuntimeError("existing checkpoint belongs to another frozen config")
        rows.append(row["prediction"])
    return rows


def _build_ledger(
    predictions: list[dict[str, Any]], config: dict[str, Any], run_id: str
) -> EvaluationLedger:
    ledger = EvaluationLedger()
    for row in predictions:
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        step = 0
        for item in row.get("usage_records", []):
            step += 1
            ledger.add(
                EvaluationLedgerRecord(
                    run_id=run_id,
                    case_id=row["case_id"],
                    experiment_group=row["experiment_group"],
                    repetition=row["repetition"],
                    data_version=config["data_version"],
                    config_hash=config["config_hash"],
                    model=str(item.get("model")),
                    tool=str(item.get("operation")),
                    step=step,
                    started_at=now,
                    ended_at=now,
                    duration_ms=float(item.get("latency_ms", 0)),
                    status="success" if item.get("success") else "failed",
                    retry_count=max(0, int(item.get("attempts", 1)) - 1),
                    cache_hit=False,
                    degraded=bool(item.get("degraded")),
                    input_tokens=int(item.get("input_tokens", 0)),
                    output_tokens=int(item.get("output_tokens", 0)),
                    estimated_cost_cny=float(item.get("estimated_cost_cny", 0)),
                    error_category=(
                        f"http_{item.get('status_code')}" if item.get("status_code") else None
                    ),
                )
            )
        for trace in row.get("public_trace", []):
            step += 1
            ledger.add(
                EvaluationLedgerRecord(
                    run_id=run_id,
                    case_id=row["case_id"],
                    experiment_group=row["experiment_group"],
                    repetition=row["repetition"],
                    data_version=config["data_version"],
                    config_hash=config["config_hash"],
                    tool=trace.get("tool"),
                    step=step,
                    parent_step=trace.get("parent_step"),
                    started_at=now,
                    ended_at=now,
                    duration_ms=float(trace.get("duration_ms", 0)),
                    status=trace.get("status", "failed"),
                    degraded=trace.get("status") in {"degraded", "unavailable"},
                    error_category=(trace.get("tool") if trace.get("status") == "failed" else None),
                )
            )
        ledger.add(
            EvaluationLedgerRecord(
                run_id=run_id,
                case_id=row["case_id"],
                experiment_group=row["experiment_group"],
                repetition=row["repetition"],
                data_version=config["data_version"],
                config_hash=config["config_hash"],
                tool="final_result",
                step=step + 1,
                started_at=now,
                ended_at=now,
                duration_ms=float(row.get("latency_ms", 0)),
                status="success" if row.get("schema_pass") else "failed",
                degraded=bool(row.get("degraded_states")),
                error_category=row.get("error_category"),
                final_metrics={
                    "abstained": bool(row.get("abstained")),
                    "recommended_count": len(row.get("recommended_model_ids", [])),
                    "schema_pass": bool(row.get("schema_pass")),
                },
            )
        )
    return ledger


async def evaluate(
    *,
    smoke: bool,
    repetitions: int,
    repetition_start: int,
    groups: tuple[str, ...],
    case_ids: set[str] | None,
    checkpoint_path: Path | None,
) -> dict[str, Any]:
    frozen = validate_freeze()
    if not frozen["passed"]:
        raise RuntimeError(f"freeze validation failed: {frozen['errors']}")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cases = load_jsonl(CASES_PATH)
    if case_ids:
        cases = [item for item in cases if item["case_id"] in case_ids]
        missing = case_ids - {item["case_id"] for item in cases}
        if missing:
            raise ValueError(f"unknown case ids: {sorted(missing)}")
    if smoke:
        cases = [cases[index] for index in (0, 1, 3) if index < len(cases)]
        repetition_start = 1
        repetitions = 1
    if repetition_start < 1 or repetition_start > repetitions:
        raise ValueError("repetition_start must be between 1 and repetitions")
    settings = load_bailian_settings()
    usage_ledger = UsageLedger()
    provider = BailianProvider(settings, ledger=usage_ledger, timeout_seconds=30.0)
    evidence_by_id, evidence_by_model_field = _evidence_maps()
    predictions = (
        _checkpoint_load(checkpoint_path, config["config_hash"])
        if checkpoint_path is not None else []
    )
    done = {
        (item["case_id"], item["experiment_group"], int(item["repetition"]))
        for item in predictions
    }
    try:
        for repetition in range(repetition_start, repetitions + 1):
            for case in cases:
                for group in groups:
                    key = (case["case_id"], group, repetition)
                    if key in done:
                        continue
                    if float(usage_ledger.summary()["estimated_cost_cny"]) >= float(config["stage_cost_limit_cny"]):
                        raise RuntimeError("Stage 6 API cost limit reached before evaluation completed")
                    try:
                        if group == "direct_llm":
                            prediction = await _run_direct(provider, case, repetition)
                        elif group == "fixed_rag":
                            prediction = await _run_fixed_rag(
                                provider, settings, case, repetition, evidence_by_model_field
                            )
                        else:
                            prediction = await _run_agent(
                                provider,
                                settings,
                                case,
                                repetition,
                                checker_enabled=group == "agentic_rag_checker",
                            )
                    except (Exception, ValidationError) as exc:
                        prediction = _error_prediction(case, group, repetition, exc)
                    _attach_verification(prediction, case)
                    predictions.append(prediction)
                    done.add(key)
                    if checkpoint_path is not None:
                        _checkpoint_append(checkpoint_path, prediction, config["config_hash"])
                    print(
                        json.dumps(
                            {
                                "progress": f"{len(done)}/{len(cases) * len(groups) * (repetitions - repetition_start + 1)}",
                                "case_id": case["case_id"],
                                "group": group,
                                "repetition": repetition,
                                "cost_cny": usage_ledger.summary()["estimated_cost_cny"],
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
    finally:
        await provider.aclose()
    expected_keys = {
        (case["case_id"], group, repetition)
        for repetition in range(repetition_start, repetitions + 1)
        for case in cases
        for group in groups
    }
    predictions = [
        item for item in predictions
        if (item["case_id"], item["experiment_group"], int(item["repetition"])) in expected_keys
    ]
    predictions.sort(key=lambda item: (item["repetition"], item["case_id"], GROUPS.index(item["experiment_group"])))
    cases_by_id = {item["case_id"]: item for item in cases}
    first_run = {
        group: score_group(
            [item for item in predictions if item["experiment_group"] == group and item["repetition"] == 1],
            cases_by_id,
            evidence_by_id,
        )
        for group in groups
    }
    aggregate = {
        group: score_group(
            [item for item in predictions if item["experiment_group"] == group],
            cases_by_id,
            evidence_by_id,
        )
        for group in groups
    }
    first_run_by_split = {
        split: {
            group: score_group(
                [
                    item for item in predictions
                    if item["experiment_group"] == group
                    and item["repetition"] == 1
                    and cases_by_id[item["case_id"]]["split"] == split
                ],
                cases_by_id,
                evidence_by_id,
            )
            for group in groups
        }
        for split in ("regression", "holdout")
    }
    aggregate_by_split = {
        split: {
            group: score_group(
                [
                    item for item in predictions
                    if item["experiment_group"] == group
                    and cases_by_id[item["case_id"]]["split"] == split
                ],
                cases_by_id,
                evidence_by_id,
            )
            for group in groups
        }
        for split in ("regression", "holdout")
    }
    run_id = f"stage6-{uuid.uuid4().hex[:12]}"
    total_cost = round(
        sum(float(item.get("usage", {}).get("estimated_cost_cny", 0)) for item in predictions), 8
    )
    return {
        "evaluation_version": config["evaluation_version"],
        "mode": "smoke" if smoke else "full",
        "run_id": run_id,
        "frozen_config": config,
        "freeze_validation": frozen,
        "case_count": len(cases),
        "repetitions": repetitions,
        "repetition_start": repetition_start,
        "prediction_count": len(predictions),
        "experiment_groups": list(groups),
        "first_run_metrics": first_run,
        "first_run_split_metrics": first_run_by_split,
        "aggregate_metrics": aggregate,
        "aggregate_split_metrics": aggregate_by_split,
        "stability": score_stability(predictions),
        "cost": {
            "estimated_cost_cny": total_cost,
            "stage_limit_cny": config["stage_cost_limit_cny"],
            "within_limit": total_cost <= float(config["stage_cost_limit_cny"]),
        },
        "predictions": predictions,
    }


def _write_result(payload: dict[str, Any], output: Path, ledger_output: Path | None) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if ledger_output is not None:
        config = payload["frozen_config"]
        _build_ledger(payload["predictions"], config, payload["run_id"]).write(ledger_output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-freeze", action="store_true")
    mode.add_argument("--smoke", action="store_true")
    mode.add_argument("--full", action="store_true")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--repetition-start", type=int, default=1)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--group", action="append", choices=GROUPS, default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT_PATH)
    parser.add_argument("--ledger-output", type=Path)
    parser.add_argument("--no-ledger", action="store_true")
    args = parser.parse_args()
    if args.validate_freeze:
        result = validate_freeze()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["passed"] else 1
    output = args.output or (SMOKE_PATH if args.smoke else RESULTS_PATH)
    payload = asyncio.run(
        evaluate(
            smoke=args.smoke,
            repetitions=args.repetitions,
            repetition_start=args.repetition_start,
            groups=tuple(args.group) or GROUPS,
            case_ids=set(args.case_id) or None,
            checkpoint_path=None if args.smoke else args.checkpoint,
        )
    )
    ledger_output = None if args.smoke or args.no_ledger else (args.ledger_output or LEDGER_PATH)
    _write_result(payload, output, ledger_output)
    print(
        json.dumps(
            {
                "mode": payload["mode"],
                "case_count": payload["case_count"],
                "repetitions": payload["repetitions"],
                "cost": payload["cost"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
