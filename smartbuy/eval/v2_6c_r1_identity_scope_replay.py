"""Offline replay of the 20 exposed V2-6C cases after identity-scope repair.

This runner deliberately reuses saved, exposed constraint resolutions. It does
not call an LLM, Embedding, Reranker, Web Search, or any other paid provider.
The ten specialist cases remain unrun and are only classified as exposed by
the repository audit.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smartbuy.agent import DomainDecisionAgent
from smartbuy.constraint_proposals import ClarificationState, ConstraintResolution, ProposalStatus
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.eval.v2_6c_laptop_agent_runner import CASES_SHA256, _percentile, _score
from smartbuy.memory import DomainPreferenceMemoryStore
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.tools.base import ToolResult
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)


ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "smartbuy" / "eval" / "v2_6a_laptop_cases.jsonl"
POLICY = ROOT / "smartbuy" / "eval" / "v2_6c_laptop_scoring_policy.json"
DOMAIN_PACK = ROOT / "smartbuy" / "domain_packs" / "laptop"
PRODUCT_PACK = ROOT / "smartbuy" / "product_packs" / "examples" / "laptop-v1" / "pack.json"
REGRESSION_SOURCE = ROOT / "smartbuy" / "eval" / "results" / "v2_6c_laptop_regression_after_fix4.json"
HOLDOUT_SOURCE = ROOT / "smartbuy" / "eval" / "results" / "v2_6c_laptop_holdout_first.json"
INDEX_VERSION = "laptop-governed-2026-09-02-v1-embedding1024-v1"
EXPOSED_SPLITS = {"regression", "holdout"}
UNRUN_EXPOSED_SPLITS = {"hard_negative", "clarification"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OfflineScopedKBSearch:
    """No-network KB trace adapter; governed evidence still comes from SQLite."""

    index_version = INDEX_VERSION

    def __init__(self, repository: DomainReadonlyRepository) -> None:
        self.repository = repository

    async def run(
        self,
        query: str,
        *,
        product_id: str | None = None,
        scope: Any,
        vector_top_k: int = 12,
        top_k: int = 5,
        **_: Any,
    ) -> ToolResult:
        del query, vector_top_k
        scope.assert_runtime(
            domain_id=self.repository.domain_pack.domain_id,
            data_version=self.repository.snapshot.data_version,
            index_version=self.index_version,
        )
        if product_id is not None and not scope.permits(product_id):
            return ToolResult(
                tool="domain_kb_search",
                status="failed",
                degraded=True,
                summary="离线回归拒绝范围外商品",
                error_code="kb_scope_mismatch",
            )
        products = self.repository.load()
        targets = [product_id] if product_id else list(scope.product_ids)
        hits = []
        for candidate_id in targets:
            product = products[candidate_id]
            evidence = product["evidence"][0] if product["evidence"] else None
            hits.append(
                {
                    "product_id": candidate_id,
                    "configuration_id": product["attributes"].get("configuration_id"),
                    "region": product["region"],
                    "evidence_id": evidence["evidence_id"] if evidence else None,
                    "source_id": evidence["source_id"] if evidence else None,
                }
            )
            if len(hits) >= top_k:
                break
        return ToolResult(
            tool="domain_kb_search",
            status="success",
            data={
                "index_version": self.index_version,
                "data_version": self.repository.snapshot.data_version,
                "scope_fingerprint": scope.fingerprint,
                "hits": hits,
                "offline_replay": True,
            },
            summary=f"离线范围回归返回 {len(hits)} 个治理身份",
        )


def _historical_resolution(report: dict[str, Any]) -> ConstraintResolution:
    proposals = report.get("constraint_proposals", [])
    pending = [
        item["proposal_id"]
        for item in proposals
        if item["status"] in {ProposalStatus.AMBIGUOUS.value, ProposalStatus.NEEDS_CONFIRMATION.value}
    ]
    state = ClarificationState(report.get("clarification_state", "not_required"))
    question = None
    if state == ClarificationState.PENDING:
        questions = report.get("pending_questions", [])
        question = questions[0] if questions else "请确认待定约束。"
    return ConstraintResolution.model_validate(
        {
            "query": report["request_summary"],
            "source_turn": 1,
            "proposals": proposals,
            "constraint_set": report.get("constraint_set", {}),
            "clarification_state": state.value,
            "clarification_question": question,
            "pending_proposal_ids": pending if state == ClarificationState.PENDING else [],
            "diff": report.get("constraint_diff", []),
            "provider_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_ms": 0,
            "estimated_cost_cny": 0,
        }
    )


def _case_map(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {item["case_id"]: item for item in payload["cases"]}


def _identity_audit(report: Any) -> dict[str, Any]:
    assert report.product_scope is not None
    scope = report.product_scope
    candidate_ids = {item.product_id for item in report.candidates}
    evidence_ids = {item.product_id for item in report.evidence}
    scope_ids = set(scope.product_ids)
    checker_ids = set(report.constraint_verification.candidate_pool_model_ids)
    identity_rows = [*report.candidates, *report.evidence]
    identity_complete = all(
        item.product_id == item.model_id
        and item.domain_id == scope.domain_id
        and item.data_version == scope.data_version
        and item.configuration_id in scope.configuration_ids
        and item.region in scope.regions
        for item in identity_rows
    )
    return {
        "scope_fingerprint": scope.fingerprint,
        "scope_type": scope.scope_type.value,
        "scope_product_ids": scope.product_ids,
        "scope_configuration_ids": scope.configuration_ids,
        "scope_regions": scope.regions,
        "report_out_of_scope_count": len((candidate_ids | evidence_ids) - scope_ids),
        "checker_out_of_scope_count": len(checker_ids - scope_ids),
        "identity_envelope_complete": identity_complete,
    }


async def run(output: Path) -> dict[str, Any]:
    if output.exists():
        raise RuntimeError("offline replay output already exists; results are immutable")
    if _sha(CASES) != CASES_SHA256:
        raise RuntimeError("frozen Laptop E2E cases changed")
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines()]
    exposed = [item for item in cases if item["split"] in EXPOSED_SPLITS]
    unrun_exposed = [item["case_id"] for item in cases if item["split"] in UNRUN_EXPOSED_SPLITS]
    if len(exposed) != 20 or len(unrun_exposed) != 10:
        raise RuntimeError("the frozen 20/10 audit partition changed")
    historical = {**_case_map(REGRESSION_SOURCE), **_case_map(HOLDOUT_SOURCE)}
    policy = json.loads(POLICY.read_text(encoding="utf-8"))["cases"]
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="proofpick-v2-6c-r1-") as temporary:
        runtime = Path(temporary)
        pack = DomainPackLoader().load(DOMAIN_PACK)
        manager = DomainProductPackManager(runtime / "data", domain_pack_path=DOMAIN_PACK)
        snapshot = manager.publish(manager.stage(PRODUCT_PACK).data_version)
        repository = DomainReadonlyRepository(snapshot, pack)
        agent = DomainDecisionAgent(
            pack,
            repository,
            DomainProductQueryTool(repository),
            DomainEvidenceCheckTool(repository),
            DomainConstraintCheckerTool(repository),
            NaturalConstraintEngine(pack),
            DomainPreferenceMemoryStore(runtime / "memory", pack),
            kb_search=OfflineScopedKBSearch(repository),
        )
        for case in exposed:
            started = time.perf_counter()
            source = historical[case["case_id"]]["report"]
            report = await agent.run(
                source["request_summary"],
                session_id=f"v2-6c-r1-{case['case_id']}",
                user_id="offline-evaluation",
                constraint_resolution=_historical_resolution(source),
            )
            row = _score(case, report, policy)
            row["wall_latency_ms"] = (time.perf_counter() - started) * 1000
            row["identity_audit"] = _identity_audit(report)
            rows.append(row)
    split_metrics = {}
    for split in ("regression", "holdout"):
        selected = [item for item in rows if item["split"] == split]
        split_metrics[split] = {
            "classification": "exposed_regression",
            "task_accuracy": {
                "numerator": sum(item["task_correct"] for item in selected),
                "denominator": len(selected),
            },
        }
    evidence_numerator = sum(item["recommendation_evidence_covered"] for item in rows)
    evidence_denominator = sum(item["recommendation_evidence_denominator"] for item in rows)
    field_tp = sum(item["field_tp"] for item in rows)
    field_fp = sum(item["field_fp"] for item in rows)
    field_fn = sum(item["field_fn"] for item in rows)
    field_precision = field_tp / (field_tp + field_fp) if field_tp + field_fp else 1.0
    field_recall = field_tp / (field_tp + field_fn) if field_tp + field_fn else 1.0
    field_f1 = (
        2 * field_precision * field_recall / (field_precision + field_recall)
        if field_precision + field_recall else 0.0
    )
    eligible_cases = [
        item for item in rows if policy[item["case_id"]]["result_kind"] == "eligible"
    ]
    result = {
        "schema_version": "proofpick-v2-6c-r1-offline-replay-v1",
        "run_type": "v2_6c_r1_exposed_regression_offline",
        "created_at": datetime.now(UTC).isoformat(),
        "evaluation_boundary": {
            "run_case_ids": [item["case_id"] for item in exposed],
            "unrun_exposed_specialist_case_ids": unrun_exposed,
            "unseen_holdout_claim": False,
            "paid_provider_calls": 0,
        },
        "frozen_inputs": {
            "case_file_sha256": _sha(CASES),
            "scoring_policy_sha256": _sha(POLICY),
            "regression_source_sha256": _sha(REGRESSION_SOURCE),
            "holdout_first_source_sha256": _sha(HOLDOUT_SOURCE),
        },
        "domain_id": "laptop",
        "data_version": "laptop-governed-2026-09-02-v1",
        "index_version": INDEX_VERSION,
        "metrics": {
            "task_accuracy": {
                "numerator": sum(item["task_correct"] for item in rows),
                "denominator": len(rows),
            },
            "by_split": split_metrics,
            "recommendation_evidence_coverage": {
                "numerator": evidence_numerator,
                "denominator": evidence_denominator,
            },
            "clear_hard_constraint_fields": {
                "tp": field_tp,
                "fp": field_fp,
                "fn": field_fn,
                "precision": field_precision,
                "recall": field_recall,
                "f1": field_f1,
            },
            "sufficient_evidence_empty_recommendation": {
                "numerator": sum(not item["recommended_ids"] for item in eligible_cases),
                "denominator": len(eligible_cases),
            },
            "unknown_overclaimed": sum(item["unknown_overclaimed"] for item in rows),
            "checker_boundary_violations": sum(
                item["checker_boundary_violations"] for item in rows
            ),
            "scope_leakage_count": sum(
                item["identity_audit"]["report_out_of_scope_count"]
                + item["identity_audit"]["checker_out_of_scope_count"]
                for item in rows
            ),
            "identity_envelope_complete": {
                "numerator": sum(item["identity_audit"]["identity_envelope_complete"] for item in rows),
                "denominator": len(rows),
            },
            "average_latency_ms": statistics.mean(item["wall_latency_ms"] for item in rows),
            "p95_latency_ms": _percentile([item["wall_latency_ms"] for item in rows], 0.95),
        },
        "api_usage": {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_cny": 0,
        },
        "cases": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run(args.output))
    print(json.dumps({"status": "completed", "metrics": result["metrics"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
