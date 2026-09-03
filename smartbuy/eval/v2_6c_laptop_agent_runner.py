"""Immutable V2-6C Laptop Agent runner with Regression-before-Holdout discipline."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smartbuy.agent import DomainDecisionAgent
from smartbuy.config import load_bailian_settings
from smartbuy.constraint_proposals import ProposalStatus
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.constraint_proposals.provider import QwenConstraintProposalProvider
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.memory import DomainPreferenceMemoryStore
from smartbuy.orchestration.contracts import OrchestratorRequest
from smartbuy.orchestration.react_adapter import ReactOrchestrator
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.providers import BailianProvider
from smartbuy.retrieval.domain_index import DomainIndexManager
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainKBSearchTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)


ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "smartbuy" / "eval" / "v2_6a_laptop_cases.jsonl"
CASES_SHA256 = "3dfcc0f442bda2b6b4d2e96814a8973b415b3d8c8b9b33235924982fa1758d34"
POLICY = ROOT / "smartbuy" / "eval" / "v2_6c_laptop_scoring_policy.json"
DOMAIN_PACK = ROOT / "smartbuy" / "domain_packs" / "laptop"
INDEX_VERSION = "laptop-governed-2026-09-02-v1-embedding1024-v1"
RC_CONFIG = ROOT / "smartbuy" / "eval" / "results" / "v2_6c_release_candidate.json"
RC_FILES = (
    "smartbuy/agent/domain_agent.py",
    "smartbuy/agent/domain_gateway.py",
    "smartbuy/domain_packs/category_registry.json",
    "smartbuy/domain_packs/category_router.py",
    "smartbuy/constraint_proposals/engine.py",
    "smartbuy/constraint_proposals/provider.py",
    "smartbuy/domain_packs/laptop/manifest.json",
    "smartbuy/domain_packs/laptop/fields.json",
    "smartbuy/domain_packs/laptop/policies.json",
    "smartbuy/product_packs/examples/laptop-v1/pack.json",
    "smartbuy/eval/v2_6a_laptop_cases.jsonl",
    "smartbuy/eval/v2_6c_laptop_scoring_policy.json",
    "smartbuy/eval/v2_6c_laptop_agent_runner.py",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))]


def release_candidate_payload(index_manifest_hash: str) -> dict[str, Any]:
    files = {relative: _sha(ROOT / relative) for relative in RC_FILES}
    payload = {
        "schema_version": "proofpick-v2-6c-rc-v1",
        "case_sha256": CASES_SHA256,
        "scoring_policy_sha256": _sha(POLICY),
        "domain_id": "laptop",
        "domain_pack_version": "1.0.0",
        "data_version": "laptop-governed-2026-09-02-v1",
        "index_version": INDEX_VERSION,
        "index_manifest_hash": index_manifest_hash,
        "orchestrator": "react",
        "max_steps": 8,
        "max_tool_calls": 12,
        "temperature": 0,
        "cache": "cold",
        "files": files,
    }
    payload["config_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return payload


def _load_cases(split: str) -> list[dict[str, Any]]:
    if _sha(CASES) != CASES_SHA256:
        raise RuntimeError("frozen Laptop E2E cases changed")
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines()]
    selected = [item for item in cases if item["split"] == split]
    if split == "specialists":
        selected = [item for item in cases if item["split"] in {"hard_negative", "clarification"}]
    expected = {"regression": 10, "holdout": 10, "specialists": 10}[split]
    if len(selected) != expected:
        raise RuntimeError("frozen split cardinality changed")
    return selected


def _score(case: dict[str, Any], report: Any, policy: dict[str, Any]) -> dict[str, Any]:
    spec = policy[case["case_id"]]
    expected = set(spec["expected_ids"])
    referenced = {
        item.model_id for item in report.candidates
        if any(field.evidence for field in item.fields)
    }
    active_fields = {
        item.field
        for item in report.constraint_set.active(hard_only=True, supported_only=True)
        if item.provenance.value != "system_default"
    }
    proposal_fields = {
        item.field for item in report.constraint_proposals
        if item.status != ProposalStatus.INVALID
    }
    kind = spec["result_kind"]
    if kind == "eligible":
        task_correct = set(report.recommended_model_ids) == expected
    elif kind == "referenced":
        task_correct = referenced == expected and not report.recommended_model_ids
    elif kind == "abstain":
        task_correct = report.abstained and not report.recommended_model_ids
    elif kind == "clarify":
        task_correct = report.clarification_state.value == "pending" and not report.recommended_model_ids
    else:
        task_correct = set(case["gold_fields"]) <= (active_fields | proposal_fields)
    if case["category"] in {"structured_filter", "natural_constraint"}:
        actual_for_fields = active_fields | {
            item.field for item in report.constraint_proposals
            if item.action.value == "cancel" and item.status != ProposalStatus.INVALID
        }
    else:
        actual_for_fields = set(case["gold_fields"])
    gold_fields = set(case["gold_fields"])
    tp = len(actual_for_fields & gold_fields)
    fp = len(actual_for_fields - gold_fields)
    fn = len(gold_fields - actual_for_fields)
    required_tools = (
        {"domain_product_query", "domain_evidence_check", "domain_constraint_checker"}
        if kind == "eligible" else
        {"domain_kb_search", "domain_evidence_check"} if kind == "referenced" else set()
    )
    tools = set(report.tools_used)
    recommendation_refs = [
        item for item in report.evidence if item.model_id in report.recommended_model_ids
        and item.field in gold_fields
    ]
    coverage_denominator = len(report.recommended_model_ids) * len(gold_fields)
    covered = len({(item.model_id, item.field) for item in recommendation_refs})
    return {
        "case_id": case["case_id"], "split": case["split"], "category": case["category"],
        "expected_ids": sorted(expected), "recommended_ids": report.recommended_model_ids,
        "referenced_ids": sorted(referenced), "task_correct": task_correct,
        "abstained": report.abstained, "active_fields": sorted(active_fields),
        "proposal_fields": sorted(proposal_fields), "field_tp": tp, "field_fp": fp, "field_fn": fn,
        "tool_selection_correct": required_tools <= tools,
        "tools_used": report.tools_used, "candidate_pool_size": len(report.constraint_verification.candidate_pool_model_ids),
        "eligible_ids": report.constraint_verification.eligible_model_ids,
        "recommendation_evidence_covered": covered,
        "recommendation_evidence_denominator": coverage_denominator,
        "unknown_overclaimed": sum(
            item.overall_status.value == "matched" and bool(item.unknown_fields)
            for item in report.candidates
        ),
        "checker_boundary_violations": len(
            set(report.recommended_model_ids) - set(report.constraint_verification.eligible_model_ids)
        ),
        "provider_calls": report.usage.get("provider_calls", 0),
        "input_tokens": report.usage.get("input_tokens", 0),
        "output_tokens": report.usage.get("output_tokens", 0),
        "estimated_cost_cny": report.usage.get("estimated_cost_cny", 0),
        "latency_ms": report.latency_ms,
        "degraded_states": report.degraded_states,
        "report": report.model_dump(mode="json"),
    }


async def run(split: str, runtime_root: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise RuntimeError("evaluation output already exists; historical runs are immutable")
    cases = _load_cases(split)
    policy_payload = json.loads(POLICY.read_text(encoding="utf-8"))
    if policy_payload.get("frozen_case_sha256") != CASES_SHA256:
        raise RuntimeError("scoring policy targets a different frozen set")
    pack = DomainPackLoader().load(DOMAIN_PACK)
    data_manager = DomainProductPackManager(runtime_root / "data", domain_pack_path=DOMAIN_PACK)
    snapshot = data_manager.current()
    index_manager = DomainIndexManager(
        runtime_root / "index", data_manager=data_manager, domain_id=pack.domain_id,
        domain_pack_version=pack.version,
    )
    index = index_manager.current()
    if index.index_version != INDEX_VERSION or index.data_version != snapshot.data_version:
        raise RuntimeError("Laptop Data/Index release contract mismatch")
    current_rc = release_candidate_payload(index.manifest_hash)
    if split == "holdout":
        if not RC_CONFIG.exists():
            raise RuntimeError("release candidate must be frozen before Holdout")
        frozen_rc = json.loads(RC_CONFIG.read_text(encoding="utf-8"))
        if frozen_rc.get("config_hash") != current_rc["config_hash"]:
            raise RuntimeError("code/config changed after release candidate freeze")
    repository = DomainReadonlyRepository(snapshot, pack)
    settings = load_bailian_settings()
    rows = []
    async with BailianProvider(settings) as provider:
        engine = NaturalConstraintEngine(
            pack, QwenConstraintProposalProvider(provider), max_provider_calls=1,
            max_cost_cny=0.05, always_use_provider=True,
        )
        agent = DomainDecisionAgent(
            pack, repository, DomainProductQueryTool(repository),
            DomainEvidenceCheckTool(repository), DomainConstraintCheckerTool(repository),
            engine, DomainPreferenceMemoryStore(runtime_root / "memory", pack),
            kb_search=DomainKBSearchTool(index_manager, provider),
        )
        orchestrator = ReactOrchestrator(agent)
        for case in cases:
            started = time.perf_counter()
            result = await orchestrator.run(OrchestratorRequest(
                query="笔记本：" + case["question"],
                session_id=f"v2-6c-{case['case_id']}", user_id="evaluation",
                thread_id=f"v2-6c-{case['case_id']}",
            ))
            assert result.report is not None
            row = _score(case, result.report, policy_payload["cases"])
            row["wall_latency_ms"] = (time.perf_counter() - started) * 1000
            rows.append(row)
        ledger = provider.ledger.summary()
    tp = sum(item["field_tp"] for item in rows)
    fp = sum(item["field_fp"] for item in rows)
    fn = sum(item["field_fn"] for item in rows)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    evidence_num = sum(item["recommendation_evidence_covered"] for item in rows)
    evidence_den = sum(item["recommendation_evidence_denominator"] for item in rows)
    result = {
        "run_type": f"v2_6c_laptop_{split}_first",
        "created_at": datetime.now(UTC).isoformat(),
        "split": split, "holdout_run_number": 1 if split == "holdout" else 0,
        "case_file_sha256": CASES_SHA256, "scoring_policy_sha256": _sha(POLICY),
        "release_candidate_hash": current_rc["config_hash"] if split == "holdout" else None,
        "domain_id": "laptop", "domain_pack_version": pack.version,
        "data_version": snapshot.data_version, "index_version": index.index_version,
        "collection_name": index.collection_name, "cache_mode": "cold",
        "metrics": {
            "task_accuracy": {"numerator": sum(item["task_correct"] for item in rows), "denominator": len(rows)},
            "field_precision": precision, "field_recall": recall,
            "field_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
            "tool_selection": {"numerator": sum(item["tool_selection_correct"] for item in rows), "denominator": len(rows)},
            "recommendation_evidence_coverage": {"numerator": evidence_num, "denominator": evidence_den},
            "checker_boundary_violations": sum(item["checker_boundary_violations"] for item in rows),
            "unknown_overclaimed": sum(item["unknown_overclaimed"] for item in rows),
            "average_latency_ms": statistics.mean(item["wall_latency_ms"] for item in rows),
            "p95_latency_ms": _percentile([item["wall_latency_ms"] for item in rows], 0.95),
            "rule_only_cases": sum(item["provider_calls"] == 0 for item in rows),
            "qwen_fallback_cases": sum(item["provider_calls"] == 1 for item in rows),
        },
        "api_usage": ledger,
        "cases": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def write_release_candidate(runtime_root: Path) -> dict[str, Any]:
    if RC_CONFIG.exists():
        raise RuntimeError("release candidate config already exists")
    pack = DomainPackLoader().load(DOMAIN_PACK)
    data_manager = DomainProductPackManager(runtime_root / "data", domain_pack_path=DOMAIN_PACK)
    index = DomainIndexManager(
        runtime_root / "index", data_manager=data_manager, domain_id=pack.domain_id,
        domain_pack_version=pack.version,
    ).current()
    payload = {**release_candidate_payload(index.manifest_hash), "frozen_at": datetime.now(UTC).isoformat()}
    RC_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    RC_CONFIG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--split", choices=["regression", "holdout", "specialists"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--freeze-release-candidate", action="store_true")
    args = parser.parse_args()
    if args.freeze_release_candidate:
        payload = write_release_candidate(args.runtime_root)
        print(json.dumps({"status": "frozen", "config_hash": payload["config_hash"]}))
        return 0
    if args.split is None or args.output is None:
        parser.error("--split and --output are required for an evaluation run")
    result = asyncio.run(run(args.split, args.runtime_root, args.output))
    print(json.dumps({"status": "completed", "metrics": result["metrics"], "api_usage": result["api_usage"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
