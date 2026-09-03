"""Freeze-time validator and future scorer for the V2-6C second Laptop holdout.

The ``--validate-gold`` path is intentionally not an Agent evaluation. It
validates the immutable case contract, builds the existing Product Pack into
an external temporary SQLite database, checks evidence identity, and asks the
deterministic Checker to reproduce eligible gold sets. The ``--results`` path
is reserved for one explicitly authorized future E2E run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from smartbuy.domain_packs import DomainPackLoader, DomainPackValidationError
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.tools.domain import DomainConstraintCheckerTool, DomainReadonlyRepository


ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "smartbuy" / "eval" / "v2_6c_r2_laptop_holdout.jsonl"
SCHEMA = ROOT / "smartbuy" / "eval" / "v2_6c_r2_laptop_holdout.schema.json"
POLICY = ROOT / "smartbuy" / "eval" / "v2_6c_r2_laptop_scoring_policy.json"
OLD_CASES = ROOT / "smartbuy" / "eval" / "v2_6a_laptop_cases.jsonl"
DOMAIN_PACK = ROOT / "smartbuy" / "domain_packs" / "laptop"
PRODUCT_PACK = ROOT / "smartbuy" / "product_packs" / "examples" / "laptop-v1" / "pack.json"

EXPECTED_CATEGORIES = {
    "exact_configuration_or_sku": 4,
    "same_family_configuration": 3,
    "same_family_region": 3,
    "explicit_comparison": 2,
    "catalog_filter": 2,
    "unknown_evidence": 2,
    "natural_constraint": 2,
    "evidence_identity_or_region": 2,
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sorted(values: list[str]) -> list[str]:
    return sorted(dict.fromkeys(values))


def _active_hard_constraints(case: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "field": item["field"],
            "operator": item["operator"],
            "value": item["normalized_value"],
            "unit": item["unit"],
        }
        for item in case["gold"]["constraints"]
        if item["active"]
        and item["status"] == "supported"
        and item["hard_or_soft"] == "hard"
    ]


def _validate_sqlite(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("products", "source_records", "evidence_records")
        }
    finally:
        connection.close()
    if integrity != "ok" or foreign_keys:
        raise ValueError("temporary gold-validation SQLite failed integrity checks")
    return counts


def _validate_scope(case: dict[str, Any], products: dict[str, dict[str, Any]]) -> None:
    gold = case["gold"]
    scope = gold["scope"]
    product_ids = scope["product_ids"]
    if not set(product_ids) <= set(products):
        raise ValueError(f"{case['case_id']}: scope references an unknown product")
    scoped = [products[product_id] for product_id in product_ids]
    expected_family_ids = _sorted([str(item["attributes"]["family_id"]) for item in scoped])
    expected_configuration_ids = _sorted(
        [str(item["attributes"]["configuration_id"]) for item in scoped]
    )
    expected_regions = _sorted([str(item["region"]) for item in scoped])
    if _sorted(scope["family_ids"]) != expected_family_ids:
        raise ValueError(f"{case['case_id']}: family scope is inconsistent")
    if _sorted(scope["configuration_ids"]) != expected_configuration_ids:
        raise ValueError(f"{case['case_id']}: configuration scope is inconsistent")
    if _sorted(scope["regions"]) != expected_regions:
        raise ValueError(f"{case['case_id']}: region scope is inconsistent")
    if any(quote not in case["question"] for quote in scope["mentioned_quotes"]):
        raise ValueError(f"{case['case_id']}: mentioned quote is not an exact input slice")
    if scope["scope_type"] == "exact_configuration" and len(product_ids) != 1:
        raise ValueError(f"{case['case_id']}: exact scope is not unique")
    if scope["scope_type"] == "explicit_comparison" and (
        len(product_ids) < 2 or not scope["explicit_comparison"]
    ):
        raise ValueError(f"{case['case_id']}: explicit comparison scope is invalid")
    if scope["scope_type"] == "catalog_filter" and set(product_ids) != set(products):
        raise ValueError(f"{case['case_id']}: catalog filter does not contain the full catalog")
    if scope["clarification_required"] and not gold["clarification_required"]:
        raise ValueError(f"{case['case_id']}: identity clarification was discarded")
    if scope["clarification_required"] != (
        scope["resolution_status"] == "needs_clarification"
    ):
        raise ValueError(f"{case['case_id']}: identity clarification state differs")
    if not set(gold["final_candidate_ids"]) <= set(product_ids):
        raise ValueError(f"{case['case_id']}: final gold expands candidate scope")
    if set(gold["forbidden_evidence_product_ids"]) & set(product_ids):
        raise ValueError(f"{case['case_id']}: forbidden evidence is inside usable scope")
    if gold["clarification_required"] and (
        gold["checker_candidate_ids"] or gold["final_candidate_ids"]
    ):
        raise ValueError(f"{case['case_id']}: clarification case grants a candidate")


def _validate_constraints(case: dict[str, Any], pack: Any) -> None:
    hard_fields = set(pack.pack.policies["checker"]["hard_fields"])
    for item in case["gold"]["constraints"]:
        field = pack.canonical_field(item["field"])
        pack.validate_operator(field, item["operator"])
        if item["active"] and item["status"] != "supported":
            raise ValueError(f"{case['case_id']}: non-supported constraint is active")
        if item["active"] and item["hard_or_soft"] == "hard" and field not in hard_fields:
            raise ValueError(f"{case['case_id']}: active hard field is outside Checker policy")
        if item["active"]:
            try:
                values = (
                    item["normalized_value"]
                    if item["operator"] in {"in", "not_in", "range"}
                    else [item["normalized_value"]]
                )
                if not isinstance(values, list):
                    raise ValueError("set and range constraints require a list")
                for value in values:
                    pack.normalize_value(field, value, unit=item["unit"])
            except (TypeError, ValueError, DomainPackValidationError) as exc:
                raise ValueError(
                    f"{case['case_id']}: constraint value is not pack-normalizable"
                ) from exc


def _validate_evidence(case: dict[str, Any], products: dict[str, dict[str, Any]]) -> int:
    checked = 0
    for requirement in case["gold"]["key_evidence"]:
        product_id = requirement["product_id"]
        field_id = requirement["field_id"]
        if product_id not in products:
            raise ValueError(f"{case['case_id']}: Evidence product is unknown")
        product = products[product_id]
        matching = [
            item
            for item in product["evidence"]
            if item["field_id"] == field_id
            and item["region"] == product["region"]
            and item["variant_key"] == product["variant_key"]
        ]
        expected_ids = set(requirement["evidence_ids"])
        actual_ids = {item["evidence_id"] for item in matching}
        if requirement["expected_status"] == "unknown":
            if expected_ids or matching or product["attributes"].get(field_id) is not None:
                raise ValueError(f"{case['case_id']}: unknown field has governed support")
        else:
            if not expected_ids or not expected_ids <= actual_ids:
                raise ValueError(f"{case['case_id']}: required Evidence is unavailable")
            for item in matching:
                if item["evidence_id"] in expected_ids and (
                    not item["source_id"] or item["normalized_value"] is None
                ):
                    raise ValueError(f"{case['case_id']}: Evidence is incomplete")
        checked += 1
    return checked


def validate_gold() -> dict[str, Any]:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if _sha(CASES) != policy["frozen_case_sha256"]:
        raise ValueError("frozen case SHA-256 differs from scoring policy")
    if _sha(PRODUCT_PACK) != policy["product_pack_sha256"]:
        raise ValueError("Product Pack SHA-256 differs from scoring policy")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    cases = _load_jsonl(CASES)
    if len(cases) != 20:
        raise ValueError("second holdout must contain exactly 20 frozen cases")
    for case in cases:
        validator.validate(case)
    case_ids = [case["case_id"] for case in cases]
    expected_ids = [f"laptop-r2-{number:03d}" for number in range(1, 21)]
    if case_ids != expected_ids or len(case_ids) != len(set(case_ids)):
        raise ValueError("case IDs must be unique and sequential")
    if Counter(case["category"] for case in cases) != Counter(EXPECTED_CATEGORIES):
        raise ValueError("category distribution differs from the frozen design")
    questions = [case["question"].strip() for case in cases]
    old_questions = {case["question"].strip() for case in _load_jsonl(OLD_CASES)}
    if len(questions) != len(set(questions)) or set(questions) & old_questions:
        raise ValueError("a second-holdout question is duplicated")

    evidence_requirements = 0
    checker_cases = 0
    with tempfile.TemporaryDirectory(prefix="proofpick-v2-6c-r2-gold-") as temporary:
        pack = DomainPackLoader().load(DOMAIN_PACK)
        manager = DomainProductPackManager(
            Path(temporary) / "data",
            domain_pack_path=DOMAIN_PACK,
        )
        snapshot = manager.publish(manager.stage(PRODUCT_PACK).data_version)
        counts = _validate_sqlite(snapshot.database_path)
        repository = DomainReadonlyRepository(snapshot, pack)
        products = repository.load()
        checker = DomainConstraintCheckerTool(repository)
        for case in cases:
            _validate_scope(case, products)
            _validate_constraints(case, pack)
            evidence_requirements += _validate_evidence(case, products)
            constraints = _active_hard_constraints(case)
            checker_ids = case["gold"]["checker_candidate_ids"]
            if constraints and not case["gold"]["clarification_required"]:
                if not checker_ids:
                    raise ValueError(f"{case['case_id']}: hard constraints omit Checker input")
                result = checker.run(constraints, candidate_ids=checker_ids)
                if result.status != "success":
                    raise ValueError(f"{case['case_id']}: deterministic Checker failed")
                eligible = sorted(
                    item["product_id"] for item in result.data["results"] if item["eligible"]
                )
                if eligible != sorted(case["gold"]["final_candidate_ids"]):
                    raise ValueError(f"{case['case_id']}: Checker and eligible gold differ")
                checker_cases += 1
            elif checker_ids:
                raise ValueError(f"{case['case_id']}: Checker gold has no active hard constraints")
            if case["gold"]["result_kind"] == "eligible" and not case["gold"]["final_candidate_ids"]:
                raise ValueError(f"{case['case_id']}: positive case has no eligible product")
            if case["gold"]["result_kind"] in {"abstain", "clarify"} and case["gold"]["final_candidate_ids"]:
                raise ValueError(f"{case['case_id']}: negative case grants a final product")
    return {
        "case_count": len(cases),
        "unique_case_ids": len(set(case_ids)),
        "category_distribution": dict(sorted(Counter(case["category"] for case in cases).items())),
        "schema_valid": True,
        "questions_distinct_from_original_30": True,
        "sqlite_integrity": "ok",
        "sqlite_foreign_key_violations": 0,
        "sqlite_counts": counts,
        "checker_gold_cases": checker_cases,
        "evidence_requirements_checked": evidence_requirements,
        "agent_e2e_runs": 0,
        "paid_api_calls": 0,
        "case_sha256": _sha(CASES),
    }


def _constraint_key(item: dict[str, Any]) -> str:
    payload = {
        "field": item["field"],
        "operator": item["operator"],
        "normalized_value": item.get("normalized_value", item.get("value")),
        "unit": item.get("unit"),
        "hard_or_soft": item.get("hard_or_soft", "hard"),
        "status": item.get("status", "supported"),
        "active": item.get("active", True),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _is_subsequence(required: list[str], actual: list[str]) -> bool:
    position = 0
    for item in actual:
        if position < len(required) and item == required[position]:
            position += 1
    return position == len(required)


def score_results(results_path: Path) -> dict[str, Any]:
    """Score a future immutable E2E result without changing frozen gold."""

    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    results = json.loads(results_path.read_text(encoding="utf-8"))
    if results.get("frozen_case_sha256") != policy["frozen_case_sha256"]:
        raise ValueError("result belongs to another case freeze")
    cases = {case["case_id"]: case for case in _load_jsonl(CASES)}
    rows = results.get("cases")
    result_ids = [item.get("case_id") for item in rows] if isinstance(rows, list) else []
    if (
        not isinstance(rows, list)
        or len(rows) != len(cases)
        or len(result_ids) != len(set(result_ids))
        or set(result_ids) != set(cases)
    ):
        raise ValueError("result must contain each frozen case exactly once")
    task_correct = 0
    tp = fp = fn = evidence_hit = evidence_total = 0
    wrong_configuration = wrong_region = scope_leakage = checker_leakage = 0
    unknown_overclaimed = clarification_bypass = sufficient_empty = eligible_cases = 0
    scored = []
    for row in rows:
        case = cases[row["case_id"]]
        gold = case["gold"]
        scope = row.get("product_scope", {})
        scope_ok = all(
            _sorted(scope.get(key, [])) == _sorted(gold["scope"][key])
            for key in ("family_ids", "product_ids", "configuration_ids", "regions")
        ) and all(
            scope.get(key) == gold["scope"][key]
            for key in (
                "scope_type",
                "explicit_comparison",
                "clarification_required",
                "resolution_status",
            )
        )
        gold_constraints = {
            _constraint_key(item)
            for item in gold["constraints"]
            if item["active"] and item["status"] == "supported" and item["hard_or_soft"] == "hard"
        }
        actual_constraints = {
            _constraint_key(item)
            for item in row.get("active_constraints", [])
            if item.get("active", True)
            and item.get("status", "supported") == "supported"
            and item.get("hard_or_soft", "hard") == "hard"
        }
        tp += len(gold_constraints & actual_constraints)
        fp += len(actual_constraints - gold_constraints)
        fn += len(gold_constraints - actual_constraints)
        tools = row.get("tools_used", [])
        tool_ok = _is_subsequence(gold["tool_path"]["required_order"], tools) and not (
            set(gold["tool_path"]["forbidden"]) & set(tools)
        )
        checker_ids = set(row.get("checker_candidate_ids", []))
        checker_gold = set(gold["checker_candidate_ids"])
        checker_leakage += len(checker_ids - checker_gold)
        final_ids = set(row.get("final_candidate_ids", []))
        final_gold = set(gold["final_candidate_ids"])
        scope_ids = set(gold["scope"]["product_ids"])
        scope_leakage += len(set(row.get("observed_product_ids", [])) - scope_ids)
        wrong_configuration += len(final_ids - scope_ids)
        region_by_product = row.get("candidate_regions", {})
        wrong_region += sum(
            1 for product_id in final_ids
            if region_by_product.get(product_id) not in gold["scope"]["regions"]
        )
        evidence = row.get("evidence", [])
        for requirement in gold["key_evidence"]:
            if requirement["expected_status"] == "unknown":
                unknown_overclaimed += sum(
                    1 for item in evidence
                    if item.get("product_id") == requirement["product_id"]
                    and item.get("field_id") == requirement["field_id"]
                    and item.get("status") == "matched"
                )
                continue
            if requirement["product_id"] not in final_ids:
                continue
            evidence_total += 1
            expected_ids = set(requirement["evidence_ids"])
            if any(
                item.get("product_id") == requirement["product_id"]
                and item.get("field_id") == requirement["field_id"]
                and item.get("status") == requirement["expected_status"]
                and item.get("evidence_id") in expected_ids
                for item in evidence
            ):
                evidence_hit += 1
        clarification_bypass += int(
            gold["clarification_required"] and bool(tools or final_ids)
        )
        if gold["result_kind"] == "eligible":
            eligible_cases += 1
            sufficient_empty += int(not final_ids)
        task_ok = all(
            (
                scope_ok,
                actual_constraints == gold_constraints,
                tool_ok,
                checker_ids == checker_gold,
                row.get("result_kind") == gold["result_kind"],
                final_ids == final_gold,
                row.get("clarification_required") == gold["clarification_required"],
                row.get("abstain_reason") == gold["abstain_reason"],
            )
        )
        task_correct += int(task_ok)
        scored.append({"case_id": row["case_id"], "task_correct": task_ok})
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    metrics = {
        "task_accuracy": {"numerator": task_correct, "denominator": len(cases)},
        "clear_hard_constraint": {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
        "recommendation_evidence_coverage": {
            "numerator": evidence_hit,
            "denominator": evidence_total,
        },
        "wrong_configuration_recommendations": wrong_configuration,
        "wrong_region_recommendations": wrong_region,
        "candidate_scope_leakage": scope_leakage,
        "checker_scope_leakage": checker_leakage,
        "unknown_overclaimed": unknown_overclaimed,
        "clarification_bypass": clarification_bypass,
        "sufficient_evidence_empty_recommendation": {
            "numerator": sufficient_empty,
            "denominator": eligible_cases,
        },
    }
    return {"schema_version": policy["schema_version"], "metrics": metrics, "cases": scored}


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate-gold", action="store_true")
    group.add_argument("--results", type=Path)
    arguments = parser.parse_args()
    output = validate_gold() if arguments.validate_gold else score_results(arguments.results)
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
