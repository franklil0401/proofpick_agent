"""Exact-denominator scoring for deterministic constraint verification suites."""

from __future__ import annotations

import math
import statistics
import time
from typing import Any

from .normalize import ConstraintNormalizer
from .verifier import CandidateConstraintVerifier


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]


def score_fixed_cases(
    cases: list[dict[str, Any]],
    *,
    normalizer: ConstraintNormalizer,
    verifier: CandidateConstraintVerifier,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    field_total = 0
    field_correct = 0
    task_correct = 0
    violation_total = 0
    violation_intercepted = 0
    compliant_total = 0
    compliant_retained = 0
    unknown_conflict_total = 0
    unknown_conflict_correct = 0
    unsupported_total = 0
    unsupported_correct = 0
    deterministic_total = 0
    deterministic_correct = 0
    latencies: list[float] = []
    for case in cases:
        constraint_set = normalizer.build(case["question"], source_turn=1)
        started = time.perf_counter()
        verification = verifier.verify_candidates(
            constraint_set, list(case["candidate_pool_model_ids"])
        )
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        repeated = verifier.verify_candidates(
            constraint_set, list(case["candidate_pool_model_ids"])
        )
        deterministic_total += 1
        deterministic_pass = verification.model_dump_json() == repeated.model_dump_json()
        deterministic_correct += int(deterministic_pass)

        actual_statuses = {
            candidate.model_id: {
                result.constraint.field: result.status.value
                for result in candidate.constraint_results
                if result.constraint.hard_or_soft.value == "hard"
            }
            for candidate in verification.candidates
        }
        case_field_total = 0
        case_field_correct = 0
        for model_id, expected_fields in case["expected_statuses"].items():
            for field, expected_status in expected_fields.items():
                case_field_total += 1
                case_field_correct += int(actual_statuses.get(model_id, {}).get(field) == expected_status)
                if expected_status in {"unknown", "conflict"}:
                    unknown_conflict_total += 1
                    unknown_conflict_correct += int(
                        actual_statuses.get(model_id, {}).get(field) == expected_status
                    )
                if case.get("fault_type") == "unsupported_constraint":
                    unsupported_total += 1
                    candidate = next(
                        (item for item in verification.candidates if item.model_id == model_id), None
                    )
                    unsupported_correct += int(
                        candidate is not None and field in candidate.unsupported_constraints
                    )
        field_total += case_field_total
        field_correct += case_field_correct

        expected_eligible = set(case["expected_eligible_model_ids"])
        actual_eligible = set(verification.eligible_model_ids)
        eligibility_pass = actual_eligible == expected_eligible
        task_correct += int(eligibility_pass)
        pool = set(case["candidate_pool_model_ids"])
        expected_rejected = pool - expected_eligible
        violation_total += len(expected_rejected)
        violation_intercepted += len(expected_rejected - actual_eligible)
        compliant_total += len(expected_eligible)
        compliant_retained += len(expected_eligible & actual_eligible)

        rows.append(
            {
                "case_id": case["case_id"],
                "fault_type": case.get("fault_type"),
                "candidate_pool_model_ids": case["candidate_pool_model_ids"],
                "expected_eligible_model_ids": sorted(expected_eligible),
                "actual_eligible_model_ids": verification.eligible_model_ids,
                "field_checks_correct": case_field_correct,
                "field_checks_total": case_field_total,
                "eligibility_pass": eligibility_pass,
                "deterministic_repeat_pass": deterministic_pass,
                "checker_latency_ms": round(latency_ms, 3),
                "semantic_fingerprint": verification.semantic_fingerprint,
                "candidate_results": [
                    {
                        "model_id": item.model_id,
                        "overall_status": item.overall_status.value,
                        "eligible": item.eligible,
                        "violated_fields": item.violated_fields,
                        "unknown_fields": item.unknown_fields,
                        "conflict_fields": item.conflict_fields,
                        "unsupported_constraints": item.unsupported_constraints,
                        "constraint_results": [
                            {
                                "field": result.constraint.field,
                                "status": result.status.value,
                                "actual_value": result.actual_value,
                                "expected_value": result.constraint.normalized_value,
                                "evidence_id": result.evidence_id,
                                "source_id": result.source_id,
                            }
                            for result in item.constraint_results
                        ],
                    }
                    for item in verification.candidates
                ],
            }
        )
    return {
        "metrics": {
            "case_count": len(cases),
            "field_level_hard_constraint_rate": round(field_correct / field_total, 6) if field_total else 1.0,
            "field_checks_correct": field_correct,
            "field_checks_total": field_total,
            "task_level_hard_constraint_rate": round(task_correct / len(cases), 6) if cases else 1.0,
            "tasks_correct": task_correct,
            "tasks_total": len(cases),
            "violation_interception_rate": round(violation_intercepted / violation_total, 6)
            if violation_total else 1.0,
            "violations_intercepted": violation_intercepted,
            "violations_total": violation_total,
            "compliant_candidate_false_kill_rate": round(
                (compliant_total - compliant_retained) / compliant_total, 6
            ) if compliant_total else 0.0,
            "compliant_candidates_retained": compliant_retained,
            "compliant_candidates_total": compliant_total,
            "unknown_conflict_handling_rate": round(
                unknown_conflict_correct / unknown_conflict_total, 6
            ) if unknown_conflict_total else 1.0,
            "unknown_conflict_correct": unknown_conflict_correct,
            "unknown_conflict_total": unknown_conflict_total,
            "unsupported_identification_rate": round(unsupported_correct / unsupported_total, 6)
            if unsupported_total else 1.0,
            "unsupported_correct": unsupported_correct,
            "unsupported_total": unsupported_total,
            "deterministic_repeat_rate": round(deterministic_correct / deterministic_total, 6)
            if deterministic_total else 1.0,
            "average_checker_latency_ms": round(statistics.fmean(latencies), 3) if latencies else 0.0,
            "p95_checker_latency_ms": round(_p95(latencies), 3),
            "checker_api_call_count": 0,
            "checker_api_cost_cny": 0.0,
        },
        "cases": rows,
    }
