"""Deterministic scorer for an immutable V2-6C-R3 validation round."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from smartbuy.decision_core.canonical import CanonicalValueNormalizer
from smartbuy.domain_packs import DomainPackLoader


ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "smartbuy/eval/v2_6c_r3_validation_round1.jsonl"
POLICY = ROOT / "smartbuy/eval/v2_6c_r3_validation_round1_policy.json"
DOMAIN_PACK = ROOT / "smartbuy/domain_packs/laptop"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_cases() -> list[dict[str, Any]]:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if _sha(CASES) != policy["case_sha256"]:
        raise ValueError("validation case SHA-256 differs from frozen policy")
    return [
        json.loads(line)
        for line in CASES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _stable(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _constraint_key(item: dict[str, Any], pack: Any) -> str:
    field = item["field"]
    definition = pack.fields[field]
    value = item.get("normalized_value", item.get("value"))
    operator = item["operator"]
    unit = item.get("unit")
    if operator in {"in", "not_in", "range"}:
        normalized = [
            CanonicalValueNormalizer.normalize(definition, member, unit=unit).to_native()
            for member in value
        ]
        if operator in {"in", "not_in"}:
            normalized = sorted(normalized, key=str)
    else:
        normalized = CanonicalValueNormalizer.normalize(
            definition, value, unit=unit
        ).to_native()
    return _stable(
        {
            "field": field,
            "operator": operator,
            "value": normalized,
            "unit": definition.unit,
            "hard_or_soft": item.get("hard_or_soft", "hard"),
        }
    )


def _subsequence(required: list[str], actual: list[str]) -> bool:
    position = 0
    for tool in actual:
        if position < len(required) and tool == required[position]:
            position += 1
    return position == len(required)


def score_results(results_path: Path) -> dict[str, Any]:
    cases = {item["case_id"]: item for item in _load_cases()}
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    if payload.get("frozen_case_sha256") != _sha(CASES):
        raise ValueError("result belongs to another validation freeze")
    rows = payload.get("cases")
    if not isinstance(rows, list) or len(rows) != len(cases):
        raise ValueError("result does not contain exactly 24 cases")
    ids = [item.get("case_id") for item in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(cases):
        raise ValueError("result case IDs differ from frozen validation cases")

    pack = DomainPackLoader().load(DOMAIN_PACK)
    task_correct = tp = fp = fn = 0
    evidence_hit = evidence_total = 0
    wrong_configuration = wrong_region = scope_leakage = checker_leakage = 0
    unknown_overclaimed = clarification_bypass = non_domain = 0
    sufficient_empty = eligible_count = 0
    scored_rows: list[dict[str, Any]] = []
    category = Counter()
    first_errors = Counter()
    for row in rows:
        case = cases[row["case_id"]]
        gold = case["gold"]
        scope = row["product_scope"]
        scope_ok = all(
            sorted(scope.get(key, [])) == sorted(gold["scope"][key])
            for key in ("family_ids", "product_ids", "configuration_ids", "regions")
        ) and all(
            scope.get(key) == gold["scope"][key]
            for key in (
                "scope_type", "explicit_comparison", "clarification_required",
                "resolution_status",
            )
        )
        expected_constraints = {
            _constraint_key(item, pack)
            for item in gold["constraints"]
            if item["active"] and item["status"] == "supported" and item["hard_or_soft"] == "hard"
        }
        actual_constraints = {
            _constraint_key(item, pack)
            for item in row.get("active_constraints", [])
            if item.get("active", True)
            and item.get("status", "supported") == "supported"
            and item.get("hard_or_soft", "hard") == "hard"
            and item.get("field") in pack.fields
        }
        non_domain += sum(
            item.get("field") not in pack.fields for item in row.get("active_constraints", [])
        )
        row_tp = len(expected_constraints & actual_constraints)
        row_fp = len(actual_constraints - expected_constraints)
        row_fn = len(expected_constraints - actual_constraints)
        tp += row_tp
        fp += row_fp
        fn += row_fn
        tools = row.get("tools_used", [])
        tool_ok = _subsequence(gold["tool_path"]["required_order"], tools) and not (
            set(gold["tool_path"]["forbidden"]) & set(tools)
        )
        checker_actual = set(row.get("checker_candidate_ids", []))
        checker_gold = set(gold["checker_candidate_ids"])
        checker_ok = checker_actual == checker_gold
        checker_leakage += len(checker_actual - set(gold["scope"]["product_ids"]))
        final_actual = set(row.get("final_candidate_ids", []))
        final_gold = set(gold["final_candidate_ids"])
        final_ok = final_actual == final_gold
        scope_ids = set(gold["scope"]["product_ids"])
        wrong_configuration += len(final_actual - scope_ids)
        wrong_region += sum(
            product_id in final_actual
            and row.get("candidate_regions", {}).get(product_id) not in gold["scope"]["regions"]
            for product_id in final_actual
        )
        scope_leakage += len(set(row.get("observed_product_ids", [])) - scope_ids)
        row_evidence = {
            (item.get("product_id"), item.get("field_id"), item.get("evidence_id"), item.get("status", "matched"))
            for item in row.get("evidence", [])
        }
        evidence_ok = True
        for required in gold["key_evidence"]:
            if required["expected_status"] == "unknown":
                if any(
                    product == required["product_id"] and field == required["field_id"] and status == "matched"
                    for product, field, _evidence, status in row_evidence
                ):
                    unknown_overclaimed += 1
                    evidence_ok = False
                continue
            if required["product_id"] not in final_gold:
                continue
            for evidence_id in required["evidence_ids"]:
                evidence_total += 1
                matched = (
                    required["product_id"], required["field_id"], evidence_id, "matched"
                ) in row_evidence
                evidence_hit += int(matched)
                evidence_ok &= matched
        result_ok = (
            row.get("result_kind") == gold["result_kind"]
            and row.get("clarification_required") == gold["clarification_required"]
            and row.get("abstain_reason") == gold["abstain_reason"]
        )
        if gold["clarification_required"] and (
            tools or checker_actual or final_actual
        ):
            clarification_bypass += 1
        if gold["result_kind"] == "eligible":
            eligible_count += 1
            sufficient_empty += int(not final_actual)
        checks = {
            "product_scope_resolution": scope_ok,
            "constraint_resolution": row_fp == 0 and row_fn == 0,
            "tool_orchestration": tool_ok,
            "checker_candidate_scope": checker_ok,
            "result_classification": result_ok,
            "final_candidate_selection": final_ok,
            "evidence_closure": evidence_ok,
        }
        first_error = next((name for name, passed in checks.items() if not passed), None)
        correct = first_error is None
        task_correct += int(correct)
        category[(case["category"], correct)] += 1
        if first_error:
            first_errors[first_error] += 1
        scored_rows.append(
            {
                "case_id": case["case_id"],
                "category": case["category"],
                "task_correct": correct,
                "first_error_node": first_error,
                "field_tp": row_tp,
                "field_fp": row_fp,
                "field_fn": row_fn,
                "wrong_recommendation": bool(final_actual - final_gold),
                "safety_failure": bool(
                    (final_actual - scope_ids)
                    or (checker_actual - scope_ids)
                    or (gold["clarification_required"] and (tools or final_actual))
                ),
            }
        )
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    evidence_rate = evidence_hit / evidence_total if evidence_total else 1.0
    empty_rate = sufficient_empty / eligible_count if eligible_count else 0.0
    thresholds = json.loads(POLICY.read_text(encoding="utf-8"))["thresholds"]
    gates = {
        "task_accuracy": task_correct / len(cases) >= thresholds["task_accuracy_min"],
        "clear_hard_constraint_f1": f1 >= thresholds["clear_hard_constraint_f1_min"],
        "recommendation_evidence_coverage": evidence_rate >= thresholds["recommendation_evidence_coverage_min"],
        "wrong_configuration_recommendations": wrong_configuration <= 0,
        "wrong_region_recommendations": wrong_region <= 0,
        "candidate_scope_leakage": scope_leakage <= 0,
        "checker_scope_leakage": checker_leakage <= 0,
        "unknown_overclaimed": unknown_overclaimed <= 0,
        "clarification_bypass": clarification_bypass <= 0,
        "non_domain_field_activations": non_domain <= 0,
        "sufficient_evidence_empty_recommendation_rate": empty_rate <= 0.1,
    }
    categories = {}
    for name in sorted({item["category"] for item in cases.values()}):
        categories[name] = {
            "numerator": category[(name, True)],
            "denominator": category[(name, True)] + category[(name, False)],
        }
    return {
        "task_accuracy": {"numerator": task_correct, "denominator": len(cases)},
        "category_accuracy": categories,
        "clear_hard_constraint": {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1,
        },
        "recommendation_evidence_coverage": {
            "numerator": evidence_hit, "denominator": evidence_total, "rate": evidence_rate,
        },
        "wrong_configuration_recommendations": wrong_configuration,
        "wrong_region_recommendations": wrong_region,
        "candidate_scope_leakage": scope_leakage,
        "checker_scope_leakage": checker_leakage,
        "unknown_overclaimed": unknown_overclaimed,
        "clarification_bypass": clarification_bypass,
        "non_domain_field_activations": non_domain,
        "sufficient_evidence_empty_recommendation": {
            "numerator": sufficient_empty, "denominator": eligible_count, "rate": empty_rate,
        },
        "first_error_nodes": dict(sorted(first_errors.items())),
        "cases": scored_rows,
        "joint_gates": gates,
        "all_joint_gates_passed": all(gates.values()),
    }
