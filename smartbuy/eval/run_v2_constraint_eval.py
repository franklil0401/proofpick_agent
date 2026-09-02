"""Reproduce the frozen V2-5 expression evaluation without network access."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from smartbuy.constraint_proposals.engine import ENGINE_VERSION, NaturalConstraintEngine
from smartbuy.constraints import (
    ConstraintOperator,
    ConstraintProvenance,
    ConstraintSet,
    ConstraintStrength,
    NormalizedConstraint,
)
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.domain_packs.loader import DEFAULT_MONITOR_PACK


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = ROOT / "smartbuy/eval/v2_stage5_expression_cases.jsonl"


def _previous(items: list[dict[str, Any]]) -> ConstraintSet | None:
    if not items:
        return None
    return ConstraintSet(
        constraints=[
            NormalizedConstraint(
                field=item["field"],
                operator=ConstraintOperator(item["operator"]),
                normalized_value=item["value"],
                unit=item.get("unit"),
                hard_or_soft=ConstraintStrength(item["strength"]),
                provenance=ConstraintProvenance.SESSION_CONFIRMED,
                source_text="frozen fixture",
                source_turn=1,
                confidence=1.0,
                supported=True,
                active=True,
            )
            for item in items
        ]
    )


def _signature(item: dict[str, Any]) -> str:
    return json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def evaluate(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    cases = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    engine = NaturalConstraintEngine(DomainPackLoader().load(DEFAULT_MONITOR_PACK))
    tp = fp = fn = exact = 0
    clear_tp = clear_fp = clear_fn = 0
    failed: list[str] = []
    split_exact: dict[str, int] = {"regression": 0, "holdout": 0}
    clarification_cases = clarification_safe = 0
    unsupported_cases = unsupported_safe = 0
    latencies: list[float] = []
    for case in cases:
        resolution = await engine.resolve(
            case["query"],
            source_turn=2 if case.get("previous") else 1,
            previous=_previous(case.get("previous", [])),
        )
        latencies.append(resolution.latency_ms)
        actual_items = [
                {
                    "field": item.field,
                    "operator": item.operator.value if item.operator else "eq",
                    "value": item.normalized_value,
                    "unit": item.unit,
                    "strength": item.strength.value,
                    "status": item.status.value,
                    "action": item.action.value,
                }
            for item in resolution.proposals
        ]
        expected = {_signature(item) for item in case["expected"]}
        actual = {_signature(item) for item in actual_items}
        expected_clear = {
            _signature(item)
            for item in case["expected"]
            if item["status"] == "supported"
            and item["strength"] == "hard"
            and item["action"] in {"add", "override"}
        }
        actual_clear = {
            _signature(item)
            for item in actual_items
            if item["status"] == "supported"
            and item["strength"] == "hard"
            and item["action"] in {"add", "override"}
        }
        tp += len(expected & actual)
        fp += len(actual - expected)
        fn += len(expected - actual)
        clear_tp += len(expected_clear & actual_clear)
        clear_fp += len(actual_clear - expected_clear)
        clear_fn += len(expected_clear - actual_clear)
        if expected == actual:
            exact += 1
            split_exact[case["split"]] += 1
        else:
            failed.append(case["case_id"])
        expected_statuses = {item["status"] for item in case["expected"]}
        if expected_statuses & {"ambiguous", "needs_confirmation"}:
            clarification_cases += 1
            clarification_safe += not any(
                item.active and item.status.value != "supported"
                for item in resolution.proposals
            )
        if "unsupported" in expected_statuses:
            unsupported_cases += 1
            unsupported_safe += not any(
                item.active and item.status.value == "unsupported"
                for item in resolution.proposals
            )
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    clear_precision = clear_tp / (clear_tp + clear_fp) if clear_tp + clear_fp else 0.0
    clear_recall = clear_tp / (clear_tp + clear_fn) if clear_tp + clear_fn else 0.0
    clear_f1 = (
        2 * clear_precision * clear_recall / (clear_precision + clear_recall)
        if clear_precision + clear_recall
        else 0.0
    )
    ordered_latency = sorted(latencies)
    p95_index = max(0, min(len(ordered_latency) - 1, int(len(ordered_latency) * 0.95)))
    return {
        "schema_version": "proofpick-v2-constraint-eval-result-v1",
        "run_type": "postfix_frozen_full",
        "runner": ENGINE_VERSION,
        "provider": "offline_rules_only",
        "cases_sha256": hashlib.sha256(payload).hexdigest(),
        "case_count": len(cases),
        "splits": {"regression": 30, "holdout": 20},
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "clear_hard_fields": {
            "true_positive": clear_tp,
            "false_positive": clear_fp,
            "false_negative": clear_fn,
            "precision": round(clear_precision, 6),
            "recall": round(clear_recall, 6),
            "f1": round(clear_f1, 6),
        },
        "task_exact": exact,
        "split_task_exact": split_exact,
        "clarification_safe": f"{clarification_safe}/{clarification_cases}",
        "unsupported_safe": f"{unsupported_safe}/{unsupported_cases}",
        "failed_case_ids": failed,
        "average_rule_latency_ms": round(sum(latencies) / len(latencies), 3),
        "p95_rule_latency_ms": round(ordered_latency[p95_index], 3),
        "api_calls": 0,
        "estimated_cost_cny": 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(evaluate(args.cases)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
