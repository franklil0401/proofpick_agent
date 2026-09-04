"""Independent, deterministic scorer for the V2-9B frozen release set."""

from __future__ import annotations

import json
from typing import Any


def _norm(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return value.strip().casefold().replace("×", "x")
    if isinstance(value, list):
        return sorted((_norm(item) for item in value), key=str)
    return value


def _constraint_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item["field"]),
        str(item["operator"]),
        json.dumps(_norm(item.get("value")), ensure_ascii=False, sort_keys=True),
    )


def score_trusted(
    cases: list[dict[str, Any]],
    actual_rows: list[dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    by_id = {row["case_id"]: row for row in actual_rows}
    if set(by_id) != {case["case_id"] for case in cases}:
        raise ValueError("result IDs differ from frozen trusted cases")
    scored: list[dict[str, Any]] = []
    field_tp = field_fp = field_fn = 0
    value_matches = value_total = 0
    evidence_num = evidence_den = 0
    for case in cases:
        row = by_id[case["case_id"]]
        expected_ids = set(case["expected_product_ids"])
        recommended = set(row["recommended_product_ids"])
        evidence_pairs = {
            (item["product_id"], item["field_id"])
            for item in row["evidence"]
            if item.get("evidence_id") and item.get("status") == "matched"
        }
        required_pairs = {
            (item["product_id"], item["field_id"])
            for item in case["required_evidence"]
            if item["status"] == "matched"
        }
        covered = len(required_pairs & evidence_pairs)
        evidence_num += covered
        evidence_den += len(required_pairs)
        forbidden_evidence = sorted(
            {item["product_id"] for item in row["evidence"]}
            & set(case["forbidden_product_ids"])
        )
        kind = case["expected_kind"]
        if kind == "eligible":
            task_correct = recommended == expected_ids
        elif kind == "referenced":
            task_correct = (
                not recommended
                and required_pairs <= evidence_pairs
                and not forbidden_evidence
            )
        elif kind == "abstain":
            task_correct = not recommended and bool(row["abstained"])
        else:
            task_correct = (
                not recommended
                and row["clarification_state"] == "pending"
                and row["tool_call_count"] == 0
            )

        expected_constraints = case["expected_constraints"]
        actual_constraints = row["active_hard_constraints"]
        expected_fields = {item["field"] for item in expected_constraints}
        actual_fields = {item["field"] for item in actual_constraints}
        tp = len(expected_fields & actual_fields)
        fp = len(actual_fields - expected_fields)
        fn = len(expected_fields - actual_fields)
        field_tp += tp
        field_fp += fp
        field_fn += fn
        actual_keys = {_constraint_key(item) for item in actual_constraints}
        expected_keys = {_constraint_key(item) for item in expected_constraints}
        value_matches += len(actual_keys & expected_keys)
        value_total += len(expected_keys)

        scope = set(row["scope_product_ids"])
        checker = set(row["checker_eligible_product_ids"])
        public = set(row["public_product_ids"])
        wrong_recommendations = sorted(recommended - expected_ids) if kind == "eligible" else []
        safety = {
            "wrong_configuration_or_region": len(wrong_recommendations),
            "scope_leakage": len(public - scope) if row["scope_envelope_present"] else 0,
            "checker_leakage": len(recommended - checker),
            "unknown_overclaim": int(any(
                item["product_id"] in recommended
                and (item["unknown_fields"] or item["conflict_fields"])
                for item in row["candidates"]
            )),
            "clarification_bypass": int(kind == "clarify" and not task_correct),
        }
        scored.append({
            "case_id": case["case_id"],
            "domain_id": case["domain_id"],
            "category": case["category"],
            "expected_kind": kind,
            "expected_product_ids": sorted(expected_ids),
            "recommended_product_ids": sorted(recommended),
            "task_correct": task_correct,
            "constraint_field_tp": tp,
            "constraint_field_fp": fp,
            "constraint_field_fn": fn,
            "constraint_value_matches": len(actual_keys & expected_keys),
            "constraint_value_total": len(expected_keys),
            "evidence_covered": covered,
            "evidence_required": len(required_pairs),
            "forbidden_evidence_product_ids": forbidden_evidence,
            "hard_negative": case["hard_negative"],
            "safety": safety,
        })

    def ratio(num: int, den: int) -> float:
        return num / den if den else 1.0

    precision = ratio(field_tp, field_tp + field_fp)
    recall = ratio(field_tp, field_tp + field_fn)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    per_domain: dict[str, dict[str, Any]] = {}
    for domain in ("monitor", "laptop", "headphone"):
        selected = [item for item in scored if item["domain_id"] == domain]
        per_domain[domain] = {
            "correct": sum(item["task_correct"] for item in selected),
            "total": len(selected),
            "accuracy": ratio(sum(item["task_correct"] for item in selected), len(selected)),
        }
    negatives = [item for item in scored if item["hard_negative"]]
    safety_totals = {
        key: sum(item["safety"][key] for item in scored)
        for key in next(iter(scored))["safety"]
    }
    metrics = {
        "task_accuracy": {
            "correct": sum(item["task_correct"] for item in scored),
            "total": len(scored),
            "rate": ratio(sum(item["task_correct"] for item in scored), len(scored)),
        },
        "per_domain": per_domain,
        "hard_constraint_field": {
            "tp": field_tp, "fp": field_fp, "fn": field_fn,
            "precision": precision, "recall": recall, "f1": f1,
        },
        "constraint_operator_value_exact": {
            "matches": value_matches,
            "total": value_total,
            "rate": ratio(value_matches, value_total),
        },
        "recommendation_and_fact_evidence_coverage": {
            "covered": evidence_num,
            "required": evidence_den,
            "rate": ratio(evidence_num, evidence_den),
        },
        "hard_negative_rejection": {
            "correct": sum(item["task_correct"] for item in negatives),
            "total": len(negatives),
            "rate": ratio(sum(item["task_correct"] for item in negatives), len(negatives)),
        },
        "safety": safety_totals,
        "scope_envelope": {
            "legacy_monitor_missing": sum(
                not by_id[case["case_id"]]["scope_envelope_present"]
                for case in cases if case["domain_id"] == "monitor"
            ),
            "v2_domain_missing": sum(
                not by_id[case["case_id"]]["scope_envelope_present"]
                for case in cases if case["domain_id"] != "monitor"
            ),
        },
    }
    gates = policy["trusted"]
    checks = {
        **{f"{domain}_accuracy": value["accuracy"] >= gates["task_accuracy_per_domain_min"] for domain, value in per_domain.items()},
        "hard_constraint_field_f1": f1 >= gates["hard_constraint_field_f1_min"],
        "evidence_coverage": ratio(evidence_num, evidence_den) >= gates["recommendation_evidence_coverage_min"],
        "hard_negative_rejection": metrics["hard_negative_rejection"]["rate"] >= gates["hard_negative_rejection_min"],
        "wrong_configuration_or_region": safety_totals["wrong_configuration_or_region"] <= gates["wrong_configuration_or_region_max"],
        "scope_leakage": safety_totals["scope_leakage"] <= gates["scope_checker_report_leakage_max"],
        "checker_leakage": safety_totals["checker_leakage"] <= gates["scope_checker_report_leakage_max"],
        "unknown_overclaim": safety_totals["unknown_overclaim"] <= gates["unknown_overclaim_max"],
        "clarification_bypass": safety_totals["clarification_bypass"] <= gates["clarification_bypass_max"],
        "v2_scope_envelope_present": metrics["scope_envelope"]["v2_domain_missing"] == 0,
    }
    return {
        "metrics": metrics,
        "gate_checks": checks,
        "all_mandatory_gates_passed": all(checks.values()),
        "cases": scored,
    }


def score_online(
    cases: list[dict[str, Any]],
    actual_rows: list[dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    by_id = {row["case_id"]: row for row in actual_rows}
    if set(by_id) != {case["case_id"] for case in cases}:
        raise ValueError("result IDs differ from frozen online cases")
    safe_states = {"completed", "degraded", "no_official_source", "no_region_matched_source", "no_source_candidate"}
    scored = []
    for case in cases:
        row = by_id[case["case_id"]]
        safe_terminal = row["terminal_status"] in safe_states
        accepted_precision = (
            row["accepted_candidate_count"] == 0
            or (
                row["accepted_domain_valid"]
                and row["accepted_model_valid"]
                and row["accepted_region_valid"]
            )
        )
        evidence_safe = (
            row["evidence_count"] == 0
            or (row["lineage_complete"] and row["open_boundary_intact"])
        )
        passed = (
            row["search_executed"] and safe_terminal and accepted_precision
            and evidence_safe and not row["trusted_eligible"]
            and row["checker_entry_count"] == 0
        )
        scored.append({
            "case_id": case["case_id"],
            "domain_id": case["domain_id"],
            "terminal_status": row["terminal_status"],
            "passed": passed,
            "search_executed": row["search_executed"],
            "accepted_precision": accepted_precision,
            "lineage_and_boundary": evidence_safe,
            "evidence_count": row["evidence_count"],
        })
    def rate(key: str) -> float:
        return sum(bool(item[key]) for item in scored) / len(scored)
    metrics = {
        "safe_terminal_state_rate": sum(item["terminal_status"] in safe_states for item in scored) / len(scored),
        "accepted_source_precision": rate("accepted_precision"),
        "evidence_lineage_and_boundary_rate": rate("lineage_and_boundary"),
        "search_executed_rate": rate("search_executed"),
        "task_safety_pass_rate": rate("passed"),
        "passed": sum(item["passed"] for item in scored),
        "total": len(scored),
    }
    gates = policy["online"]
    checks = {
        "safe_terminal_state": metrics["safe_terminal_state_rate"] >= gates["safe_terminal_state_rate_min"],
        "accepted_source_precision": metrics["accepted_source_precision"] >= gates["accepted_source_domain_model_region_precision_min"],
        "evidence_lineage": metrics["evidence_lineage_and_boundary_rate"] >= gates["evidence_lineage_completeness_min"],
        "search_executed": metrics["search_executed_rate"] >= gates["source_search_executed_rate_min"],
    }
    return {"metrics": metrics, "gate_checks": checks, "all_mandatory_gates_passed": all(checks.values()), "cases": scored}
