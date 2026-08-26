from __future__ import annotations

import json
from pathlib import Path

from smartbuy.data.derive import evidence_rows, source_rows
from smartbuy.data.loader import load_catalog
from smartbuy.data.quality import validate_catalog


def test_catalog_scope_and_quality_gate() -> None:
    catalog = load_catalog()
    report = validate_catalog(catalog)

    assert report.passed
    assert len(catalog.products) == 12
    assert len({product["brand"] for product in catalog.products}) == 4
    assert 10 <= len(catalog.source_records) <= 20
    assert report.metrics["critical_missing_rate"] == 0.0


def test_every_normalized_product_fact_has_traceable_evidence() -> None:
    catalog = load_catalog()
    sources = {source["source_id"] for source in source_rows(catalog)}
    evidence = evidence_rows(catalog)
    trace = {(item["model_id"], item["normalized_field"]) for item in evidence}

    for item in evidence:
        assert item["source_id"] in sources
    for product in catalog.products:
        for field_name, value in product.items():
            if field_name not in {"official_source_id", "source_updated_at"} and value is not None:
                assert (product["model_id"], field_name) in trace


def test_eval_cases_have_unique_ids_and_required_contract() -> None:
    path = Path(__file__).resolve().parents[2] / "eval" / "cases.jsonl"
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    required = {
        "case_id", "question", "category", "expected_model_ids", "gold_evidence_ids",
        "required_fields", "expected_behavior", "should_abstain", "notes",
    }

    assert len(cases) == 40
    assert len({case["case_id"] for case in cases}) == len(cases)
    assert all(required == set(case) for case in cases)
    assert any(case["category"] == "source_conflict" for case in cases)
    assert any(case["category"] == "reranker_degradation" for case in cases)
    assert any(case["should_abstain"] for case in cases)
