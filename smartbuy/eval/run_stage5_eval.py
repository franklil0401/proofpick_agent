"""Run Stage 5 fixed-pool ablation or bounded live Agent validation."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smartbuy.agent import PurchaseDecisionAgent
from smartbuy.config import load_bailian_settings
from smartbuy.constraints import (
    CandidateConstraintVerifier,
    ConstraintNormalizer,
    ConstraintStrength,
    score_fixed_cases,
)
from smartbuy.db.build_database import DEFAULT_OUTPUT
from smartbuy.memory import LongTermPreferenceStore, SessionMemoryStore
from smartbuy.observability import UsageLedger
from smartbuy.providers import BailianProvider
from smartbuy.tools import EvidenceCheckTool, KBSearchTool, Text2SQLTool, WebSearchTool


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STAGE4_CASES = Path(__file__).with_name("stage4_cases.jsonl")
STAGE4_RESULTS = PROJECT_ROOT / "smartbuy/data/processed/stage4_e2e_results.json"
NATURAL_CASES = Path(__file__).with_name("stage5_natural_cases.jsonl")
FAULT_CASES = Path(__file__).with_name("stage5_fault_cases.jsonl")
FIXED_RESULTS = PROJECT_ROOT / "smartbuy/data/processed/stage5_fixed_ablation_results.json"
DRY_RESULTS = PROJECT_ROOT / "smartbuy/data/processed/stage5_agent_dry_run_results.json"
AGENT_RESULTS = PROJECT_ROOT / "smartbuy/data/processed/stage5_agent_e2e_results.json"
AS_OF = datetime(2026, 8, 27, 0, 0, tzinfo=UTC)
STAGE_COST_LIMIT_CNY = 10.0


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))]


def _controlled_stage4_ablation(
    normalizer: ConstraintNormalizer, verifier: CandidateConstraintVerifier
) -> dict[str, Any]:
    cases = {item["case_id"]: item for item in load_jsonl(STAGE4_CASES)}
    baseline = json.loads(STAGE4_RESULTS.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    a_task_pass = 0
    b_task_pass = 0
    recoveries = 0
    removals = 0
    gold_eligible_total = 0
    a_false_kills = 0
    b_false_kills = 0
    a_field_passed = 0
    a_field_total = 0
    b_field_passed = 0
    b_field_total = 0
    for baseline_case in baseline["cases"]:
        case = cases[baseline_case["case_id"]]
        constraint_set = normalizer.build(case["question"], source_turn=1)
        hard = [
            item
            for item in constraint_set.active(hard_only=True)
            if item.hard_or_soft == ConstraintStrength.HARD
        ]
        if not hard:
            continue
        pool = [item["model_id"] for item in baseline_case.get("candidates", [])]
        verification = verifier.verify_candidates(constraint_set, pool)
        a_recommended = {
            item["model_id"]
            for item in baseline_case.get("candidates", [])
            if item.get("overall_status") == "matched"
        }
        b_recommended = set(verification.eligible_model_ids)
        expected = set(case["expected_model_ids"])
        a_pass = a_recommended == expected
        b_pass = b_recommended == expected
        a_task_pass += int(a_pass)
        b_task_pass += int(b_pass)
        recoveries += len(b_recommended - a_recommended)
        removals += len(a_recommended - b_recommended)
        gold_eligible_total += len(expected)
        a_false_kills += len(expected - a_recommended)
        b_false_kills += len(expected - b_recommended)
        by_model = {item.model_id: item for item in verification.candidates}
        for recommendations, label in ((a_recommended, "a"), (b_recommended, "b")):
            for model_id in recommendations:
                candidate = by_model.get(model_id)
                if candidate is None:
                    if label == "a":
                        a_field_total += 1
                    else:
                        b_field_total += 1
                    continue
                hard_results = [
                    result
                    for result in candidate.constraint_results
                    if result.constraint.hard_or_soft == ConstraintStrength.HARD
                ]
                passed = sum(result.status.value == "passed" for result in hard_results)
                if label == "a":
                    a_field_passed += passed
                    a_field_total += len(hard_results)
                else:
                    b_field_passed += passed
                    b_field_total += len(hard_results)
        rows.append(
            {
                "case_id": case["case_id"],
                "candidate_pool_model_ids": pool,
                "same_candidate_pool": verification.candidate_pool_model_ids == pool,
                "expected_eligible_model_ids": sorted(expected),
                "stage4_recommended_model_ids": sorted(a_recommended),
                "stage5_recommended_model_ids": verification.eligible_model_ids,
                "stage4_task_pass": a_pass,
                "stage5_task_pass": b_pass,
                "recovered_model_ids": sorted(b_recommended - a_recommended),
                "removed_model_ids": sorted(a_recommended - b_recommended),
                "semantic_fingerprint": verification.semantic_fingerprint,
            }
        )
    denominator = len(rows)
    return {
        "definition": (
            "A 使用阶段 4 已保存输出；B 对完全相同的已保存工具候选池运行 Checker。"
            "只纳入存在当前输入硬约束的阶段 4 用例，未重跑或削弱 A。"
        ),
        "metrics": {
            "applicable_task_count": denominator,
            "stage4_task_level_hard_constraint_rate": round(a_task_pass / denominator, 6)
            if denominator else 1.0,
            "stage5_task_level_hard_constraint_rate": round(b_task_pass / denominator, 6)
            if denominator else 1.0,
            "stage4_field_level_hard_constraint_rate": round(a_field_passed / a_field_total, 6)
            if a_field_total else 1.0,
            "stage4_field_checks_passed": a_field_passed,
            "stage4_field_checks_total": a_field_total,
            "stage5_field_level_hard_constraint_rate": round(b_field_passed / b_field_total, 6)
            if b_field_total else 1.0,
            "stage5_field_checks_passed": b_field_passed,
            "stage5_field_checks_total": b_field_total,
            "stage4_compliant_false_kill_rate": round(a_false_kills / gold_eligible_total, 6)
            if gold_eligible_total else 0.0,
            "stage5_compliant_false_kill_rate": round(b_false_kills / gold_eligible_total, 6)
            if gold_eligible_total else 0.0,
            "candidate_recovery_count": recoveries,
            "incorrect_recommendation_removal_count": removals,
            "same_candidate_pool_rate": round(
                sum(row["same_candidate_pool"] for row in rows) / denominator, 6
            ) if denominator else 1.0,
            "checker_api_call_count": 0,
            "checker_api_cost_cny": 0.0,
        },
        "cases": rows,
    }


def evaluate_fixed() -> dict[str, Any]:
    normalizer = ConstraintNormalizer()
    verifier = CandidateConstraintVerifier(DEFAULT_OUTPUT, as_of=AS_OF)
    natural = score_fixed_cases(
        load_jsonl(NATURAL_CASES), normalizer=normalizer, verifier=verifier
    )
    faults = score_fixed_cases(
        load_jsonl(FAULT_CASES), normalizer=normalizer, verifier=verifier
    )
    controlled = _controlled_stage4_ablation(normalizer, verifier)
    blockers = []
    for label, metrics in (
        ("natural", natural["metrics"]),
        ("fault", faults["metrics"]),
    ):
        for key in (
            "field_level_hard_constraint_rate",
            "task_level_hard_constraint_rate",
            "violation_interception_rate",
            "unknown_conflict_handling_rate",
            "deterministic_repeat_rate",
        ):
            if float(metrics[key]) != 1.0:
                blockers.append(f"{label}.{key}")
    if float(faults["metrics"]["unsupported_identification_rate"]) != 1.0:
        blockers.append("fault.unsupported_identification_rate")
    return {
        "evaluation_version": "smartbuy-stage5-fixed-ablation-v1",
        "as_of": AS_OF.isoformat().replace("+00:00", "Z"),
        "data_version": "monitor-cn-2026-08-26-v1",
        "schema_version": "1.0.0",
        "controlled_stage4_ablation": controlled,
        "new_natural_hard_cases": natural,
        "fault_injection_cases": faults,
        "blocking_failures": blockers,
        "passed": not blockers,
    }


def _observed_models(report: Any) -> set[str]:
    return {
        *report.recommended_model_ids,
        *(item.model_id for item in report.evidence),
        *(report.constraint_verification.candidate_pool_model_ids if report.constraint_verification else []),
    }


def _multihop_pass(report: Any) -> bool:
    traces = [
        item for item in report.trace
        if item.tool in {"text2sql", "kb_search", "evidence_check"}
        and item.status in {"success", "degraded"}
    ]
    tools = [item.tool for item in traces]
    return (
        all(tool in tools for tool in ("text2sql", "kb_search", "evidence_check"))
        and tools.index("text2sql") < tools.index("kb_search") < tools.index("evidence_check")
        and all(item.parent_step is not None for item in traces if item.tool in {"kb_search", "evidence_check"})
    )


async def evaluate_agent(*, dry_run: bool, case_ids: list[str] | None = None) -> dict[str, Any]:
    cases = load_jsonl(STAGE4_CASES)
    if case_ids:
        requested = set(case_ids)
        cases = [item for item in cases if item["case_id"] in requested]
        missing = requested - {item["case_id"] for item in cases}
        if missing:
            raise ValueError(f"unknown case ids: {sorted(missing)}")
    elif dry_run:
        cases = cases[:4]
    settings = load_bailian_settings()
    ledger = UsageLedger()
    provider = BailianProvider(settings, ledger=ledger, timeout_seconds=30.0)
    agent = PurchaseDecisionAgent(
        provider,
        {
            "text2sql": Text2SQLTool(DEFAULT_OUTPUT),
            "kb_search": KBSearchTool(settings, provider),
            "evidence_check": EvidenceCheckTool(DEFAULT_OUTPUT),
            "web_search": WebSearchTool(),
        },
        session_memory=SessionMemoryStore(),
        preference_memory=LongTermPreferenceStore("C:/ai/smartbuy-stage5/eval_preferences.json"),
        constraint_verifier=CandidateConstraintVerifier(DEFAULT_OUTPUT, as_of=AS_OF),
    )
    rows = []
    try:
        for case in cases:
            if float(ledger.summary()["estimated_cost_cny"]) >= STAGE_COST_LIMIT_CNY:
                raise RuntimeError("Stage 5 API cost limit reached before evaluation completed")
            report = await agent.run(case["question"], session_id=f"stage5-{case['case_id']}")
            expected_tools = set(case["expected_tools"])
            actual_tools = set(report.tools_used)
            expected_models = set(case["expected_model_ids"])
            observed_models = _observed_models(report)
            recall = len(observed_models & expected_models) / len(expected_models) if expected_models else 1.0
            checker = report.constraint_verification
            recommended = set(report.recommended_model_ids)
            eligible = set(checker.eligible_model_ids if checker else [])
            recommendation_task = report.task_type in {"filter", "comparison", "dynamic"}
            gate_integrity = bool(checker) and recommended.issubset(eligible)
            if recommendation_task:
                gate_integrity = gate_integrity and recommended == eligible
            row = {
                "case_id": case["case_id"],
                "category": case["category"],
                "tool_selection_pass": expected_tools.issubset(actual_tools),
                "expected_tools": sorted(expected_tools),
                "actual_tools": report.tools_used,
                "model_recall": round(recall, 6),
                "expected_model_ids": sorted(expected_models),
                "observed_model_ids": sorted(observed_models),
                "abstention_pass": report.abstained == case["should_abstain"],
                "should_abstain": case["should_abstain"],
                "actual_abstain": report.abstained,
                "multihop_pass": _multihop_pass(report) if case["multihop"] else True,
                "multihop_required": case["multihop"],
                "schema_pass": report.report_version == "smartbuy-decision-v2",
                "constraint_gate_integrity_pass": gate_integrity,
                "constraint_checker_degraded": checker.degraded if checker else True,
                "candidate_pool_model_ids": checker.candidate_pool_model_ids if checker else [],
                "eligible_model_ids": checker.eligible_model_ids if checker else [],
                "recommended_model_ids": report.recommended_model_ids,
                "constraint_check_latency_ms": report.constraint_check_latency_ms,
                "latency_ms": report.latency_ms,
                "tool_call_count": report.tool_call_count,
                "usage": report.usage,
                "stop_reason": report.stop_reason,
                "task_type": report.task_type,
                "public_trace": [item.model_dump(mode="json") for item in report.trace],
            }
            row["end_to_end_pass"] = all(
                [
                    row["tool_selection_pass"], row["model_recall"] == 1.0,
                    row["abstention_pass"], row["multihop_pass"], row["schema_pass"],
                    row["constraint_gate_integrity_pass"], not row["constraint_checker_degraded"],
                ]
            )
            rows.append(row)
    finally:
        await provider.aclose()
    positive = [row for row in rows if row["expected_model_ids"]]
    multihop = [row for row in rows if row["multihop_required"]]
    latencies = [row["latency_ms"] for row in rows]
    checker_latencies = [row["constraint_check_latency_ms"] for row in rows]
    metrics = {
        "case_count": len(rows),
        "tool_selection_accuracy": round(statistics.fmean(row["tool_selection_pass"] for row in rows), 6),
        "model_recall": round(statistics.fmean(row["model_recall"] for row in positive), 6) if positive else 1.0,
        "abstention_accuracy": round(statistics.fmean(row["abstention_pass"] for row in rows), 6),
        "multihop_completion_rate": round(statistics.fmean(row["multihop_pass"] for row in multihop), 6)
        if multihop else 1.0,
        "schema_pass_rate": round(statistics.fmean(row["schema_pass"] for row in rows), 6),
        "constraint_gate_integrity_rate": round(
            statistics.fmean(row["constraint_gate_integrity_pass"] for row in rows), 6
        ),
        "end_to_end_pass_rate": round(statistics.fmean(row["end_to_end_pass"] for row in rows), 6),
        "average_latency_ms": round(statistics.fmean(latencies), 3),
        "p95_latency_ms": round(percentile(latencies, 0.95), 3),
        "average_constraint_check_latency_ms": round(statistics.fmean(checker_latencies), 3),
        "p95_constraint_check_latency_ms": round(percentile(checker_latencies, 0.95), 3),
        "checker_api_call_count": 0,
        "checker_api_cost_cny": 0.0,
    }
    return {
        "evaluation_version": "smartbuy-stage5-agent-e2e-v1",
        "mode": "targeted_regression" if case_ids else ("dry_run" if dry_run else "full"),
        "passed": all(row["end_to_end_pass"] for row in rows),
        "metrics": metrics,
        "usage": ledger.summary(),
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fixed", action="store_true", help="run offline fixed-pool ablation and fault suites")
    group.add_argument("--dry-run", action="store_true", help="run the first four live Agent cases")
    group.add_argument("--full", action="store_true", help="run all sixteen live Agent cases")
    parser.add_argument(
        "--case-id", action="append", dest="case_ids",
        help="limit a live run to explicit case IDs; repeat for multiple cases",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.fixed:
        payload = evaluate_fixed()
        default_output = FIXED_RESULTS
    else:
        payload = asyncio.run(evaluate_agent(dry_run=args.dry_run, case_ids=args.case_ids))
        default_output = DRY_RESULTS if args.dry_run else AGENT_RESULTS
    output = args.output or default_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    summary = {
        "mode": payload.get("mode", "fixed"),
        "passed": payload.get("passed"),
        "metrics": payload.get("metrics"),
        "usage": payload.get("usage"),
        "blocking_failures": payload.get("blocking_failures"),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if payload.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
