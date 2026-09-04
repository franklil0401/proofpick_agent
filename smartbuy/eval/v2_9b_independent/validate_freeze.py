"""Validate independent V2-9B gold labels without production decision code."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _product_records() -> tuple[dict[str, dict[str, Any]], set[tuple[str, str]]]:
    products: dict[str, dict[str, Any]] = {}
    evidence: set[tuple[str, str]] = set()
    monitor = json.loads((ROOT / "smartbuy/data/catalog/monitors_v1.json").read_text(encoding="utf-8"))
    for row in monitor["products"]:
        product_id = row["model_id"]
        products[product_id] = {**row, "product_id": product_id}
    for row in _jsonl(ROOT / "smartbuy/data/processed/evidence_records.jsonl"):
        evidence.add((row["model_id"], row["normalized_field"]))
    for domain in ("laptop", "headphone"):
        pack = json.loads((ROOT / f"smartbuy/product_packs/examples/{domain}-v1/pack.json").read_text(encoding="utf-8"))
        for row in pack["products"]:
            products[row["product_id"]] = {
                "product_id": row["product_id"],
                "brand": row["brand"],
                "region": row["market"],
                **{key: _value(value) for key, value in row["attributes"].items()},
            }
        for row in pack["evidence"]:
            evidence.add((row["product_id"], row["field_id"]))
    return products, evidence


def _satisfies(actual: Any, operator: str, expected: Any) -> bool:
    if actual is None:
        return False
    if operator == "eq":
        if isinstance(actual, str) and isinstance(expected, str):
            return actual.casefold() == expected.casefold()
        return actual == expected
    if operator == "gte":
        return float(actual) >= float(expected)
    if operator == "lte":
        return float(actual) <= float(expected)
    if operator == "contains_all":
        values = {str(item).casefold() for item in actual}
        return {str(item).casefold() for item in expected} <= values
    raise ValueError(operator)


def main() -> int:
    trusted = _jsonl(HERE / "trusted_cases.jsonl")
    online = _jsonl(HERE / "online_cases.jsonl")
    trusted_schema = json.loads((HERE / "trusted_case.schema.json").read_text(encoding="utf-8"))
    online_schema = json.loads((HERE / "online_case.schema.json").read_text(encoding="utf-8"))
    for row in trusted:
        jsonschema.validate(row, trusted_schema)
    for row in online:
        jsonschema.validate(row, online_schema)
    products, evidence = _product_records()
    issues: list[str] = []
    evidence_checks = 0
    constraint_checks = 0
    for case in trusted:
        unknown = set(case["expected_product_ids"]) - set(products)
        if unknown:
            issues.append(f"{case['case_id']}: unknown products {sorted(unknown)}")
        for item in case["required_evidence"]:
            evidence_checks += 1
            if (item["product_id"], item["field_id"]) not in evidence:
                issues.append(f"{case['case_id']}: missing gold evidence {item}")
        for product_id in case["expected_product_ids"]:
            product = products[product_id]
            for constraint in case["expected_constraints"]:
                constraint_checks += 1
                if not _satisfies(product.get(constraint["field"]), constraint["operator"], constraint["value"]):
                    issues.append(
                        f"{case['case_id']}: {product_id} does not satisfy {constraint['field']} "
                        f"{constraint['operator']} {constraint['value']} (actual={product.get(constraint['field'])})"
                    )
    category_counts: dict[str, int] = defaultdict(int)
    for row in trusted:
        category_counts[row["category"]] += 1
    payload = {
        "status": "passed" if not issues else "failed",
        "trusted_cases": len(trusted),
        "online_cases": len(online),
        "product_ids": len(products),
        "gold_evidence_pairs_checked": evidence_checks,
        "expected_constraint_product_checks": constraint_checks,
        "category_counts": dict(sorted(category_counts.items())),
        "issues": issues,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
