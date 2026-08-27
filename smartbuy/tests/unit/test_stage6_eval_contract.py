"""Frozen-suite, scoring and sanitized-ledger contracts for Stage 6."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from smartbuy.eval.run_stage6_eval import validate_freeze
from smartbuy.eval.merge_stage6_checkpoints import merge
from smartbuy.eval.stage6_scoring import _ndcg, ratio, score_group, score_stability
from smartbuy.observability import EvaluationLedgerRecord


def test_frozen_stage6_suite_has_expected_size_splits_and_hashes():
    result = validate_freeze()
    assert result["passed"] is True
    assert result["natural_case_count"] == 40
    assert result["split_counts"] == {"regression": 16, "holdout": 24}
    assert len(result["natural_sha256"]) == 64
    assert len(result["config_hash"]) == 64


def test_zero_denominator_is_na_instead_of_zero_or_one_hundred_percent():
    assert ratio(0, 0) == {
        "numerator": 0,
        "denominator": 0,
        "rate": None,
        "status": "N/A",
    }


def test_stability_requires_three_repetitions_and_checker_fingerprints():
    rows = []
    for repetition in (1, 2, 3):
        rows.append(
            {
                "experiment_group": "agentic_rag_checker",
                "case_id": "case-1",
                "repetition": repetition,
                "recommended_model_ids": ["model-a"],
                "abstained": False,
                "tools_used": ["text2sql", "kb_search", "evidence_check"],
                "checker_fingerprint": "byte-stable",
                "latency_ms": 10 + repetition,
                "usage": {"estimated_cost_cny": 0.01},
            }
        )
    result = score_stability(rows)["agentic_rag_checker"]
    assert result["final_candidate_set_consistency"]["rate"] == 1.0
    assert result["tool_path_consistency"]["rate"] == 1.0
    assert result["checker_workflow_fingerprint_consistency"]["rate"] == 1.0


def test_model_level_ndcg_deduplicates_multiple_chunks_from_one_model():
    assert _ndcg(["model-a", "model-a", "model-b"], {"model-a", "model-b"}) == 1.0


def test_ledger_schema_forbids_prompt_or_arbitrary_sensitive_fields():
    record = EvaluationLedgerRecord(
        run_id="run-1",
        case_id="case-1",
        experiment_group="cache",
        repetition=1,
        data_version="data-v1",
        config_hash="a" * 64,
        model="text-embedding-v4",
        tool="kb_search",
        step=1,
        started_at="2026-08-27T00:00:00Z",
        ended_at="2026-08-27T00:00:01Z",
        duration_ms=1000,
        status="success",
    )
    assert "prompt" not in json.dumps(record.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        EvaluationLedgerRecord.model_validate({**record.model_dump(), "prompt": "secret"})


def test_missing_citation_region_is_scored_as_a_boolean_not_a_type_error():
    case = {
        "case_id": "case-1",
        "split": "holdout",
        "task_type": "fact",
        "expected_model_ids": ["model-a"],
        "should_abstain": False,
        "category": "single_fact",
        "gold_evidence_ids": ["evidence-a"],
        "required_tools": ["kb_search"],
        "multihop": False,
        "required_fields": ["resolution"],
    }
    prediction = {
        "case_id": "case-1",
        "experiment_group": "fixed_rag",
        "recommended_model_ids": [],
        "observed_model_ids": ["model-a"],
        "abstained": False,
        "claims": [{"evidence_ids": ["evidence-a"]}],
        "evidence_ids": ["evidence-a"],
        "citation_pairs": [
            {"model_id": "model-a", "evidence_id": "evidence-a", "region": None}
        ],
        "retrieved_model_ids": ["model-a"],
        "schema_pass": True,
        "usage": {},
    }
    metrics = score_group(
        [prediction],
        {"case-1": case},
        {"evidence-a": {"model_id": "model-a", "region": "CN"}},
    )
    assert metrics["evidence_quality"]["wrong_model_or_region_reference_rate"]["numerator"] == 0


def test_checkpoint_merge_is_deterministic_and_rejects_conflicts(tmp_path):
    row = {
        "config_hash": "a" * 64,
        "prediction": {
            "case_id": "case-1",
            "experiment_group": "direct_llm",
            "repetition": 1,
        },
    }
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    output = tmp_path / "merged.jsonl"
    first.write_text(json.dumps(row) + "\n", encoding="utf-8")
    second.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert merge([first, second], output)["prediction_count"] == 1

    conflicting = {**row, "prediction": {**row["prediction"], "abstained": True}}
    second.write_text(json.dumps(conflicting) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="conflicting duplicate"):
        merge([first, second], output)

    audit = tmp_path / "audit.json"
    result = merge(
        [first, second], output, first_wins_audit=audit, expected_count=1
    )
    assert result["duplicate_count"] == 1
    assert result["conflicting_duplicate_count"] == 1
    assert json.loads(audit.read_text(encoding="utf-8"))["selection_policy"] == (
        "first occurrence wins"
    )
