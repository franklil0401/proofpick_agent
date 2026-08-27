"""Deterministic scoring for the frozen Stage 6 four-group experiment."""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from typing import Any


def ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 6) if denominator else None,
        "status": "measured" if denominator else "N/A",
    }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return round(ordered[index], 3)


def _dcg(ranked: list[str], gold: set[str], k: int = 5) -> float:
    return sum((1.0 / math.log2(index + 2)) for index, item in enumerate(ranked[:k]) if item in gold)


def _ndcg(ranked: list[str], gold: set[str], k: int = 5) -> float:
    if not gold:
        return 1.0
    # Retrieval works at chunk level, while this metric is explicitly at the
    # product/model level. Multiple chunks from one product must not collect
    # relevance gain repeatedly.
    unique_ranked = list(dict.fromkeys(ranked))
    ideal = _dcg(list(gold)[: min(k, len(gold))], gold, k)
    return _dcg(unique_ranked, gold, k) / ideal if ideal else 0.0


def _case_answer_models(case: dict[str, Any], prediction: dict[str, Any]) -> set[str]:
    if prediction.get("abstained"):
        return set()
    if case["task_type"] in {"filter", "comparison", "dynamic"}:
        return set(prediction.get("recommended_model_ids", []))
    return set(prediction.get("observed_model_ids", []))


def score_group(
    predictions: list[dict[str, Any]],
    cases_by_id: dict[str, dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    candidate_gold = candidate_hit = predicted_total = predicted_correct = 0
    hard_pass = hard_total = hard_task_pass = hard_task_total = 0
    false_kills = violations = recommendation_total = 0
    abstain_tp = abstain_fp = abstain_fn = abstain_correct = 0
    unknown_pass = unknown_total = unsupported_pass = unsupported_total = 0
    citation_correct = citation_total = evidence_covered = evidence_total = 0
    unsupported_claims = claim_total = wrong_reference = reference_total = 0
    conflict_pass = conflict_total = 0
    retrieval_hit = retrieval_total = 0
    ndcgs: list[float] = []
    tool_pass = tool_total = necessary_hit = necessary_total = 0
    multihop_pass = multihop_total = order_pass = order_total = 0
    blocked_calls = blocked_total = degrade_visible = degrade_total = 0
    e2e_pass = 0
    model_latency_ms: dict[str, float] = defaultdict(float)
    tool_latency_ms: dict[str, float] = defaultdict(float)
    cache_hits = cache_observations = retry_count = 0
    api_errors: Counter[str] = Counter()

    for prediction in predictions:
        case = cases_by_id[prediction["case_id"]]
        expected = set(case["expected_model_ids"])
        actual = _case_answer_models(case, prediction)
        candidate_gold += len(expected)
        candidate_hit += len(actual & expected)
        predicted_total += len(actual)
        predicted_correct += len(actual & expected)
        false_kills += len(expected - actual)

        actual_abstain = bool(prediction.get("abstained"))
        expected_abstain = bool(case["should_abstain"])
        abstain_correct += int(actual_abstain == expected_abstain)
        abstain_tp += int(actual_abstain and expected_abstain)
        abstain_fp += int(actual_abstain and not expected_abstain)
        abstain_fn += int(not actual_abstain and expected_abstain)

        hard_checks = prediction.get("hard_constraint_checks", [])
        hard_total += len(hard_checks)
        hard_pass += sum(item.get("status") == "passed" for item in hard_checks)
        if prediction.get("has_hard_constraints"):
            hard_task_total += 1
            task_hard_ok = actual == expected and all(
                item.get("status") == "passed" for item in hard_checks
            )
            if expected and not hard_checks:
                task_hard_ok = False
            hard_task_pass += int(task_hard_ok)
        recommendation_total += len(prediction.get("recommended_model_ids", []))
        violations += sum(
            item.get("overall_status") != "passed"
            for item in prediction.get("recommended_candidate_verifications", [])
        )

        expected_unknown = case["category"] in {
            "source_conflict", "dynamic_unknown", "price_missing", "ambiguous_constraint",
        }
        if expected_unknown:
            unknown_total += 1
            unknown_pass += int(bool(prediction.get("unknown_or_conflict_reported")))
        expected_unsupported = any(
            field in {
                "camera", "face_recognition", "ten_year_burn_in_guarantee",
                "lifetime_zero_dead_pixel_guarantee",
            }
            for field in case["required_fields"]
        )
        if expected_unsupported:
            unsupported_total += 1
            unsupported_pass += int(bool(prediction.get("unsupported_constraints")))

        citations = list(dict.fromkeys(prediction.get("evidence_ids", [])))
        gold_evidence = set(case["gold_evidence_ids"])
        citation_total += len(citations)
        citation_correct += sum(item in gold_evidence for item in citations)
        evidence_total += len(gold_evidence)
        evidence_covered += len(gold_evidence & set(citations))
        claims = prediction.get("claims", [])
        claim_total += len(claims)
        unsupported_claims += sum(not item.get("evidence_ids") for item in claims)
        for pair in prediction.get("citation_pairs", []):
            evidence = evidence_by_id.get(pair.get("evidence_id"))
            reference_total += 1
            wrong_reference += int(bool(
                evidence is None
                or evidence.get("model_id") != pair.get("model_id")
                or (pair.get("region") and evidence.get("region") not in {None, pair.get("region")})
            ))
        if case["category"] == "source_conflict":
            conflict_total += 1
            conflict_pass += int(bool(prediction.get("unknown_or_conflict_reported")))

        retrieved = prediction.get("retrieved_model_ids")
        if retrieved is not None and expected:
            retrieval_total += len(expected)
            retrieval_hit += len(set(retrieved[:5]) & expected)
            ndcgs.append(_ndcg(retrieved, expected, 5))

        required_tools = set(case["required_tools"])
        actual_tools = set(prediction.get("tools_used", []))
        if prediction["experiment_group"] in {"agentic_rag", "agentic_rag_checker"}:
            tool_total += 1
            tool_pass += int(required_tools.issubset(actual_tools))
            necessary_total += len(required_tools)
            necessary_hit += len(required_tools & actual_tools)
            if case["multihop"]:
                multihop_total += 1
                order_total += 1
                multihop_pass += int(bool(prediction.get("multihop_pass")))
                order_pass += int(bool(prediction.get("tool_order_pass")))
            blocked = prediction.get("blocked_unauthorized_or_out_of_order", [])
            blocked_total += len(blocked)
            blocked_calls += sum(bool(item.get("blocked")) for item in blocked)
            if prediction.get("degraded_states"):
                degrade_total += 1
                degrade_visible += int(bool(prediction.get("degradation_visible")))

        schema_pass = bool(prediction.get("schema_pass"))
        task_pass = schema_pass and actual == expected and actual_abstain == expected_abstain
        if case["multihop"] and prediction["experiment_group"] in {"agentic_rag", "agentic_rag_checker"}:
            task_pass = task_pass and bool(prediction.get("multihop_pass"))
        e2e_pass += int(task_pass)
        if prediction.get("error_category"):
            api_errors[str(prediction["error_category"])] += 1
        for usage_record in prediction.get("usage_records", []):
            model_latency_ms[str(usage_record.get("model") or "unknown")] += float(
                usage_record.get("latency_ms", 0)
            )
            retry_count += max(0, int(usage_record.get("attempts", 1)) - 1)
            if not usage_record.get("success"):
                status = usage_record.get("status_code")
                api_errors[f"http_{status}" if status else "provider_error"] += 1
            if usage_record.get("cache_hit") is not None:
                cache_observations += 1
                cache_hits += int(bool(usage_record.get("cache_hit")))
        for trace in prediction.get("public_trace", []):
            tool_latency_ms[str(trace.get("tool") or "unknown")] += float(
                trace.get("duration_ms", 0)
            )
        rows.append(
            {
                "case_id": case["case_id"],
                "split": case["split"],
                "expected_model_ids": sorted(expected),
                "actual_model_ids": sorted(actual),
                "candidate_exact": actual == expected,
                "abstention_pass": actual_abstain == expected_abstain,
                "schema_pass": schema_pass,
                "end_to_end_pass": task_pass,
            }
        )

    precision_denominator = abstain_tp + abstain_fp
    recall_denominator = abstain_tp + abstain_fn
    abstain_precision = abstain_tp / precision_denominator if precision_denominator else None
    abstain_recall = abstain_tp / recall_denominator if recall_denominator else None
    abstain_f1 = (
        2 * abstain_precision * abstain_recall / (abstain_precision + abstain_recall)
        if abstain_precision is not None and abstain_recall is not None
        and abstain_precision + abstain_recall
        else None
    )
    latencies = [float(item.get("latency_ms", 0.0)) for item in predictions]
    input_tokens = sum(int(item.get("usage", {}).get("input_tokens", 0)) for item in predictions)
    output_tokens = sum(int(item.get("usage", {}).get("output_tokens", 0)) for item in predictions)
    cost = sum(float(item.get("usage", {}).get("estimated_cost_cny", 0.0)) for item in predictions)
    model_latency_total = sum(model_latency_ms.values())
    tool_latency_total = sum(tool_latency_ms.values())
    return {
        "case_count": len(predictions),
        "task_quality": {
            "end_to_end_task_completion": ratio(e2e_pass, len(predictions)),
            "correct_candidate_recall": ratio(candidate_hit, candidate_gold),
            "recommended_candidate_precision": ratio(predicted_correct, predicted_total),
            "field_level_hard_constraint_correctness": ratio(hard_pass, hard_total),
            "task_level_hard_constraint_satisfaction": ratio(hard_task_pass, hard_task_total),
            "compliant_candidate_false_kill_rate": ratio(false_kills, candidate_gold),
            "violating_candidate_recommendation_rate": ratio(violations, recommendation_total),
            "abstention_accuracy": ratio(abstain_correct, len(predictions)),
            "abstention_precision": {"value": round(abstain_precision, 6) if abstain_precision is not None else None, "status": "measured" if abstain_precision is not None else "N/A"},
            "abstention_recall": {"value": round(abstain_recall, 6) if abstain_recall is not None else None, "status": "measured" if abstain_recall is not None else "N/A"},
            "abstention_f1": {"value": round(abstain_f1, 6) if abstain_f1 is not None else None, "status": "measured" if abstain_f1 is not None else "N/A"},
            "unknown_conflict_handling": ratio(unknown_pass, unknown_total),
            "unsupported_constraint_identification": ratio(unsupported_pass, unsupported_total),
        },
        "evidence_quality": {
            "recall_at_5": ratio(retrieval_hit, retrieval_total),
            "ndcg_at_5": {"value": round(statistics.fmean(ndcgs), 6) if ndcgs else None, "denominator": len(ndcgs), "status": "measured" if ndcgs else "N/A"},
            "citation_correctness": ratio(citation_correct, citation_total),
            "critical_evidence_coverage": ratio(evidence_covered, evidence_total),
            "unsupported_external_fact_rate": ratio(unsupported_claims, claim_total),
            "wrong_model_or_region_reference_rate": ratio(wrong_reference, reference_total),
            "source_conflict_preservation": ratio(conflict_pass, conflict_total),
        },
        "agent_capability": {
            "tool_selection_accuracy": ratio(tool_pass, tool_total),
            "necessary_tool_coverage": ratio(necessary_hit, necessary_total),
            "dependent_multihop_completion": ratio(multihop_pass, multihop_total),
            "tool_order_accuracy": ratio(order_pass, order_total),
            "unauthorized_or_out_of_order_block_rate": ratio(blocked_calls, blocked_total),
            "average_tool_calls": round(statistics.fmean(float(item.get("tool_call_count", 0)) for item in predictions), 3) if predictions else None,
            "limit_reached_tasks": sum(bool(item.get("limit_reached")) for item in predictions),
            "degradation_visibility": ratio(degrade_visible, degrade_total),
        },
        "engineering": {
            "average_latency_ms": round(statistics.fmean(latencies), 3) if latencies else None,
            "p50_latency_ms": percentile(latencies, 0.50),
            "p95_latency_ms": percentile(latencies, 0.95),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "average_input_tokens_per_task": round(input_tokens / len(predictions), 3) if predictions else None,
            "average_output_tokens_per_task": round(output_tokens / len(predictions), 3) if predictions else None,
            "estimated_cost_cny": round(cost, 8),
            "average_cost_cny_per_task": round(cost / len(predictions), 8) if predictions else None,
            "model_latency_breakdown": {
                model: {
                    "duration_ms": round(duration, 3),
                    "share": round(duration / model_latency_total, 6) if model_latency_total else None,
                }
                for model, duration in sorted(model_latency_ms.items())
            },
            "tool_latency_breakdown": {
                tool: {
                    "duration_ms": round(duration, 3),
                    "share": round(duration / tool_latency_total, 6) if tool_latency_total else None,
                }
                for tool, duration in sorted(tool_latency_ms.items())
            },
            "cache_hit_rate": ratio(cache_hits, cache_observations),
            "retry_count": retry_count,
            "api_error_distribution": dict(sorted(api_errors.items())),
        },
        "cases": rows,
    }


def score_stability(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in predictions:
        grouped[(row["experiment_group"], row["case_id"])].append(row)
    by_group: dict[str, dict[str, Any]] = {}
    for group in sorted({key[0] for key in grouped}):
        cases = [rows for (name, _), rows in grouped.items() if name == group and len(rows) >= 3]
        candidate_consistent = abstain_consistent = tool_consistent = checker_consistent = 0
        ranking_jaccards: list[float] = []
        for rows in cases:
            rows = sorted(rows, key=lambda item: item["repetition"])
            candidate_sets = [tuple(sorted(item.get("recommended_model_ids", []))) for item in rows]
            candidate_consistent += int(len(set(candidate_sets)) == 1)
            abstain_consistent += int(len({bool(item.get("abstained")) for item in rows}) == 1)
            tool_consistent += int(
                len({tuple(item.get("tools_used", [])) for item in rows}) == 1
            )
            checker_values = [item.get("checker_fingerprint") for item in rows]
            if all(checker_values):
                checker_consistent += int(len(set(checker_values)) == 1)
            first = list(rows[0].get("recommended_model_ids", []))
            for other in rows[1:]:
                second = list(other.get("recommended_model_ids", []))
                union = set(first) | set(second)
                ranking_jaccards.append(len(set(first) & set(second)) / len(union) if union else 1.0)
        by_group[group] = {
            "three_run_case_count": len(cases),
            "final_candidate_set_consistency": ratio(candidate_consistent, len(cases)),
            "abstention_consistency": ratio(abstain_consistent, len(cases)),
            "tool_path_consistency": ratio(tool_consistent, len(cases)) if group.startswith("agentic") else {"numerator": 0, "denominator": 0, "rate": None, "status": "N/A"},
            "checker_workflow_fingerprint_consistency": ratio(checker_consistent, len(cases)) if group == "agentic_rag_checker" else {"numerator": 0, "denominator": 0, "rate": None, "status": "N/A"},
            "ranking_jaccard": round(statistics.fmean(ranking_jaccards), 6) if ranking_jaccards else None,
            "latency_coefficient_of_variation": _coefficient_of_variation([float(item.get("latency_ms", 0)) for rows in cases for item in rows]),
            "cost_coefficient_of_variation": _coefficient_of_variation([float(item.get("usage", {}).get("estimated_cost_cny", 0)) for rows in cases for item in rows]),
        }
    return by_group


def _coefficient_of_variation(values: list[float]) -> float | None:
    if len(values) < 2 or statistics.fmean(values) == 0:
        return None
    return round(statistics.pstdev(values) / statistics.fmean(values), 6)
