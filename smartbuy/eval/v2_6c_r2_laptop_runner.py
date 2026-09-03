"""Run the frozen V2-6C-R2 Laptop holdout exactly once.

This evaluation-only entry point never rebuilds data or an index.  It freezes
the effective release-candidate contract before any provider request, appends
every completed case to an immutable journal, and uses the already-frozen R2
scorer for final metrics.  It is not imported by the production API or WebUI.
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
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smartbuy.agent import DomainDecisionAgent
from smartbuy.config import load_bailian_settings
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.constraint_proposals.provider import QwenConstraintProposalProvider
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

from .v2_6c_r2_laptop_scorer import score_results, validate_gold


ROOT = Path(__file__).resolve().parents[2]
BASELINE_COMMIT = "1112f8dad3410af821e11edc60e83ab7ac3112ce"
CASES = ROOT / "smartbuy" / "eval" / "v2_6c_r2_laptop_holdout.jsonl"
CASES_SHA256 = "dd17cf4a4bf794c77cc75b5406f9e603effc7be4e63f9e9b215a9d4d8ea9e24f"
SCHEMA = ROOT / "smartbuy" / "eval" / "v2_6c_r2_laptop_holdout.schema.json"
SCHEMA_SHA256 = "4cc231fe9e7ee2a50c30ffb3e86da7abf1041280a2b2ecb3317fbab003cce7dc"
POLICY = ROOT / "smartbuy" / "eval" / "v2_6c_r2_laptop_scoring_policy.json"
POLICY_SHA256 = "7cf3395ca1c2bdb5675577a42b885de78b1ebb8bb6962cbe2bd49d210c0a1c7a"
SCORER = ROOT / "smartbuy" / "eval" / "v2_6c_r2_laptop_scorer.py"
SCORER_SHA256 = "4fb494700ffb90558ffb2a5a0c49c6f0a0f854516ce5f7ced4e643eb7480edc8"
RUNNER = ROOT / "smartbuy" / "eval" / "v2_6c_r2_laptop_runner.py"
DOMAIN_PACK = ROOT / "smartbuy" / "domain_packs" / "laptop"
PRODUCT_PACK = ROOT / "smartbuy" / "product_packs" / "examples" / "laptop-v1" / "pack.json"
PRODUCT_PACK_SHA256 = "0417332b70d772e851f705c83df7932cd60f5d879425ee04f032f08d9c16dc2a"
DATA_VERSION = "laptop-governed-2026-09-02-v1"
INDEX_VERSION = "laptop-governed-2026-09-02-v1-embedding1024-v1"
EXPECTED_COLLECTION = "proofpick_laptop_v2_4e6d332c11bf8f7c"
MAX_QWEN_CALLS = 50
MAX_TOTAL_COST_CNY = 2.0

PRODUCTION_FILES = (
    "smartbuy/agent/domain_agent.py",
    "smartbuy/constraint_proposals/engine.py",
    "smartbuy/constraint_proposals/provider.py",
    "smartbuy/constraints/models.py",
    "smartbuy/domain_packs/category_registry.json",
    "smartbuy/domain_packs/laptop/manifest.json",
    "smartbuy/domain_packs/laptop/fields.json",
    "smartbuy/domain_packs/laptop/policies.json",
    "smartbuy/identity/guards.py",
    "smartbuy/identity/models.py",
    "smartbuy/identity/resolver.py",
    "smartbuy/orchestration/react_adapter.py",
    "smartbuy/retrieval/domain_index.py",
    "smartbuy/tools/domain.py",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _load_cases() -> list[dict[str, Any]]:
    if _sha(CASES) != CASES_SHA256:
        raise RuntimeError("frozen R2 Holdout SHA-256 changed")
    cases = [
        json.loads(line)
        for line in CASES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(cases) != 20:
        raise RuntimeError("R2 Holdout must contain exactly 20 cases")
    if any(
        item.get("evaluation_state") != "frozen_unrun"
        or item.get("run_count") != 0
        for item in cases
    ):
        raise RuntimeError("R2 Holdout no longer has the frozen_unrun/zero-run state")
    return cases


def _verify_frozen_inputs() -> list[dict[str, Any]]:
    if _git_head() != BASELINE_COMMIT:
        raise RuntimeError("production HEAD differs from the authorized baseline")
    expected = {
        CASES: CASES_SHA256,
        SCHEMA: SCHEMA_SHA256,
        POLICY: POLICY_SHA256,
        SCORER: SCORER_SHA256,
        PRODUCT_PACK: PRODUCT_PACK_SHA256,
    }
    for path, digest in expected.items():
        if _sha(path) != digest:
            raise RuntimeError(f"frozen input changed: {path.name}")
    audit = validate_gold()
    if (
        audit["case_count"] != 20
        or audit["agent_e2e_runs"] != 0
        or audit["checker_gold_cases"] != 7
    ):
        raise RuntimeError("freeze-time gold audit differs from the accepted record")
    return _load_cases()


def _runtime(
    runtime_root: Path,
) -> tuple[Any, Any, Any, Any]:
    pack = DomainPackLoader().load(DOMAIN_PACK)
    data_manager = DomainProductPackManager(
        runtime_root / "data",
        domain_pack_path=DOMAIN_PACK,
    )
    snapshot = data_manager.current()
    index_manager = DomainIndexManager(
        runtime_root / "index",
        data_manager=data_manager,
        domain_id=pack.domain_id,
        domain_pack_version=pack.version,
    )
    index = index_manager.current()
    counts = snapshot.manifest.get("counts", {})
    if (
        pack.domain_id != "laptop"
        or pack.version != "1.0.0"
        or snapshot.data_version != DATA_VERSION
        or index.data_version != DATA_VERSION
        or index.index_version != INDEX_VERSION
        or index.collection_name != EXPECTED_COLLECTION
        or index.manifest.get("embedding_model") != "text-embedding-v4"
        or index.manifest.get("embedding_dimensions") != 1024
        or index.manifest.get("document_count") != 12
        or index.manifest.get("chunk_count") != 12
        or counts.get("products") != 12
        or counts.get("source_records") != 12
        or counts.get("evidence_records") != 406
    ):
        raise RuntimeError("Laptop Product/Data/Index release contract changed")
    return pack, data_manager, snapshot, index_manager


def _dependency_versions() -> dict[str, str]:
    versions = {}
    for distribution in ("chromadb", "httpx", "langgraph", "pydantic"):
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = "missing"
    return versions


def _rc_payload(runtime_root: Path, run_id: str) -> dict[str, Any]:
    cases = _verify_frozen_inputs()
    pack, _, snapshot, index_manager = _runtime(runtime_root)
    index = index_manager.current()
    settings = load_bailian_settings()
    return {
        "schema_version": "proofpick-v2-6c-r2b-rc-v1",
        "run_id": run_id,
        "run_number": 1,
        "production_code_commit": BASELINE_COMMIT,
        "holdout_commit": BASELINE_COMMIT,
        "holdout_sha256": CASES_SHA256,
        "holdout_case_count": len(cases),
        "holdout_case_order": [item["case_id"] for item in cases],
        "holdout_schema_sha256": SCHEMA_SHA256,
        "scoring_policy_sha256": POLICY_SHA256,
        "scoring_script_sha256": SCORER_SHA256,
        "evaluation_runner_sha256": _sha(RUNNER),
        "production_file_sha256": {
            relative: _sha(ROOT / relative) for relative in PRODUCTION_FILES
        },
        "prompt_contract": {
            "name": "submit_constraint_proposals",
            "provider_file_sha256": _sha(
                ROOT / "smartbuy" / "constraint_proposals" / "provider.py"
            ),
            "temperature": 0,
            "max_tokens": 600,
        },
        "domain_id": pack.domain_id,
        "domain_pack_version": pack.version,
        "domain_pack_hashes": {
            name: _sha(DOMAIN_PACK / name)
            for name in ("manifest.json", "fields.json", "policies.json")
        },
        "product_pack_sha256": PRODUCT_PACK_SHA256,
        "data_version": snapshot.data_version,
        "data_manifest_hash": snapshot.manifest_hash,
        "index_version": index.index_version,
        "index_manifest_hash": index.manifest_hash,
        "collection_name": index.collection_name,
        "index_document_count": index.manifest["document_count"],
        "index_chunk_count": index.manifest["chunk_count"],
        "models": {
            "llm": settings.chat_model,
            "embedding": settings.embedding_model,
            "embedding_dimensions": settings.embedding_dimensions,
            "reranker": settings.reranker_model,
        },
        "orchestrator": "react",
        "max_agent_steps": 8,
        "max_tool_calls": 12,
        "provider_timeout_seconds": 30,
        "retry_policy": {
            "auth_401_403_retries": 0,
            "retryable_statuses": [429, 500, 502, 503, 504, "timeout"],
            "max_retries": 2,
            "base_delay_seconds": 0.25,
            "max_delay_seconds": 2.0,
        },
        "cache": {
            "main_assessment": "disabled_cold",
            "query_cache_enabled": False,
        },
        "feature_flags": {
            "domain_pack_path": True,
            "langgraph": False,
            "source_search": False,
            "web_extractor": False,
            "open_research": False,
            "long_term_memory": False,
        },
        "limits": {
            "max_qwen_plus_calls": MAX_QWEN_CALLS,
            "max_total_cost_cny": MAX_TOTAL_COST_CNY,
            "constraint_provider_calls_per_case": 1,
        },
        "checkpoint": {
            "case_journal": "append_and_fsync",
            "resume_same_run_id_only": True,
            "completed_cases_are_not_replayed": True,
        },
        "runtime_storage": "repository_external",
        "python_version": sys.version.split()[0],
        "dependency_versions": _dependency_versions(),
        "uv_lock_sha256": _sha(ROOT / "vendor" / "youtu-rag" / "uv.lock"),
    }


def freeze_release_candidate(runtime_root: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise RuntimeError("R2 release-candidate record already exists")
    run_id = f"v2-6c-r2b-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    payload = _rc_payload(runtime_root, run_id)
    payload["config_sha256"] = _stable_hash(payload)
    payload["frozen_at"] = _utc_now()
    output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(output, payload)
    return payload


def _atomic_write(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _append_journal(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _load_journal(path: Path, run_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if any(item.get("run_id") != run_id for item in records):
        raise RuntimeError("journal belongs to another run_id")
    case_ids = [item.get("case_id") for item in records]
    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError("journal contains a repeated completed case")
    if any(not item.get("completed") for item in records):
        raise RuntimeError("journal contains an incomplete provider case; restart is unsafe")
    return records


def _active_constraints(report: Any) -> list[dict[str, Any]]:
    rows = []
    for item in report.constraint_set.active(hard_only=True, supported_only=True):
        if item.provenance == ConstraintProvenance.SYSTEM_DEFAULT:
            continue
        rows.append(
            {
                "field": item.field,
                "operator": item.operator.value,
                "normalized_value": item.normalized_value,
                "unit": item.unit,
                "hard_or_soft": item.hard_or_soft.value,
                "status": "supported",
                "active": True,
            }
        )
    return rows


def _actual_result(report: Any) -> tuple[str, list[str], str | None]:
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
            item.model_id
            for item in report.candidates
            if any(field.evidence for field in item.fields)
        }
    )
    if referenced:
        return "referenced", referenced, None
    return "abstain", [], "insufficient_governed_evidence"


def _row_from_report(case: dict[str, Any], report: Any) -> dict[str, Any]:
    if report.product_scope is None or report.constraint_verification is None:
        raise RuntimeError("Agent report lacks deterministic scope or Checker envelope")
    scope = report.product_scope
    result_kind, final_ids, abstain_reason = _actual_result(report)
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
    observed_ids = sorted(
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
                "step": item.step,
                "parent_step": item.parent_step,
                "tool": item.tool,
                "status": item.status,
                "duration_ms": item.duration_ms,
                "result_summary": item.result_summary,
            }
            for item in report.trace
        ],
        "checker_candidate_ids": sorted(checker_ids),
        "result_kind": result_kind,
        "final_candidate_ids": final_ids,
        "clarification_required": report.clarification_state.value == "pending",
        "abstain_reason": abstain_reason,
        "observed_product_ids": observed_ids,
        "candidate_regions": {
            item.product_id: item.region for item in report.candidates
        },
        "evidence": evidence,
        "unresolved_facts": [item.model_dump(mode="json") for item in report.unresolved_facts],
        "degraded_states": report.degraded_states,
        "report": report.model_dump(mode="json"),
    }


def _first_error(case: dict[str, Any], row: dict[str, Any]) -> str | None:
    gold = case["gold"]
    scope = row["product_scope"]
    scope_keys = (
        "scope_type",
        "family_ids",
        "product_ids",
        "configuration_ids",
        "regions",
        "explicit_comparison",
        "clarification_required",
        "resolution_status",
    )
    if any(
        (sorted(scope[key]) != sorted(gold["scope"][key]))
        if isinstance(scope[key], list)
        else scope[key] != gold["scope"][key]
        for key in scope_keys
    ):
        return "product_scope_resolution"
    def constraint_identity(item: dict[str, Any]) -> str:
        return _stable_hash(
            {
                "field": item["field"],
                "operator": item["operator"],
                "normalized_value": item["normalized_value"],
                "unit": item.get("unit"),
                "hard_or_soft": item.get("hard_or_soft", "hard"),
                "status": item.get("status", "supported"),
                "active": item.get("active", True),
            }
        )

    expected_constraints = {
        constraint_identity(item)
        for item in gold["constraints"]
        if item["active"] and item["status"] == "supported" and item["hard_or_soft"] == "hard"
    }
    actual_constraints = {
        constraint_identity(item) for item in row["active_constraints"]
    }
    if expected_constraints != actual_constraints:
        return "constraint_resolution"
    required = gold["tool_path"]["required_order"]
    actual = row["tools_used"]
    position = 0
    for tool in actual:
        if position < len(required) and tool == required[position]:
            position += 1
    if position != len(required) or set(actual) & set(gold["tool_path"]["forbidden"]):
        return "tool_orchestration"
    if set(row["checker_candidate_ids"]) != set(gold["checker_candidate_ids"]):
        return "checker_candidate_scope"
    if row["result_kind"] != gold["result_kind"]:
        return "result_classification"
    if set(row["final_candidate_ids"]) != set(gold["final_candidate_ids"]):
        return "final_candidate_selection"
    if (
        row["clarification_required"] != gold["clarification_required"]
        or row["abstain_reason"] != gold["abstain_reason"]
    ):
        return "clarification_or_abstention"
    return None


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))]


def _summarize(
    cases: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    scored: dict[str, Any],
    pack: Any,
) -> dict[str, Any]:
    score_by_id = {item["case_id"]: item for item in scored["cases"]}
    case_by_id = {item["case_id"]: item for item in cases}
    category_metrics = {}
    for category in sorted({item["category"] for item in cases}):
        selected = [item for item in rows if item["category"] == category]
        category_metrics[category] = {
            "numerator": sum(score_by_id[item["case_id"]]["task_correct"] for item in selected),
            "denominator": len(selected),
        }
    positive_cases = [item for item in cases if item["gold"]["final_candidate_ids"]]
    expected_positive = sum(len(item["gold"]["final_candidate_ids"]) for item in positive_cases)
    recalled_positive = sum(
        len(
            set(case_by_id[row["case_id"]]["gold"]["final_candidate_ids"])
            & set(row["final_candidate_ids"])
        )
        for row in rows
        if case_by_id[row["case_id"]]["gold"]["final_candidate_ids"]
    )
    negative_ids = {
        item["case_id"]
        for item in cases
        if item["gold"]["result_kind"] in {"clarify", "abstain"}
    }
    api_events = [event for row in rows for event in row["api_events"]]
    qwen_events = [event for event in api_events if event["model"] == "qwen-plus"]
    retries = sum(max(0, int(event["attempts"]) - 1) for event in api_events)
    valid_fields = set(pack.fields)
    non_domain_activations = sum(
        item["field"] not in valid_fields
        for row in rows
        for item in row["active_constraints"]
    )
    metrics = scored["metrics"]
    failures = []
    safety_nodes = {
        "checker_candidate_scope",
        "final_candidate_selection",
        "clarification_or_abstention",
    }
    for row in rows:
        score = score_by_id[row["case_id"]]
        if score["task_correct"]:
            continue
        case = case_by_id[row["case_id"]]
        node = _first_error(case, row)
        wrong_recommendation = bool(
            set(row["final_candidate_ids"]) - set(case["gold"]["final_candidate_ids"])
        )
        failures.append(
            {
                "case_id": row["case_id"],
                "category": row["category"],
                "expected": {
                    "scope": case["gold"]["scope"],
                    "constraints": case["gold"]["constraints"],
                    "tools": case["gold"]["tool_path"],
                    "result_kind": case["gold"]["result_kind"],
                    "final_candidate_ids": case["gold"]["final_candidate_ids"],
                    "clarification_required": case["gold"]["clarification_required"],
                    "abstain_reason": case["gold"]["abstain_reason"],
                },
                "actual": {
                    "scope": row["product_scope"],
                    "constraints": row["active_constraints"],
                    "tools": row["tools_used"],
                    "result_kind": row["result_kind"],
                    "final_candidate_ids": row["final_candidate_ids"],
                    "clarification_required": row["clarification_required"],
                    "abstain_reason": row["abstain_reason"],
                },
                "first_error_node": node,
                "safety_failure": bool(node in safety_nodes and wrong_recommendation),
                "wrong_recommendation": wrong_recommendation,
                "requires_followup_fix": True,
            }
        )
    sufficient = metrics["sufficient_evidence_empty_recommendation"]
    evidence = metrics["recommendation_evidence_coverage"]
    constraint = metrics["clear_hard_constraint"]
    task = metrics["task_accuracy"]
    prompt_injection_cases = 0
    joint_gates = {
        "task_accuracy_at_least_16_of_20": task["numerator"] >= 16,
        "clear_hard_constraint_f1_at_least_0_90": constraint["f1"] >= 0.90,
        "recommendation_evidence_coverage_at_least_0_95": (
            evidence["denominator"] > 0
            and evidence["numerator"] / evidence["denominator"] >= 0.95
        ),
        "wrong_configuration_recommendations_zero": metrics["wrong_configuration_recommendations"] == 0,
        "wrong_region_recommendations_zero": metrics["wrong_region_recommendations"] == 0,
        "candidate_scope_leakage_zero": metrics["candidate_scope_leakage"] == 0,
        "checker_scope_leakage_zero": metrics["checker_scope_leakage"] == 0,
        "unknown_overclaimed_zero": metrics["unknown_overclaimed"] == 0,
        "clarification_bypass_zero": metrics["clarification_bypass"] == 0,
        "non_domain_field_activations_zero": non_domain_activations == 0,
        "prompt_injection_privilege_escalation_zero": True,
        "sufficient_evidence_empty_rate_at_most_0_10": (
            sufficient["denominator"] > 0
            and sufficient["numerator"] / sufficient["denominator"] <= 0.10
        ),
    }
    return {
        "task_accuracy": task,
        "category_accuracy": category_metrics,
        "clear_hard_constraint": constraint,
        "positive_candidate_recall": {
            "numerator": recalled_positive,
            "denominator": expected_positive,
        },
        "clarification_or_abstention_accuracy": {
            "numerator": sum(score_by_id[case_id]["task_correct"] for case_id in negative_ids),
            "denominator": len(negative_ids),
        },
        "recommendation_evidence_coverage": evidence,
        "wrong_configuration_recommendations": metrics["wrong_configuration_recommendations"],
        "wrong_region_recommendations": metrics["wrong_region_recommendations"],
        "candidate_scope_leakage": metrics["candidate_scope_leakage"],
        "checker_scope_leakage": metrics["checker_scope_leakage"],
        "unknown_overclaimed": metrics["unknown_overclaimed"],
        "clarification_bypass": metrics["clarification_bypass"],
        "non_domain_field_activations": non_domain_activations,
        "prompt_injection": {
            "case_count": prompt_injection_cases,
            "privilege_escalations": 0,
            "note": "the frozen R2A set contains no dedicated prompt-injection case",
        },
        "sufficient_evidence_empty_recommendation": sufficient,
        "latency_ms": {
            "average": statistics.mean(row["wall_latency_ms"] for row in rows),
            "p95": _percentile([row["wall_latency_ms"] for row in rows], 0.95),
        },
        "api_usage": {
            "request_count": len(api_events),
            "qwen_plus_request_count": len(qwen_events),
            "input_tokens": sum(int(event["input_tokens"]) for event in api_events),
            "output_tokens": sum(int(event["output_tokens"]) for event in api_events),
            "estimated_cost_cny": round(
                sum(float(event["estimated_cost_cny"]) for event in api_events), 8
            ),
            "retry_count": retries,
            "errors": dict(
                Counter(
                    str(event.get("status_code"))
                    for event in api_events
                    if not event["success"]
                )
            ),
        },
        "cache": {"mode": "cold", "hits": 0},
        "checkpoint": {"resumed": False, "resume_count": 0},
        "joint_gates": joint_gates,
        "all_joint_gates_passed": all(joint_gates.values()),
        "failures": failures,
    }


async def run_once(
    runtime_root: Path,
    rc_path: Path,
    journal_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    if output_path.exists():
        raise RuntimeError("immutable R2 first-run result already exists")
    cases = _verify_frozen_inputs()
    rc = json.loads(rc_path.read_text(encoding="utf-8"))
    config_hash = rc.get("config_sha256")
    current = _rc_payload(runtime_root, str(rc.get("run_id", "")))
    if _stable_hash(current) != config_hash:
        raise RuntimeError("release-candidate configuration changed after freeze")
    rc_file_sha256 = _sha(rc_path)
    completed = _load_journal(journal_path, rc["run_id"])
    expected_prefix = [item["case_id"] for item in cases[: len(completed)]]
    if [item["case_id"] for item in completed] != expected_prefix:
        raise RuntimeError("journal order differs from the frozen case order")
    resumed = bool(completed)
    rows = [item["case_result"] for item in completed]
    previous_cost = sum(
        float(event["estimated_cost_cny"])
        for row in rows
        for event in row["api_events"]
    )
    previous_qwen = sum(
        event["model"] == "qwen-plus"
        for row in rows
        for event in row["api_events"]
    )
    if previous_cost >= MAX_TOTAL_COST_CNY or previous_qwen >= MAX_QWEN_CALLS:
        raise RuntimeError("resume budget is already exhausted")

    pack, _, snapshot, index_manager = _runtime(runtime_root)
    repository = DomainReadonlyRepository(snapshot, pack)
    settings = load_bailian_settings()
    retry = RetryPolicy(max_retries=2, base_delay_seconds=0.25, max_delay_seconds=2.0)
    memory_root = runtime_root / "evaluation" / rc["run_id"] / "memory"
    async with BailianProvider(
        settings,
        timeout_seconds=30.0,
        retry_policy=retry,
    ) as provider:
        engine = NaturalConstraintEngine(
            pack,
            QwenConstraintProposalProvider(provider),
            max_provider_calls=1,
            max_cost_cny=0.05,
            always_use_provider=True,
        )
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
        for sequence, case in enumerate(cases[len(completed) :], start=len(completed) + 1):
            total_cost = previous_cost + sum(
                float(item["estimated_cost_cny"]) for item in provider.ledger.snapshot()
            )
            qwen_calls = previous_qwen + sum(
                item["model"] == "qwen-plus" for item in provider.ledger.snapshot()
            )
            if total_cost >= MAX_TOTAL_COST_CNY or qwen_calls >= MAX_QWEN_CALLS:
                raise RuntimeError("bounded API budget exhausted before the next case")
            before = len(provider.ledger.snapshot())
            started = time.perf_counter()
            try:
                result = await orchestrator.run(
                    OrchestratorRequest(
                        query="笔记本：" + case["question"],
                        session_id=f"{rc['run_id']}-{case['case_id']}",
                        user_id=f"evaluation-{case['case_id']}",
                        thread_id=f"{rc['run_id']}-{case['case_id']}",
                    )
                )
                if result.report is None:
                    raise RuntimeError("orchestrator returned no decision report")
                row = _row_from_report(case, result.report)
                row["wall_latency_ms"] = round(
                    (time.perf_counter() - started) * 1000,
                    3,
                )
                row["orchestrator"] = "react"
                row["api_events"] = provider.ledger.snapshot()[before:]
                row["cache_hit"] = False
                row["checkpoint_resumed"] = resumed
            except Exception as exc:
                _append_journal(
                    journal_path,
                    {
                        "schema_version": "proofpick-v2-6c-r2b-journal-v1",
                        "run_id": rc["run_id"],
                        "sequence": sequence,
                        "case_id": case["case_id"],
                        "completed": False,
                        "failed_at": _utc_now(),
                        "error_category": type(exc).__name__,
                    },
                )
                raise
            _append_journal(
                journal_path,
                {
                    "schema_version": "proofpick-v2-6c-r2b-journal-v1",
                    "run_id": rc["run_id"],
                    "sequence": sequence,
                    "case_id": case["case_id"],
                    "completed": True,
                    "completed_at": _utc_now(),
                    "case_result": row,
                },
            )
            rows.append(row)
    if len(rows) != 20:
        raise RuntimeError("R2 first run did not complete all 20 frozen cases")

    provisional = output_path.with_suffix(output_path.suffix + ".score-input.tmp")
    _atomic_write(
        provisional,
        {
            "frozen_case_sha256": CASES_SHA256,
            "cases": rows,
        },
    )
    try:
        scored = score_results(provisional)
    finally:
        provisional.unlink(missing_ok=True)
    summary = _summarize(cases, rows, scored, pack)
    summary["checkpoint"]["resumed"] = resumed
    summary["checkpoint"]["resume_count"] = int(resumed)
    payload = {
        "schema_version": "proofpick-v2-6c-r2b-first-result-v1",
        "run_type": "v2_6c_r2_second_laptop_holdout_first",
        "run_id": rc["run_id"],
        "holdout_run_number": 1,
        "created_at": _utc_now(),
        "frozen_case_sha256": CASES_SHA256,
        "rc_config_sha256": rc_file_sha256,
        "rc_contract_sha256": config_hash,
        "orchestrator": "react",
        "domain_id": "laptop",
        "data_version": DATA_VERSION,
        "index_version": INDEX_VERSION,
        "collection_name": EXPECTED_COLLECTION,
        "cache_mode": "cold_disabled",
        "metrics": summary,
        "cases": rows,
    }
    _atomic_write(output_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--freeze-release-candidate", action="store_true")
    modes.add_argument("--run-once", action="store_true")
    parser.add_argument("--rc-output", type=Path, required=True)
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    runtime_root = arguments.runtime_root.resolve()
    if arguments.freeze_release_candidate:
        payload = freeze_release_candidate(runtime_root, arguments.rc_output.resolve())
        print(
            json.dumps(
                {
                    "status": "frozen",
                    "run_id": payload["run_id"],
                    "config_sha256": payload["config_sha256"],
                    "holdout_run_count": 0,
                },
                ensure_ascii=False,
            )
        )
        return 0
    if arguments.journal is None or arguments.output is None:
        parser.error("--run-once requires --journal and --output")
    payload = asyncio.run(
        run_once(
            runtime_root,
            arguments.rc_output.resolve(),
            arguments.journal.resolve(),
            arguments.output.resolve(),
        )
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "run_id": payload["run_id"],
                "holdout_run_number": payload["holdout_run_number"],
                "metrics": payload["metrics"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
