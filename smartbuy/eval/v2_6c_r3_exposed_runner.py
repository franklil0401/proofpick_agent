"""Offline runner for all 50 exposed Laptop tasks.

This runner never imports a cloud provider.  It preserves the two historical
scoring contracts and reports their metrics separately before aggregating
compatible counters.
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
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.decision_core.canonical import CanonicalValueNormalizer
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.eval.v2_6c_laptop_agent_runner import _score as score_original
from smartbuy.eval.v2_6c_r2_laptop_runner import _first_error, _row_from_report
from smartbuy.eval.v2_6c_r2_laptop_scorer import score_results as score_r2
from smartbuy.memory import DomainPreferenceMemoryStore
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.tools import ToolResult
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)


ROOT = Path(__file__).resolve().parents[2]
DOMAIN_PACK = ROOT / "smartbuy" / "domain_packs" / "laptop"
PRODUCT_PACK = ROOT / "smartbuy" / "product_packs" / "examples" / "laptop-v1" / "pack.json"
ORIGINAL_CASES = ROOT / "smartbuy" / "eval" / "v2_6a_laptop_cases.jsonl"
ORIGINAL_POLICY = ROOT / "smartbuy" / "eval" / "v2_6c_laptop_scoring_policy.json"
R2_CASES = ROOT / "smartbuy" / "eval" / "v2_6c_r2_laptop_holdout.jsonl"
R2_SHA256 = "dd17cf4a4bf794c77cc75b5406f9e603effc7be4e63f9e9b215a9d4d8ea9e24f"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _is_subsequence(required: list[str], actual: list[str]) -> bool:
    position = 0
    for item in actual:
        if position < len(required) and required[position] == item:
            position += 1
    return position == len(required)


def _constraint_signature(pack: Any, item: dict[str, Any]) -> tuple[str, str, str]:
    field = pack.canonical_field(str(item["field"]))
    operator = str(item["operator"])
    value = item.get("normalized_value", item.get("value"))
    values = value if operator in {"in", "not_in", "range"} else [value]
    stable = [
        CanonicalValueNormalizer.normalize(
            pack.fields[field], current, unit=item.get("unit")
        ).stable_key()
        for current in values
    ]
    return field, operator, json.dumps(stable, sort_keys=True)


def _score_r2_canonical(
    pack: Any,
    cases: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    by_id = {item["case_id"]: item for item in rows}
    tp = fp = fn = task_correct = evidence_hit = evidence_total = 0
    failures = []
    for case in cases:
        row = by_id[case["case_id"]]
        gold = case["gold"]
        expected_constraints = {
            _constraint_signature(pack, item)
            for item in gold["constraints"]
            if item["active"] and item["status"] == "supported" and item["hard_or_soft"] == "hard"
        }
        actual_constraints = {
            _constraint_signature(pack, item)
            for item in row["active_constraints"]
            if item.get("active", True)
        }
        tp += len(expected_constraints & actual_constraints)
        fp += len(actual_constraints - expected_constraints)
        fn += len(expected_constraints - actual_constraints)
        scope = row["product_scope"]
        scope_ok = all(
            sorted(scope[key]) == sorted(gold["scope"][key])
            for key in ("family_ids", "product_ids", "configuration_ids", "regions")
        ) and all(
            scope[key] == gold["scope"][key]
            for key in (
                "scope_type",
                "explicit_comparison",
                "clarification_required",
                "resolution_status",
            )
        )
        tool_ok = _is_subsequence(gold["tool_path"]["required_order"], row["tools_used"])
        tool_ok = tool_ok and not set(gold["tool_path"]["forbidden"]) & set(row["tools_used"])
        ok = all(
            (
                scope_ok,
                actual_constraints == expected_constraints,
                tool_ok,
                set(row["checker_candidate_ids"]) == set(gold["checker_candidate_ids"]),
                row["result_kind"] == gold["result_kind"],
                set(row["final_candidate_ids"]) == set(gold["final_candidate_ids"]),
                row["clarification_required"] == gold["clarification_required"],
                row["abstain_reason"] == gold["abstain_reason"],
            )
        )
        task_correct += int(ok)
        if not ok:
            failures.append({
                "case_id": case["case_id"],
                "first_error_node": (
                    "candidate_scope" if not scope_ok
                    else "constraint_resolution" if actual_constraints != expected_constraints
                    else "tool_routing" if not tool_ok
                    else "checker_or_report"
                ),
            })
        evidence = row["evidence"]
        for requirement in gold["key_evidence"]:
            if requirement["expected_status"] == "unknown":
                continue
            if requirement["product_id"] not in row["final_candidate_ids"]:
                continue
            evidence_total += 1
            evidence_hit += int(any(
                item["product_id"] == requirement["product_id"]
                and item["field_id"] == requirement["field_id"]
                and item["evidence_id"] in requirement["evidence_ids"]
                for item in evidence
            ))
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {
        "task_accuracy": {"numerator": task_correct, "denominator": len(cases)},
        "clear_hard_constraint": {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        },
        "recommendation_evidence_coverage": {
            "numerator": evidence_hit,
            "denominator": evidence_total,
        },
        "failures": failures,
    }


class OfflineKBSearch:
    """Trace-compatible KB fixture; governed Evidence still comes from SQLite."""

    index_version = "offline-governed-evidence-v1"

    async def run(self, _query: str, **_kwargs: Any) -> ToolResult:
        return ToolResult(
            tool="domain_kb_search",
            status="success",
            data={"index_version": self.index_version, "hits": []},
            summary="离线回归使用治理 Evidence，不调用向量服务",
        )


def _agent(root: Path) -> DomainDecisionAgent:
    pack = DomainPackLoader().load(DOMAIN_PACK)
    manager = DomainProductPackManager(root / "data", domain_pack_path=DOMAIN_PACK)
    snapshot = manager.publish(manager.stage(PRODUCT_PACK).data_version)
    repository = DomainReadonlyRepository(snapshot, pack)
    return DomainDecisionAgent(
        pack,
        repository,
        DomainProductQueryTool(repository),
        DomainEvidenceCheckTool(repository),
        DomainConstraintCheckerTool(repository),
        NaturalConstraintEngine(pack),
        DomainPreferenceMemoryStore(root / "memory", pack),
        kb_search=OfflineKBSearch(),
    )


async def run(output: Path) -> dict[str, Any]:
    if output.exists():
        raise RuntimeError("exposed regression output is immutable")
    if _sha(R2_CASES) != R2_SHA256:
        raise RuntimeError("R2 frozen task hash changed")
    original_cases = _load(ORIGINAL_CASES)
    r2_cases = _load(R2_CASES)
    original_policy = json.loads(ORIGINAL_POLICY.read_text(encoding="utf-8"))["cases"]
    with tempfile.TemporaryDirectory(prefix="proofpick-r3-exposed-") as temporary:
        agent = _agent(Path(temporary))
        original_rows = []
        original_reports = []
        r2_rows = []
        durations = []
        for case in original_cases:
            started = time.perf_counter()
            report = await agent.run(case["question"])
            durations.append((time.perf_counter() - started) * 1000)
            original_reports.append(report)
            original_rows.append(score_original(case, report, original_policy))
        for case in r2_cases:
            started = time.perf_counter()
            report = await agent.run(case["question"])
            durations.append((time.perf_counter() - started) * 1000)
            row = _row_from_report(case, report)
            row["first_error_node"] = _first_error(case, row)
            r2_rows.append(row)

    raw_r2 = {
        "frozen_case_sha256": R2_SHA256,
        "cases": r2_rows,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
        json.dump(raw_r2, handle, ensure_ascii=False)
        temporary_result = Path(handle.name)
    try:
        r2_score = score_r2(temporary_result)
    finally:
        temporary_result.unlink(missing_ok=True)

    pack = DomainPackLoader().load(DOMAIN_PACK)
    r2_canonical = _score_r2_canonical(pack, r2_cases, r2_rows)
    old_tp = sum(item["field_tp"] for item in original_rows)
    old_fp = sum(item["field_fp"] for item in original_rows)
    old_fn = sum(item["field_fn"] for item in original_rows)
    r2_fields = r2_canonical["clear_hard_constraint"]
    tp, fp, fn = old_tp + r2_fields["tp"], old_fp + r2_fields["fp"], old_fn + r2_fields["fn"]
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    old_evidence_numerator = sum(item["recommendation_evidence_covered"] for item in original_rows)
    old_evidence_denominator = sum(item["recommendation_evidence_denominator"] for item in original_rows)
    r2_evidence = r2_canonical["recommendation_evidence_coverage"]
    old_eligible_rows = [
        item for item in original_rows
        if original_policy[item["case_id"]]["result_kind"] == "eligible"
    ]
    old_scope_leakage = sum(
        len(
            {
                *item["recommended_ids"],
                *[candidate["model_id"] for candidate in item["report"]["candidates"]],
                *[evidence["model_id"] for evidence in item["report"]["evidence"]],
            }
            - set(item["report"]["product_scope"]["product_ids"])
        )
        for item in original_rows
    )
    old_wrong_region = sum(
        1
        for item in original_rows
        for candidate in item["report"]["candidates"]
        if candidate["model_id"] in item["recommended_ids"]
        and candidate["region"] not in item["report"]["product_scope"]["regions"]
    )
    combined = {
        "task_accuracy": {
            "numerator": sum(item["task_correct"] for item in original_rows)
            + r2_canonical["task_accuracy"]["numerator"],
            "denominator": 50,
        },
        "clear_hard_constraint": {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
        "recommendation_evidence_coverage": {
            "numerator": old_evidence_numerator + r2_evidence["numerator"],
            "denominator": old_evidence_denominator + r2_evidence["denominator"],
        },
        "wrong_configuration_recommendations": (
            sum(
                len(set(item["recommended_ids"]) - set(item["report"]["product_scope"]["product_ids"]))
                for item in original_rows
            )
            + r2_score["metrics"]["wrong_configuration_recommendations"]
        ),
        "wrong_region_recommendations": old_wrong_region
        + r2_score["metrics"]["wrong_region_recommendations"],
        "candidate_scope_leakage": old_scope_leakage
        + r2_score["metrics"]["candidate_scope_leakage"],
        "checker_scope_leakage": (
            sum(item["checker_boundary_violations"] for item in original_rows)
            + r2_score["metrics"]["checker_scope_leakage"]
        ),
        "unknown_overclaimed": (
            sum(item["unknown_overclaimed"] for item in original_rows)
            + r2_score["metrics"]["unknown_overclaimed"]
        ),
        "clarification_bypass": r2_score["metrics"]["clarification_bypass"],
        "sufficient_evidence_empty_recommendation": {
            "numerator": sum(not item["recommended_ids"] for item in old_eligible_rows)
            + r2_score["metrics"]["sufficient_evidence_empty_recommendation"]["numerator"],
            "denominator": len(old_eligible_rows)
            + r2_score["metrics"]["sufficient_evidence_empty_recommendation"]["denominator"],
        },
        "provider_calls": 0,
        "estimated_cost_cny": 0.0,
        "average_latency_ms": statistics.mean(durations),
    }
    payload = {
        "schema_version": "proofpick-v2-6c-r3-exposed-regression-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "classification": {
            "laptop-001-010": "exposed_regression_v1",
            "laptop-011-020": "exposed_holdout_regression_v1",
            "laptop-021-030": "unrun_exposed_specialist",
            "laptop-r2-001-020": "exposed_holdout_regression_v2",
        },
        "input_hashes": {
            "original_30": _sha(ORIGINAL_CASES),
            "r2_20": _sha(R2_CASES),
        },
        "offline": True,
        "scoring_note": (
            "combined metrics use the R3 CanonicalValue contract; the frozen R2 exact-JSON "
            "score is retained separately under r2_20 and is not overwritten"
        ),
        "metrics": combined,
        "original_30": {
            "task_accuracy": {
                "numerator": sum(item["task_correct"] for item in original_rows),
                "denominator": 30,
            },
            "cases": [
                {key: item[key] for key in ("case_id", "task_correct", "field_tp", "field_fp", "field_fn")}
                for item in original_rows
            ],
        },
        "r2_20": r2_score,
        "r2_20_canonical_r3": r2_canonical,
        "r2_rows": r2_rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run(args.output))
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
