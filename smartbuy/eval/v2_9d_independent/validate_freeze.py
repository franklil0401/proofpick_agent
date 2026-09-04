"""Validate RC2 evaluation gold without importing production decision code."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _value(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) and "value" in value else value


def _records() -> tuple[dict[str, dict[str, Any]], set[tuple[str, str]]]:
    products: dict[str, dict[str, Any]] = {}
    evidence: set[tuple[str, str]] = set()
    monitor = json.loads((ROOT / "smartbuy/data/catalog/monitors_v1.json").read_text(encoding="utf-8"))
    for row in monitor["products"]:
        products[row["model_id"]] = {**row, "product_id": row["model_id"], "domain_id": "monitor"}
    for row in _jsonl(ROOT / "smartbuy/data/processed/evidence_records.jsonl"):
        evidence.add((row["model_id"], row["normalized_field"]))
    for domain in ("laptop", "headphone"):
        pack = json.loads((ROOT / f"smartbuy/product_packs/examples/{domain}-v1/pack.json").read_text(encoding="utf-8"))
        for row in pack["products"]:
            products[row["product_id"]] = {
                "product_id": row["product_id"], "domain_id": domain, "brand": row["brand"],
                "region": row["market"], **{key: _value(value) for key, value in row["attributes"].items()},
            }
        for row in pack["evidence"]:
            evidence.add((row["product_id"], row["field_id"]))
    return products, evidence


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().casefold().replace("×", "x")
    return value


def _satisfies(actual: Any, operator: str, expected: Any) -> bool:
    if actual is None:
        return False
    if operator == "eq":
        return _norm(actual) == _norm(expected)
    if operator == "gte":
        return float(actual) >= float(expected)
    if operator == "lte":
        return float(actual) <= float(expected)
    if operator == "contains_all":
        return {_norm(item) for item in expected} <= {_norm(item) for item in actual}
    raise ValueError(operator)


def _signature(row: dict[str, Any]) -> str:
    payload = {
        "domain_id": row["domain_id"], "category": row["category"],
        "expected_kind": row["expected_kind"], "expected_product_ids": sorted(row["expected_product_ids"]),
        "expected_constraints": sorted(row["expected_constraints"], key=lambda item: (item["field"], item["operator"])),
        "required_evidence": sorted(row["required_evidence"], key=lambda item: (item["product_id"], item["field_id"])),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> int:
    trusted = _jsonl(HERE / "trusted_cases.jsonl")
    online = _jsonl(HERE / "online_cases.jsonl")
    trusted_schema = json.loads((HERE / "trusted_case.schema.json").read_text(encoding="utf-8"))
    online_schema = json.loads((HERE / "online_case.schema.json").read_text(encoding="utf-8"))
    for row in trusted:
        jsonschema.validate(row, trusted_schema)
    for row in online:
        jsonschema.validate(row, online_schema)
    products, evidence = _records()
    issues: list[str] = []
    evidence_checks = constraint_checks = exact_set_checks = 0
    for case in trusted:
        domain_products = {key: value for key, value in products.items() if value["domain_id"] == case["domain_id"]}
        unknown = set(case["expected_product_ids"]) - set(domain_products)
        if unknown:
            issues.append(f"{case['case_id']}: unknown products {sorted(unknown)}")
        for item in case["required_evidence"]:
            evidence_checks += 1
            if (item["product_id"], item["field_id"]) not in evidence:
                issues.append(f"{case['case_id']}: missing evidence {item['product_id']}/{item['field_id']}")
        constraints = case["expected_constraints"]
        for product_id in case["expected_product_ids"]:
            for item in constraints:
                constraint_checks += 1
                if not _satisfies(domain_products[product_id].get(item["field"]), item["operator"], item["value"]):
                    issues.append(f"{case['case_id']}: expected product violates {item['field']}")
        if constraints and case["category"] in {"catalog_filter", "no_match"}:
            exact_set_checks += 1
            derived = {
                product_id for product_id, product in domain_products.items()
                if all(_satisfies(product.get(item["field"]), item["operator"], item["value"]) for item in constraints)
            }
            if derived != set(case["expected_product_ids"]):
                issues.append(f"{case['case_id']}: exact candidate set expected={sorted(case['expected_product_ids'])} derived={sorted(derived)}")

    old_trusted = _jsonl(ROOT / "smartbuy/eval/v2_9b_independent/trusted_cases.jsonl")
    old_online = _jsonl(ROOT / "smartbuy/eval/v2_9b_independent/online_cases_rc2.jsonl")
    question_duplicates = sorted({row["question"] for row in trusted} & {row["question"] for row in old_trusted})
    def actionable(row: dict[str, Any]) -> bool:
        return bool(row["expected_constraints"] or row["required_evidence"])

    signature_duplicates = len(
        {_signature(row) for row in trusted if actionable(row)}
        & {_signature(row) for row in old_trusted if actionable(row)}
    )
    online_duplicates = len(
        {(row["query"], row["target_model"], row["region"]) for row in online}
        & {(row["query"], row["target_model"], row["region"]) for row in old_online}
    )
    if question_duplicates:
        issues.append(f"historical exact questions: {question_duplicates}")
    if signature_duplicates:
        issues.append(f"historical exact gold signatures: {signature_duplicates}")
    if online_duplicates:
        issues.append(f"historical exact online triples: {online_duplicates}")
    categories = Counter(row["category"] for row in trusted)
    result = {
        "status": "passed" if not issues else "failed", "trusted_cases": len(trusted), "online_cases": len(online),
        "domain_counts": {domain: sum(row["domain_id"] == domain for row in trusted) for domain in ("monitor", "laptop", "headphone")},
        "category_counts": dict(sorted(categories.items())), "product_ids": len(products),
        "gold_evidence_pairs_checked": evidence_checks, "expected_constraint_product_checks": constraint_checks,
        "exact_candidate_set_checks": exact_set_checks, "historical_exact_question_duplicates": len(question_duplicates),
        "historical_exact_actionable_gold_signature_duplicates": signature_duplicates,
        "historical_exact_online_triple_duplicates": online_duplicates, "issues": issues,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
