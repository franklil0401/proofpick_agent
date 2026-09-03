"""Run the frozen V2-8 Headphone engineering set exactly once."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smartbuy.agent import DomainDecisionAgent
from smartbuy.config import load_bailian_settings
from smartbuy.constraint_proposals import ClarificationState
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.memory import DomainPreferenceMemoryStore
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.providers import BailianProvider
from smartbuy.providers.bailian import BailianError
from smartbuy.retrieval.domain_index import DomainIndexManager
from smartbuy.tools import ToolResult
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainKBSearchTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)


ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "smartbuy" / "eval" / "v2_8_headphone_engineering_cases.jsonl"
CASES_SHA256 = "851129b3eacac9b24bdbda675af5233912495c4d0d55bf8e4995e964de0b358d"
POLICY = ROOT / "smartbuy" / "eval" / "v2_8_headphone_engineering_policy.json"
DOMAIN = ROOT / "smartbuy" / "domain_packs" / "headphone"
INDEX_VERSION = "headphone-governed-2026-09-03-v1-embedding1024-v1"
RC_CONFIG = ROOT / "smartbuy" / "eval" / "results" / "v2_8_headphone_engineering_rc.json"
RC_FILES = (
    "smartbuy/agent/domain_agent.py",
    "smartbuy/constraint_proposals/engine.py",
    "smartbuy/domain_packs/headphone/manifest.json",
    "smartbuy/domain_packs/headphone/fields.json",
    "smartbuy/domain_packs/headphone/policies.json",
    "smartbuy/product_packs/examples/headphone-v1/pack.json",
    "smartbuy/eval/v2_8_headphone_engineering_cases.jsonl",
    "smartbuy/eval/v2_8_headphone_engineering_policy.json",
    "smartbuy/eval/v2_8_headphone_engineering_runner.py",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _p95(values: list[float]) -> float:
    return sorted(values)[max(0, math.ceil(len(values) * 0.95) - 1)]


def _git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


class FaultInjectingProvider:
    """Delegates real calls and injects only the frozen reranker failure case."""

    def __init__(self, delegate: BailianProvider) -> None:
        self.delegate = delegate
        self.fail_rerank = False

    @property
    def ledger(self):
        return self.delegate.ledger

    async def embed(self, texts):
        return await self.delegate.embed(texts)

    async def rerank(self, query, documents, *, top_n, instruct=None):
        if self.fail_rerank:
            raise BailianError("frozen_reranker_failure_fixture")
        return await self.delegate.rerank(query, documents, top_n=top_n, instruct=instruct)


class FailingChecker:
    VERSION = "proofpick-frozen-checker-failure-fixture"

    @staticmethod
    def run(*_args, **_kwargs) -> ToolResult:
        return ToolResult(
            tool="domain_constraint_checker", status="failed", data={},
            summary="受控 Checker 故障；安全关闭。", error_code="checker_unavailable",
        )


def _release_candidate(runtime_root: Path) -> dict[str, Any]:
    pack = DomainPackLoader().load(DOMAIN)
    manager = DomainProductPackManager(runtime_root / "data", domain_pack_path=DOMAIN)
    data = manager.current()
    index = DomainIndexManager(
        runtime_root / "index", data_manager=manager, domain_id=pack.domain_id,
        domain_pack_version=pack.version,
    ).current()
    payload = {
        "schema_version": "proofpick-v2-8-headphone-engineering-rc-v1",
        "production_commit": _git_head(), "case_sha256": CASES_SHA256,
        "scoring_policy_sha256": _sha(POLICY),
        "domain_pack_version": pack.version, "domain_pack_fingerprint": pack.fingerprint,
        "data_version": data.data_version, "data_manifest_hash": data.manifest_hash,
        "index_version": index.index_version, "index_manifest_hash": index.manifest_hash,
        "collection_name": index.collection_name,
        "llm_model": "qwen-plus", "embedding_model": "text-embedding-v4",
        "embedding_dimensions": 1024, "reranker_model": "qwen3-rerank",
        "temperature": 0, "max_agent_steps": 8, "max_tool_calls": 12,
        "orchestrator": "react", "cache": "cold", "source_search": "disabled",
        "files": {relative: _sha(ROOT / relative) for relative in RC_FILES},
    }
    payload["config_hash"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return payload


def _load_cases() -> list[dict[str, Any]]:
    if _sha(CASES) != CASES_SHA256:
        raise RuntimeError("frozen Headphone engineering set changed")
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines()]
    if len(cases) != 30 or any(item["frozen_status"] != "frozen_unrun" for item in cases):
        raise RuntimeError("frozen Headphone engineering cardinality/status changed")
    return cases


def _score(case: dict[str, Any], report: Any) -> dict[str, Any]:
    expected = set(case["expected_product_ids"])
    actual = set(report.recommended_model_ids)
    evidence_ids = {
        item.model_id for item in report.evidence
        if item.field in set(case["gold_fields"])
    }
    kind = case["expected_kind"]
    if kind == "eligible":
        task_correct = actual == expected
    elif kind == "referenced":
        task_correct = expected <= evidence_ids and not actual
    elif kind == "degraded_referenced":
        task_correct = expected <= evidence_ids and not actual and bool(report.degraded_states)
    elif kind == "clarify":
        task_correct = report.clarification_state == ClarificationState.PENDING and not actual
    elif kind == "safety_blocked":
        task_correct = report.abstained and not actual and report.constraint_verification.degraded
    else:
        task_correct = report.abstained and not actual
    active = {
        item.field for item in report.constraint_set.active(hard_only=True, supported_only=True)
    }
    gold_fields = set(case["gold_fields"] if case["constraints"] else [])
    tp, fp, fn = len(active & gold_fields), len(active - gold_fields), len(gold_fields - active)
    eligible = set(report.constraint_verification.eligible_model_ids)
    scope = set(report.product_scope.product_ids)
    report_ids = {item.model_id for item in report.candidates}
    evidence_den = len(actual) * len(gold_fields)
    evidence_num = len({
        (item.model_id, item.field) for item in report.evidence
        if item.model_id in actual and item.field in gold_fields
    })
    subjective = {"comfort_observation", "sound_signature", "call_quality_observation"}
    return {
        "case_id": case["case_id"], "category": case["category"], "expected_kind": kind,
        "expected_product_ids": sorted(expected), "recommended_product_ids": sorted(actual),
        "referenced_product_ids": sorted(evidence_ids), "task_correct": task_correct,
        "field_tp": tp, "field_fp": fp, "field_fn": fn,
        "active_hard_fields": sorted(active), "tools_used": report.tools_used,
        "tool_path_correct": set(case["required_tools"]) <= set(report.tools_used),
        "clarification_state": report.clarification_state.value,
        "abstained": report.abstained, "result_status": report.usage.get("result_status"),
        "recommendation_evidence_numerator": evidence_num,
        "recommendation_evidence_denominator": evidence_den,
        "explicit_violation_recommendations": len(actual - expected) if kind == "eligible" else 0,
        "subjective_hard_fact_overrides": len(active & subjective),
        "wrong_configuration_recommendations": len(actual - scope),
        "wrong_region_recommendations": len(actual - scope),
        "scope_leakage": len(actual - scope), "checker_leakage": len(actual - eligible),
        "report_leakage": len(report_ids - scope),
        "unknown_overclaims": sum(
            item.overall_status.value == "matched" and bool(item.unknown_fields)
            for item in report.candidates
        ),
        "clarification_bypasses": int(kind == "clarify" and bool(actual)),
        "latency_ms": report.latency_ms, "degraded_states": report.degraded_states,
        "report": report.model_dump(mode="json"),
    }


async def run(runtime_root: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise RuntimeError("first-run output already exists and is immutable")
    cases = _load_cases()
    current_rc = _release_candidate(runtime_root)
    if not RC_CONFIG.exists():
        raise RuntimeError("release candidate must be frozen before the run")
    frozen_rc = json.loads(RC_CONFIG.read_text(encoding="utf-8"))
    if frozen_rc["config_hash"] != current_rc["config_hash"]:
        raise RuntimeError("code/config changed after RC freeze")
    pack = DomainPackLoader().load(DOMAIN)
    data_manager = DomainProductPackManager(runtime_root / "data", domain_pack_path=DOMAIN)
    snapshot = data_manager.current()
    index_manager = DomainIndexManager(
        runtime_root / "index", data_manager=data_manager, domain_id=pack.domain_id,
        domain_pack_version=pack.version,
    )
    if index_manager.current().index_version != INDEX_VERSION:
        raise RuntimeError("Headphone index version differs from frozen policy")
    repository = DomainReadonlyRepository(snapshot, pack)
    rows = []
    async with BailianProvider(load_bailian_settings()) as real_provider:
        provider = FaultInjectingProvider(real_provider)
        normal_checker = DomainConstraintCheckerTool(repository)
        agent = DomainDecisionAgent(
            pack, repository, DomainProductQueryTool(repository),
            DomainEvidenceCheckTool(repository), normal_checker,
            NaturalConstraintEngine(pack),
            DomainPreferenceMemoryStore(runtime_root / "memory", pack),
            kb_search=DomainKBSearchTool(index_manager, provider),
        )
        for case in cases:
            started = time.perf_counter()
            provider.fail_rerank = case["fault"] == "reranker_failure"
            agent.checker = FailingChecker() if case["fault"] == "checker_failure" else normal_checker
            report = await agent.run(
                "耳机：" + case["question"],
                session_id=case["case_id"], user_id="v2-8-evaluation",
                ranking_scenario=case["ranking_scenario"], ranking_what_if=bool(case["ranking_scenario"]),
            )
            row = _score(case, report)
            row["wall_latency_ms"] = (time.perf_counter() - started) * 1000
            rows.append(row)
        usage = real_provider.ledger.summary()
    tp, fp, fn = (
        sum(item[key] for item in rows) for key in ("field_tp", "field_fp", "field_fn")
    )
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    evidence_num = sum(item["recommendation_evidence_numerator"] for item in rows)
    evidence_den = sum(item["recommendation_evidence_denominator"] for item in rows)
    negatives = [item for item in rows if item["expected_kind"] in {"abstain", "clarify", "safety_blocked"}]
    metrics = {
        "task_accuracy": {"numerator": sum(item["task_correct"] for item in rows), "denominator": 30},
        "field_counts": {"tp": tp, "fp": fp, "fn": fn},
        "field_precision": precision, "field_recall": recall,
        "field_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
        "recommendation_evidence_coverage": {"numerator": evidence_num, "denominator": evidence_den},
        "negative_rejection": {"numerator": sum(item["task_correct"] for item in negatives), "denominator": len(negatives)},
        "tool_path": {"numerator": sum(item["tool_path_correct"] for item in rows), "denominator": 30},
        "average_latency_ms": statistics.mean(item["wall_latency_ms"] for item in rows),
        "p95_latency_ms": _p95([item["wall_latency_ms"] for item in rows]),
    }
    for key in (
        "explicit_violation_recommendations", "subjective_hard_fact_overrides",
        "wrong_configuration_recommendations", "wrong_region_recommendations",
        "scope_leakage", "checker_leakage", "report_leakage", "unknown_overclaims",
        "clarification_bypasses",
    ):
        metrics[key] = sum(item[key] for item in rows)
    payload = {
        "run_type": "v2_8_headphone_engineering_first", "run_number": 1,
        "run_id": f"v2-8-headphone-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "created_at": datetime.now(UTC).isoformat(), "case_sha256": CASES_SHA256,
        "rc_config_sha256": current_rc["config_hash"], "metrics": metrics,
        "api_usage": usage, "cases": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def freeze(runtime_root: Path) -> dict[str, Any]:
    if RC_CONFIG.exists():
        raise RuntimeError("release candidate already exists")
    payload = {**_release_candidate(runtime_root), "frozen_at": datetime.now(UTC).isoformat()}
    RC_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    RC_CONFIG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--freeze-release-candidate", action="store_true")
    args = parser.parse_args()
    if args.freeze_release_candidate:
        payload = freeze(args.runtime_root)
        print(json.dumps({"status": "frozen", "config_hash": payload["config_hash"]}))
        return 0
    if args.output is None:
        parser.error("--output is required")
    result = asyncio.run(run(args.runtime_root, args.output))
    print(json.dumps({"status": "completed", "run_id": result["run_id"], "metrics": result["metrics"], "api_usage": result["api_usage"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
