"""M18-M20 and quantitative comparison against the V1 custom loop."""

from __future__ import annotations

from experiments.langgraph_poc.benchmark import parallel_benchmark, source_capability_evidence
from experiments.langgraph_poc.fake_tools import FakeToolRegistry
from experiments.langgraph_poc.fixtures import (
    PROJECT_ROOT,
    fixture,
    stage4_regression_fixtures,
    stage5_representative_fixtures,
)
from experiments.langgraph_poc.graph import LangGraphPoc


def test_m18_ten_v1_representative_cases_match_checker_gold(database):
    cases = stage5_representative_fixtures()
    assert len(cases) == 10
    for case in cases:
        graph = LangGraphPoc(database)
        result = graph.invoke(case, thread_id=f"m18-{case['case_id']}")
        assert result["verification"]["eligible_model_ids"] == case[
            "expected_eligible_model_ids"
        ]
        by_model = {item["model_id"]: item for item in result["verification"]["candidates"]}
        for model_id, expected_fields in case["expected_statuses"].items():
            observed = {
                item["constraint"]["field"]: item["status"]
                for item in by_model[model_id]["constraint_results"]
            }
            assert all(observed[field] == status for field, status in expected_fields.items())


def test_m19_all_sixteen_v1_regressions_add_no_violating_recommendation(database):
    cases = stage4_regression_fixtures()
    assert len(cases) == 16
    for case in cases:
        graph = LangGraphPoc(database)
        result = graph.invoke(case, thread_id=f"m19-{case['case_id']}")
        recommended = set(result["final_report"]["recommended_model_ids"])
        eligible = set(result["verification"]["eligible_model_ids"])
        assert result["checker_executed"] is True
        assert recommended <= eligible


def test_m20_parallel_scheduling_and_repetition_are_deterministic(database):
    payload_a = fixture(
        case_id="m20-a",
        delays_ms={"text2sql": 35.0, "kb_search": 5.0},
    )
    payload_b = fixture(
        case_id="m20-b",
        delays_ms={"text2sql": 5.0, "kb_search": 35.0},
    )
    outputs = []
    for index, payload in enumerate((payload_a, payload_b, payload_a)):
        graph = LangGraphPoc(database, tools=FakeToolRegistry())
        outputs.append(graph.invoke(payload, thread_id=f"m20-{index}"))
    assert all(
        item["candidate_pool_model_ids"] == outputs[0]["candidate_pool_model_ids"]
        for item in outputs
    )
    assert all(
        item["verification"]["semantic_fingerprint"]
        == outputs[0]["verification"]["semantic_fingerprint"]
        for item in outputs
    )


def test_quantified_parallel_and_recovery_evidence(database):
    benchmark = parallel_benchmark(database, repetitions=5)
    capabilities = source_capability_evidence(PROJECT_ROOT)
    assert benchmark["overlap_passes"] == 5
    assert benchmark["parallel_median_ms"] < benchmark["sequential_median_ms"]
    assert benchmark["median_reduction_percent"] > 20.0
    assert capabilities == {
        "v1_checkpoint_api_count": 0,
        "v1_interrupt_api_count": 0,
    }
