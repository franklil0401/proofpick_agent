"""Build the compact metric table and unified sanitized Stage 6 ledger."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from smartbuy.eval.run_stage6_eval import _build_ledger
from smartbuy.observability import EvaluationLedger, EvaluationLedgerRecord


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED = PROJECT_ROOT / "smartbuy/data/processed"
RESULTS = PROCESSED / "stage6_four_group_results.json"
CACHE_LEDGER = PROCESSED / "stage6_cache_ledger.jsonl"
RESILIENCE_LEDGER = PROCESSED / "stage6_resilience_ledger.jsonl"
FOUR_GROUP_LEDGER = PROCESSED / "stage6_evaluation_ledger.jsonl"
CHECKER_RESULTS = PROCESSED / "stage6_checker_determinism_results.json"
TARGETED_RESULTS = PROCESSED / "stage6_targeted_regression_results.json"
UNIFIED_LEDGER = PROCESSED / "stage6_unified_ledger.jsonl"
SUMMARY_CSV = PROCESSED / "stage6_metrics_summary.csv"


def _load_ledger(path: Path) -> list[EvaluationLedgerRecord]:
    return [
        EvaluationLedgerRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build() -> dict[str, int]:
    result = json.loads(RESULTS.read_text(encoding="utf-8"))
    config = result["frozen_config"]
    rows = []
    for group, metrics in result["first_run_metrics"].items():
        task = metrics["task_quality"]
        evidence = metrics["evidence_quality"]
        engineering = metrics["engineering"]
        rows.append(
            {
                "scope": "first_run_40",
                "experiment_group": group,
                "e2e_numerator": task["end_to_end_task_completion"]["numerator"],
                "e2e_denominator": task["end_to_end_task_completion"]["denominator"],
                "candidate_recall_numerator": task["correct_candidate_recall"]["numerator"],
                "candidate_recall_denominator": task["correct_candidate_recall"]["denominator"],
                "candidate_precision_numerator": task["recommended_candidate_precision"]["numerator"],
                "candidate_precision_denominator": task["recommended_candidate_precision"]["denominator"],
                "violating_recommendation_numerator": task["violating_candidate_recommendation_rate"]["numerator"],
                "violating_recommendation_denominator": task["violating_candidate_recommendation_rate"]["denominator"],
                "abstention_accuracy_numerator": task["abstention_accuracy"]["numerator"],
                "abstention_accuracy_denominator": task["abstention_accuracy"]["denominator"],
                "recall_at_5_numerator": evidence["recall_at_5"]["numerator"],
                "recall_at_5_denominator": evidence["recall_at_5"]["denominator"],
                "ndcg_at_5": evidence["ndcg_at_5"]["value"],
                "average_latency_ms": engineering["average_latency_ms"],
                "p95_latency_ms": engineering["p95_latency_ms"],
                "estimated_cost_cny": engineering["estimated_cost_cny"],
            }
        )
    with SUMMARY_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    ledger = EvaluationLedger()
    for path in (FOUR_GROUP_LEDGER, CACHE_LEDGER, RESILIENCE_LEDGER):
        ledger.extend(_load_ledger(path))
    targeted = json.loads(TARGETED_RESULTS.read_text(encoding="utf-8"))
    targeted_ledger = _build_ledger(
        targeted["predictions"], targeted["frozen_config"], targeted["run_id"]
    )
    ledger.extend(targeted_ledger.records)
    checker = json.loads(CHECKER_RESULTS.read_text(encoding="utf-8"))
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for step, row in enumerate(checker["cases"], start=1):
        ledger.add(
            EvaluationLedgerRecord(
                run_id=checker["evaluation_version"],
                case_id=row["case_id"],
                experiment_group="agentic_rag_checker",
                repetition=1,
                data_version=config["data_version"],
                config_hash=config["config_hash"],
                tool="constraint_checker_identical_input",
                step=step,
                started_at=timestamp,
                ended_at=timestamp,
                duration_ms=0,
                status="success" if row["three_run_byte_equivalent"] else "failed",
                final_metrics={
                    "three_run_byte_equivalent": row["three_run_byte_equivalent"],
                    "candidate_pool_size": row["candidate_pool_size"],
                },
            )
        )
    ledger.write(UNIFIED_LEDGER)
    return {"metric_rows": len(rows), "ledger_records": len(ledger.records)}


def main() -> int:
    print(json.dumps(build(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
