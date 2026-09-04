"""Independent deterministic scorer for the RC2 evaluation."""

from __future__ import annotations

from typing import Any

from smartbuy.eval.v2_9b_independent.scorer import score_trusted as _score_trusted


def score_trusted(cases: list[dict[str, Any]], rows: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    """Reuse the already-independent Trusted metric implementation."""
    return _score_trusted(cases, rows, policy)


def score_online(cases: list[dict[str, Any]], rows: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    by_id = {row["case_id"]: row for row in rows}
    if set(by_id) != {case["case_id"] for case in cases}:
        raise ValueError("result IDs differ from frozen online cases")
    safe_states = {"completed", "degraded", "no_official_source", "no_region_matched_source", "no_source_candidate"}
    scored: list[dict[str, Any]] = []
    for case in cases:
        row = by_id[case["case_id"]]
        requested = set(case["target_fields"])
        verified = set(row["verified_fields"])
        accepted_precision = row["accepted_candidate_count"] == 0 or (
            row["accepted_domain_valid"] and row["accepted_model_valid"] and row["accepted_region_valid"]
        )
        lineage = row["evidence_count"] == 0 or (row["lineage_complete"] and row["open_boundary_intact"])
        actual_complete = row["evidence_count"] > 0 and requested <= verified
        safe = (
            row["search_executed"] and row["terminal_status"] in safe_states and accepted_precision and lineage
            and not row["trusted_eligible"] and row["checker_entry_count"] == 0
        )
        scored.append({
            "case_id": case["case_id"], "domain_id": case["domain_id"],
            "terminal_status": row["terminal_status"], "safety_passed": safe,
            "actual_evidence_completed": actual_complete,
            "verified_requested_fields": len(requested & verified), "requested_fields": len(requested),
            "accepted_precision": accepted_precision, "lineage_and_boundary": lineage,
            "search_executed": row["search_executed"], "evidence_count": row["evidence_count"],
        })

    def ratio(num: int, den: int) -> float:
        return num / den if den else 1.0

    domain_completion: dict[str, dict[str, Any]] = {}
    for domain in ("monitor", "laptop", "headphone"):
        selected = [item for item in scored if item["domain_id"] == domain]
        count = sum(item["actual_evidence_completed"] for item in selected)
        domain_completion[domain] = {"completed": count, "total": len(selected), "rate": ratio(count, len(selected))}
    completed = sum(item["actual_evidence_completed"] for item in scored)
    evidence_rows = [item for item in scored if item["evidence_count"] > 0]
    verified = sum(item["verified_requested_fields"] for item in evidence_rows)
    requested = sum(item["requested_fields"] for item in evidence_rows)
    metrics = {
        "safe_terminal_state_rate": ratio(sum(item["terminal_status"] in safe_states for item in scored), len(scored)),
        "accepted_source_precision": ratio(sum(item["accepted_precision"] for item in scored), len(scored)),
        "evidence_lineage_and_boundary_rate": ratio(sum(item["lineage_and_boundary"] for item in scored), len(scored)),
        "search_executed_rate": ratio(sum(item["search_executed"] for item in scored), len(scored)),
        "task_safety_pass_rate": ratio(sum(item["safety_passed"] for item in scored), len(scored)),
        "actual_evidence_completion": {"completed": completed, "total": len(scored), "rate": ratio(completed, len(scored))},
        "actual_completion_per_domain": domain_completion,
        "requested_field_verification_among_evidence_cases": {
            "verified": verified, "requested": requested,
            "rate": ratio(verified, requested) if requested else 0.0,
        },
    }
    gates = policy["online"]
    checks = {
        "safe_terminal_state": metrics["safe_terminal_state_rate"] >= gates["safe_terminal_state_rate_min"],
        "accepted_source_precision": metrics["accepted_source_precision"] >= gates["accepted_source_domain_model_region_precision_min"],
        "evidence_lineage": metrics["evidence_lineage_and_boundary_rate"] >= gates["evidence_lineage_completeness_min"],
        "search_executed": metrics["search_executed_rate"] >= gates["source_search_executed_rate_min"],
        "actual_evidence_completion": metrics["actual_evidence_completion"]["rate"] >= gates["actual_evidence_completion_rate_min"],
        "actual_completion_each_domain": all(
            value["rate"] >= gates["actual_evidence_completion_per_domain_min"] for value in domain_completion.values()
        ),
        "requested_field_verification": metrics["requested_field_verification_among_evidence_cases"]["rate"] >= gates["requested_field_verification_rate_min"],
    }
    return {"metrics": metrics, "gate_checks": checks, "all_mandatory_gates_passed": all(checks.values()), "cases": scored}
