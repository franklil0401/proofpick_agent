"""Freeze and execute one immutable V2-6C-R3 Laptop validation round.

The runner uses the existing governed Laptop data and index.  It does not
rebuild either artifact, does not call Source Search/Open Research, and keeps
the deterministic constraint parser as the primary understanding path.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import statistics
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smartbuy.agent import DomainDecisionAgent
from smartbuy.config import load_bailian_settings
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.constraints import ConstraintProvenance
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.memory import DomainPreferenceMemoryStore
from smartbuy.orchestration.contracts import OrchestratorRequest
from smartbuy.orchestration.react_adapter import ReactOrchestrator
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.providers import BailianProvider, RetryPolicy
from smartbuy.retrieval.domain_index import DomainIndexManager
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainKBSearchTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)

from .v2_6c_r3_validation_scorer import score_results


ROOT = Path(__file__).resolve().parents[2]
ROUND = 1
CASES = ROOT / "smartbuy/eval/v2_6c_r3_validation_round1.jsonl"
MANIFEST = ROOT / "smartbuy/eval/v2_6c_r3_validation_round1_manifest.json"
POLICY = ROOT / "smartbuy/eval/v2_6c_r3_validation_round1_policy.json"
SCHEMA = ROOT / "smartbuy/eval/v2_6c_r3_validation.schema.json"
SCORER = ROOT / "smartbuy/eval/v2_6c_r3_validation_scorer.py"
RUNNER = ROOT / "smartbuy/eval/v2_6c_r3_validation_runner.py"
DOMAIN_PACK = ROOT / "smartbuy/domain_packs/laptop"
PRODUCT_PACK = ROOT / "smartbuy/product_packs/examples/laptop-v1/pack.json"
DATA_VERSION = "laptop-governed-2026-09-02-v1"
INDEX_VERSION = "laptop-governed-2026-09-02-v1-embedding1024-v1"
COLLECTION = "proofpick_laptop_v2_4e6d332c11bf8f7c"
MAX_MODEL_REQUESTS = 300
MAX_COST_CNY = 5.0

PRODUCTION_FILES = (
    "smartbuy/agent/domain_agent.py",
    "smartbuy/constraint_proposals/engine.py",
    "smartbuy/decision_core/canonical.py",
    "smartbuy/decision_core/delta.py",
    "smartbuy/decision_core/intent.py",
    "smartbuy/decision_core/scope.py",
    "smartbuy/domain/models.py",
    "smartbuy/domain_packs/evaluator.py",
    "smartbuy/domain_packs/laptop/fields.json",
    "smartbuy/domain_packs/laptop/policies.json",
    "smartbuy/domain_packs/loader.py",
    "smartbuy/identity/models.py",
    "smartbuy/identity/resolver.py",
    "smartbuy/tools/domain.py",
)


def _select_round(round_number: int) -> None:
    """Select an already-frozen evaluation round without changing its policy."""

    global ROUND, CASES, MANIFEST, POLICY
    ROUND = round_number
    CASES = ROOT / f"smartbuy/eval/v2_6c_r3_validation_round{ROUND}.jsonl"
    MANIFEST = ROOT / f"smartbuy/eval/v2_6c_r3_validation_round{ROUND}_manifest.json"
    POLICY = ROOT / f"smartbuy/eval/v2_6c_r3_validation_round{ROUND}_policy.json"
    if not all(path.is_file() for path in (CASES, MANIFEST, POLICY)):
        raise RuntimeError(f"validation round {ROUND} is not frozen")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _cases() -> list[dict[str, Any]]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if _sha(CASES) != manifest["case_sha256"] or _sha(CASES) != policy["case_sha256"]:
        raise RuntimeError("validation freeze SHA-256 changed")
    rows = [
        json.loads(line)
        for line in CASES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 24 or any(
        row.get("evaluation_state") != "frozen_unrun" or row.get("run_count") != 0
        for row in rows
    ):
        raise RuntimeError("validation freeze state is not 24 x frozen_unrun")
    if manifest.get("run_count") != 0:
        raise RuntimeError("validation manifest records a previous run")
    return rows


def _runtime(runtime_root: Path) -> tuple[Any, Any, Any]:
    pack = DomainPackLoader().load(DOMAIN_PACK)
    manager = DomainProductPackManager(runtime_root / "data", domain_pack_path=DOMAIN_PACK)
    snapshot = manager.current()
    index_manager = DomainIndexManager(
        runtime_root / "index",
        data_manager=manager,
        domain_id=pack.domain_id,
        domain_pack_version=pack.version,
    )
    index = index_manager.current()
    counts = snapshot.manifest.get("counts", {})
    if (
        snapshot.data_version != DATA_VERSION
        or index.data_version != DATA_VERSION
        or index.index_version != INDEX_VERSION
        or index.collection_name != COLLECTION
        or index.manifest.get("embedding_model") != "text-embedding-v4"
        or index.manifest.get("embedding_dimensions") != 1024
        or index.manifest.get("document_count") != 12
        or index.manifest.get("chunk_count") != 12
        or counts.get("products") != 12
        or counts.get("source_records") != 12
        or counts.get("evidence_records") != 406
    ):
        raise RuntimeError("governed Laptop Data/Index contract changed")
    return pack, snapshot, index_manager


def _dependency_versions() -> dict[str, str]:
    output = {}
    for name in ("chromadb", "httpx", "langgraph", "pydantic"):
        try:
            output[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            output[name] = "missing"
    return output


def _rc_contract(runtime_root: Path, run_id: str) -> dict[str, Any]:
    cases = _cases()
    pack, snapshot, index_manager = _runtime(runtime_root)
    index = index_manager.current()
    settings = load_bailian_settings()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {
        "schema_version": "proofpick-v2-6c-r3-validation-rc-v1",
        "round": ROUND,
        "run_id": run_id,
        "holdout_commit": _head(),
        "code_freeze_commit": manifest["code_freeze_commit"],
        "case_sha256": _sha(CASES),
        "case_order": [item["case_id"] for item in cases],
        "manifest_sha256": _sha(MANIFEST),
        "policy_sha256": _sha(POLICY),
        "schema_sha256": _sha(SCHEMA),
        "scorer_sha256": _sha(SCORER),
        "runner_sha256": _sha(RUNNER),
        "production_file_sha256": {
            path: _sha(ROOT / path) for path in PRODUCTION_FILES
        },
        "domain_id": pack.domain_id,
        "domain_pack_version": pack.version,
        "product_pack_sha256": _sha(PRODUCT_PACK),
        "data_version": snapshot.data_version,
        "data_manifest_hash": snapshot.manifest_hash,
        "index_version": index.index_version,
        "index_manifest_hash": index.manifest_hash,
        "collection_name": index.collection_name,
        "models": {
            "llm": settings.chat_model,
            "constraint_proposal_mode": "deterministic_primary_no_llm_fallback",
            "embedding": settings.embedding_model,
            "embedding_dimensions": settings.embedding_dimensions,
            "reranker": settings.reranker_model,
        },
        "orchestrator": "react",
        "temperature": 0,
        "max_agent_steps": 8,
        "max_tool_calls": 12,
        "retry": {
            "auth_retries": 0,
            "retryable": [429, 500, 502, 503, 504, "timeout"],
            "max_retries": 2,
            "base_delay_seconds": 0.25,
            "max_delay_seconds": 2.0,
        },
        "cache": "cold_disabled",
        "feature_flags": {
            "domain_pack": True,
            "langgraph": False,
            "source_search": False,
            "web_extractor": False,
            "open_research": False,
            "long_term_memory": False,
        },
        "limits": {"model_requests": MAX_MODEL_REQUESTS, "cost_cny": MAX_COST_CNY},
        "checkpoint": {
            "append_fsync_journal": True,
            "same_run_id_resume_only": True,
            "completed_cases_not_replayed": True,
        },
        "runtime_storage": "repository_external",
        "python": sys.version.split()[0],
        "dependencies": _dependency_versions(),
        "uv_lock_sha256": _sha(ROOT / "vendor/youtu-rag/uv.lock"),
    }


def _atomic(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    os.replace(temporary, path)


def freeze_rc(runtime_root: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise RuntimeError("validation RC already exists")
    run_id = f"v2-6c-r3-v{ROUND}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    payload = _rc_contract(runtime_root, run_id)
    payload["config_sha256"] = _stable_hash(payload)
    payload["frozen_at"] = _now()
    _atomic(output, payload)
    return payload


def _append(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _journal(path: Path, run_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(item.get("run_id") != run_id or not item.get("completed") for item in rows):
        raise RuntimeError("journal is incomplete or belongs to another run")
    ids = [item["case_id"] for item in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("journal repeats a completed case")
    return rows


def _active_constraints(report: Any) -> list[dict[str, Any]]:
    return [
        {
            "field": item.field,
            "operator": item.operator.value,
            "normalized_value": item.normalized_value,
            "unit": item.unit,
            "hard_or_soft": item.hard_or_soft.value,
            "status": "supported",
            "active": True,
        }
        for item in report.constraint_set.active(hard_only=True, supported_only=True)
        if item.provenance != ConstraintProvenance.SYSTEM_DEFAULT
    ]


def _result(report: Any) -> tuple[str, list[str], str | None]:
    if report.clarification_state.value == "pending":
        reason = (
            "ambiguous_product_scope"
            if report.product_scope and report.product_scope.clarification_required
            else "ambiguous_constraint"
        )
        return "clarify", [], reason
    if report.abstained:
        return "abstain", [], "insufficient_governed_evidence"
    if report.recommended_model_ids:
        return "eligible", sorted(report.recommended_model_ids), None
    referenced = sorted(
        {
            item.model_id for item in report.candidates
            if any(field.evidence for field in item.fields)
        }
    )
    if referenced:
        return "referenced", referenced, None
    return "abstain", [], "insufficient_governed_evidence"


def _row(case: dict[str, Any], report: Any) -> dict[str, Any]:
    if report.product_scope is None or report.constraint_verification is None:
        raise RuntimeError("Agent omitted scope or deterministic Checker envelope")
    scope = report.product_scope
    result_kind, final_ids, abstain_reason = _result(report)
    checker_used = "domain_constraint_checker" in report.tools_used
    checker_ids = (
        report.constraint_verification.candidate_pool_model_ids if checker_used else []
    )
    evidence = [
        {
            "product_id": item.product_id,
            "field_id": item.field,
            "status": "matched",
            "evidence_id": item.evidence_id,
            "source_id": item.source_id,
            "configuration_id": item.configuration_id,
            "region": item.region,
        }
        for item in report.evidence
    ]
    observed = sorted(
        {
            *[item.product_id for item in report.candidates],
            *[item.product_id for item in report.evidence],
            *report.recommended_model_ids,
            *checker_ids,
        }
    )
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "product_scope": {
            "scope_type": scope.scope_type.value,
            "family_ids": scope.family_ids,
            "product_ids": scope.product_ids,
            "configuration_ids": scope.configuration_ids,
            "regions": scope.regions,
            "explicit_comparison": scope.explicit_comparison,
            "clarification_required": scope.clarification_required,
            "resolution_status": scope.resolution_status.value,
            "resolution_reason": scope.resolution_reason,
        },
        "active_constraints": _active_constraints(report),
        "tools_used": report.tools_used,
        "tool_trace": [
            {
                "step": item.step, "parent_step": item.parent_step,
                "tool": item.tool, "status": item.status,
                "duration_ms": item.duration_ms, "result_summary": item.result_summary,
            }
            for item in report.trace
        ],
        "checker_candidate_ids": sorted(checker_ids),
        "result_kind": result_kind,
        "final_candidate_ids": final_ids,
        "clarification_required": report.clarification_state.value == "pending",
        "abstain_reason": abstain_reason,
        "observed_product_ids": observed,
        "candidate_regions": {item.product_id: item.region for item in report.candidates},
        "evidence": evidence,
        "unresolved_facts": [item.model_dump(mode="json") for item in report.unresolved_facts],
        "degraded_states": report.degraded_states,
        "report": report.model_dump(mode="json"),
    }


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))]


async def run_once(runtime_root: Path, rc_path: Path, journal_path: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise RuntimeError("immutable validation result already exists")
    cases = _cases()
    rc = json.loads(rc_path.read_text(encoding="utf-8"))
    current = _rc_contract(runtime_root, rc["run_id"])
    if _stable_hash(current) != rc["config_sha256"]:
        raise RuntimeError("RC configuration changed after freeze")
    completed = _journal(journal_path, rc["run_id"])
    expected_prefix = [item["case_id"] for item in cases[: len(completed)]]
    if [item["case_id"] for item in completed] != expected_prefix:
        raise RuntimeError("journal order differs from frozen case order")
    rows = [item["case_result"] for item in completed]
    resumed = bool(completed)
    previous_events = [event for row in rows for event in row.get("api_events", [])]
    previous_cost = sum(float(event["estimated_cost_cny"]) for event in previous_events)
    previous_requests = len(previous_events)
    pack, snapshot, index_manager = _runtime(runtime_root)
    repository = DomainReadonlyRepository(snapshot, pack)
    settings = load_bailian_settings()
    retry = RetryPolicy(max_retries=2, base_delay_seconds=0.25, max_delay_seconds=2.0)
    memory_root = runtime_root / "evaluation" / rc["run_id"] / "memory"
    async with BailianProvider(settings, timeout_seconds=30.0, retry_policy=retry) as provider:
        # Clear deterministic expressions do not require an LLM proposal.  The
        # same Provider is used only by the already-built KB embedding/reranker.
        engine = NaturalConstraintEngine(pack, provider=None)
        agent = DomainDecisionAgent(
            pack,
            repository,
            DomainProductQueryTool(repository),
            DomainEvidenceCheckTool(repository),
            DomainConstraintCheckerTool(repository),
            engine,
            DomainPreferenceMemoryStore(memory_root, pack),
            kb_search=DomainKBSearchTool(index_manager, provider),
            max_steps=8,
            max_tool_calls=12,
        )
        orchestrator = ReactOrchestrator(agent)
        for sequence, case in enumerate(cases[len(completed):], start=len(completed) + 1):
            events = provider.ledger.snapshot()
            if previous_requests + len(events) >= MAX_MODEL_REQUESTS:
                raise RuntimeError("model request budget exhausted")
            if previous_cost + sum(float(item["estimated_cost_cny"]) for item in events) >= MAX_COST_CNY:
                raise RuntimeError("model cost budget exhausted")
            before = len(events)
            started = time.perf_counter()
            result = await orchestrator.run(
                OrchestratorRequest(
                    query="笔记本：" + case["question"],
                    session_id=f"{rc['run_id']}-{case['case_id']}",
                    user_id=f"validation-{case['case_id']}",
                    thread_id=f"{rc['run_id']}-{case['case_id']}",
                )
            )
            if result.report is None:
                raise RuntimeError("orchestrator returned no report")
            row = _row(case, result.report)
            row["wall_latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
            row["orchestrator"] = "react"
            row["api_events"] = provider.ledger.snapshot()[before:]
            row["cache_hit"] = False
            row["checkpoint_resumed"] = resumed
            _append(
                journal_path,
                {
                    "schema_version": "proofpick-v2-6c-r3-validation-journal-v1",
                    "run_id": rc["run_id"], "sequence": sequence,
                    "case_id": case["case_id"], "completed": True,
                    "completed_at": _now(), "case_result": row,
                },
            )
            rows.append(row)
    if len(rows) != len(cases):
        raise RuntimeError("validation run did not complete all cases")
    score_input = output.with_suffix(".score-input.tmp")
    _atomic(score_input, {"frozen_case_sha256": _sha(CASES), "cases": rows})
    try:
        metrics = score_results(
            score_input, cases_path=CASES, policy_path=POLICY
        )
    finally:
        score_input.unlink(missing_ok=True)
    events = [event for row in rows for event in row["api_events"]]
    latencies = [float(row["wall_latency_ms"]) for row in rows]
    api = {
        "request_count": len(events),
        "by_model": {
            model: sum(event["model"] == model for event in events)
            for model in sorted({event["model"] for event in events})
        },
        "input_tokens": sum(int(event["input_tokens"]) for event in events),
        "output_tokens": sum(int(event["output_tokens"]) for event in events),
        "estimated_cost_cny": sum(float(event["estimated_cost_cny"]) for event in events),
        "retry_count": sum(max(0, int(event["attempts"]) - 1) for event in events),
        "failed_requests": sum(not event["success"] for event in events),
    }
    failures_by_id = {item["case_id"]: item for item in metrics["cases"] if not item["task_correct"]}
    failures = [
        {
            **failures_by_id[row["case_id"]],
            "expected": next(case["gold"] for case in cases if case["case_id"] == row["case_id"]),
            "actual": {
                "product_scope": row["product_scope"],
                "active_constraints": row["active_constraints"],
                "tools_used": row["tools_used"],
                "checker_candidate_ids": row["checker_candidate_ids"],
                "result_kind": row["result_kind"],
                "final_candidate_ids": row["final_candidate_ids"],
            },
        }
        for row in rows if row["case_id"] in failures_by_id
    ]
    payload = {
        "schema_version": "proofpick-v2-6c-r3-validation-first-result-v1",
        "classification": "代码冻结后生成并单次运行的验证集",
        "round": ROUND,
        "run_id": rc["run_id"],
        "run_number": 1,
        "created_at": _now(),
        "frozen_case_sha256": _sha(CASES),
        "rc_file_sha256": _sha(rc_path),
        "rc_config_sha256": rc["config_sha256"],
        "orchestrator": "react",
        "cache": "cold_disabled",
        "checkpoint": {"resumed": resumed, "completed_cases_replayed": 0},
        "data_version": DATA_VERSION,
        "index_version": INDEX_VERSION,
        "collection_name": COLLECTION,
        "metrics": metrics,
        "latency": {
            "average_ms": statistics.mean(latencies),
            "p95_ms": _percentile(latencies, 0.95),
        },
        "api": api,
        "failures": failures,
        "cases": rows,
    }
    _atomic(output, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--runtime-root", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--freeze-release-candidate", action="store_true")
    action.add_argument("--run-once", action="store_true")
    parser.add_argument("--rc-output", type=Path, required=True)
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    _select_round(args.round)
    if args.freeze_release_candidate:
        payload = freeze_rc(args.runtime_root.resolve(), args.rc_output.resolve())
        print(json.dumps({"status": "frozen", "run_id": payload["run_id"], "config_sha256": payload["config_sha256"]}, ensure_ascii=False))
        return 0
    if args.journal is None or args.output is None:
        parser.error("--run-once requires --journal and --output")
    payload = asyncio.run(run_once(args.runtime_root.resolve(), args.rc_output.resolve(), args.journal.resolve(), args.output.resolve()))
    print(json.dumps({"status": "completed", "run_id": payload["run_id"], "metrics": payload["metrics"], "api": payload["api"], "latency": payload["latency"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
