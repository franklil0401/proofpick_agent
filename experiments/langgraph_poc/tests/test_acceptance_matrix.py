"""M01-M17: graph, resilience, checkpoint and safety acceptance matrix."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from experiments.langgraph_poc.checkpoint import (
    CheckpointCorruptedError,
    FileBackedMemorySaver,
)
from experiments.langgraph_poc.fake_tools import FakeToolRegistry
from experiments.langgraph_poc.fixtures import fixture
from experiments.langgraph_poc.fixtures import PROJECT_ROOT
from experiments.langgraph_poc.graph import LangGraphPoc, SafetyGateBypassError


def test_m01_stategraph_fact_route_uses_kb_only(poc):
    payload = fixture(
        case_id="m01",
        question="Dell U2723QE 的屏幕尺寸和分辨率是多少？",
        task_kind="fact",
        kb_candidates=["dell-u2723qe-cn"],
    )
    result = poc.invoke(payload, thread_id="m01")
    tools = [item["tool"] for item in result["tool_results"]]
    topology = poc.topology()
    assert "kb_search" in tools
    assert "text2sql" not in tools
    assert result["checker_executed"] is True
    assert result["final_report"]["recommended_model_ids"] == ["dell-u2723qe-cn"]
    assert "parse_requirements" in topology["nodes"]
    assert "constraint_gate" in topology["nodes"]


def test_m02_sql_and_kb_are_parallel_and_merge_completely(database):
    tools = FakeToolRegistry()
    poc = LangGraphPoc(database, tools=tools)
    payload = fixture(
        case_id="m02",
        delays_ms={"text2sql": 40.0, "kb_search": 40.0},
    )
    result = poc.invoke(payload, thread_id="m02")
    spans = {str(item["tool"]): item for item in tools.call_spans}
    assert max(float(spans["text2sql"]["start"]), float(spans["kb_search"]["start"])) < min(
        float(spans["text2sql"]["end"]), float(spans["kb_search"]["end"])
    )
    assert result["candidate_pool_model_ids"] == [
        "dell-u2723qe-cn",
        "asus-pa279crv-cn",
    ]
    assert {item["tool"] for item in result["tool_results"]} >= {
        "text2sql",
        "kb_search",
        "kb_search_targeted",
        "evidence_check",
    }


def test_m03_model_and_region_do_not_cross(poc):
    payload = fixture(
        case_id="m03",
        question="只看中国版 PD2705U，要求 USB-C 供电至少 60W",
        sql_candidates=["benq-pd2705u-us"],
        kb_candidates=["benq-pd2705u-us"],
    )
    result = poc.invoke(payload, thread_id="m03")
    candidate = result["verification"]["candidates"][0]
    assert candidate["eligible"] is False
    assert result["final_report"]["recommended_model_ids"] == []


def test_m04_duplicate_candidates_are_deterministically_deduplicated(poc):
    payload = fixture(
        case_id="m04",
        sql_candidates=["dell-u2723qe-cn", "dell-u2723qe-cn"],
        kb_candidates=["dell-u2723qe-cn", "dell-u2723qe-cn"],
    )
    result = poc.invoke(payload, thread_id="m04")
    assert result["candidate_pool_model_ids"] == ["dell-u2723qe-cn"]
    assert result["verification"]["candidate_pool_model_ids"] == ["dell-u2723qe-cn"]


def test_m05_conflicting_evidence_remains_conflict(poc):
    payload = fixture(
        case_id="m05",
        question="PD2705U 的 USB-C 供电至少 60W",
        sql_candidates=["benq-pd2705u-us"],
        kb_candidates=["benq-pd2705u-us"],
    )
    result = poc.invoke(payload, thread_id="m05")
    candidate = result["verification"]["candidates"][0]
    assert candidate["overall_status"] == "conflict"
    assert candidate["eligible"] is False


@pytest.mark.parametrize("error", ["unavailable", "5xx"])
def test_m06_kb_failure_or_unavailable_degrades_to_sql(database, error):
    tools = FakeToolRegistry()
    poc = LangGraphPoc(database, tools=tools)
    payload = fixture(
        case_id=f"m06-{error}",
        question="需要 USB-C 视频输入且供电至少 90W",
        sql_candidates=["dell-u2723qe-cn"],
        kb_candidates=[],
        scripts={"kb_search": [{"error": error}, {"error": error}, {"error": error}]},
    )
    result = poc.invoke(payload, thread_id=f"m06-{error}")
    assert result["final_report"]["recommended_model_ids"] == ["dell-u2723qe-cn"]
    assert "kb_search" in result["final_report"]["degraded_tools"]


def test_m07_sql_failure_degrades_to_kb(database):
    tools = FakeToolRegistry()
    poc = LangGraphPoc(database, tools=tools)
    payload = fixture(
        case_id="m07",
        question="需要 USB-C 视频输入且供电至少 90W",
        sql_candidates=[],
        kb_candidates=["dell-u2723qe-cn"],
        scripts={"text2sql": [{"error": "5xx"}, {"error": "5xx"}, {"error": "5xx"}]},
    )
    result = poc.invoke(payload, thread_id="m07")
    assert result["final_report"]["recommended_model_ids"] == []
    assert result["checker_degraded"] is True
    assert "structured_candidate_pool_unavailable" in result["stop_reason"]
    assert "text2sql" in result["final_report"]["degraded_tools"]


def test_m08_reranker_failure_keeps_vector_candidates(poc):
    payload = fixture(case_id="m08", reranker_degraded=True)
    result = poc.invoke(payload, thread_id="m08")
    kb = next(item for item in result["tool_results"] if item["tool"] == "kb_search")
    assert kb["status"] == "degraded"
    assert kb["error_category"] == "reranker_5xx"
    assert result["candidate_pool_model_ids"]


@pytest.mark.parametrize(("error", "expected_attempts"), [("401", 1), ("403", 1)])
def test_m09_auth_errors_are_never_retried(database, error, expected_attempts):
    tools = FakeToolRegistry()
    poc = LangGraphPoc(database, tools=tools)
    payload = fixture(
        case_id=f"m09-{error}",
        task_kind="fact",
        kb_candidates=["dell-u2723qe-cn"],
        scripts={"kb_search": [{"error": error}, {"candidates": ["dell-u2723qe-cn"]}]},
    )
    poc.invoke(payload, thread_id=f"m09-{error}")
    assert tools.attempts_for("kb_search") == expected_attempts


@pytest.mark.parametrize("error", ["429", "5xx", "timeout"])
def test_m09_retryable_errors_use_bounded_retry(database, error):
    tools = FakeToolRegistry()
    poc = LangGraphPoc(database, tools=tools)
    payload = fixture(
        case_id=f"m09-retry-{error}",
        task_kind="fact",
        kb_candidates=["dell-u2723qe-cn"],
        scripts={"kb_search": [{"error": error}, {"candidates": ["dell-u2723qe-cn"]}]},
    )
    result = poc.invoke(payload, thread_id=f"m09-retry-{error}")
    kb = next(item for item in result["tool_results"] if item["tool"] == "kb_search")
    assert kb["attempts"] == 2
    assert kb["retry_count"] == 1
    assert tools.attempts_for("kb_search") == 2


@pytest.mark.parametrize(
    ("limits", "reason"),
    [
        ({"max_steps": 0}, "max_steps_exceeded"),
        ({"max_tool_calls": 2}, "max_tool_calls_exceeded"),
    ],
)
def test_m10_step_and_tool_limits_fail_closed(poc, limits, reason):
    result = poc.invoke(fixture(case_id=f"m10-{reason}"), thread_id=f"m10-{reason}", limits=limits)
    assert result["final_report"]["recommended_model_ids"] == []
    assert result["checker_degraded"] is True
    assert reason in result["stop_reason"]


@pytest.mark.parametrize(
    ("payload", "limits", "reason"),
    [
        (
            fixture(
                case_id="m11-latency",
                task_kind="fact",
                kb_candidates=["dell-u2723qe-cn"],
                delays_ms={"kb_search": 20.0},
            ),
            {"max_latency_ms": 1.0},
            "latency_limit_exceeded",
        ),
        (
            fixture(case_id="m11-cost", tool_costs={"text2sql": 0.01}),
            {"max_cost_cny": 0.0},
            "cost_limit_exceeded",
        ),
    ],
)
def test_m11_latency_and_cost_limits_fail_closed(poc, payload, limits, reason):
    result = poc.invoke(payload, thread_id=payload["case_id"], limits=limits)
    assert result["final_report"]["recommended_model_ids"] == []
    assert reason in result["stop_reason"]


def test_m12_checkpoint_recovers_across_instances_without_repeating_tools(database, tmp_path):
    checkpoint_path = tmp_path / "graph.checkpoint"
    first_output = tmp_path / "first.json"
    resumed_output = tmp_path / "resumed.json"
    base = [
        sys.executable,
        "-m",
        "experiments.langgraph_poc.checkpoint_worker",
    ]
    for mode, output in (("start", first_output), ("resume", resumed_output)):
        completed = subprocess.run(
            [
                *base,
                mode,
                "--database",
                str(database),
                "--checkpoint",
                str(checkpoint_path),
                "--output",
                str(output),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stderr[-500:]

    first = json.loads(first_output.read_text(encoding="utf-8"))
    resumed = json.loads(resumed_output.read_text(encoding="utf-8"))
    assert first["interrupted"] is True
    assert first["process_tool_attempts"] == {
        "text2sql": 1,
        "kb_search": 1,
        "kb_search_targeted": 0,
    }
    assert resumed["checker_executed"] is True
    assert resumed["process_tool_attempts"]["text2sql"] == 0
    assert resumed["process_tool_attempts"]["kb_search"] == 0
    assert resumed["process_tool_attempts"]["kb_search_targeted"] == 1
    assert resumed["tool_call_count"] == 4


def test_m13_corrupt_checkpoint_is_refused(tmp_path):
    path = tmp_path / "corrupt.checkpoint"
    path.write_bytes(b"not-a-valid-checkpoint")
    with pytest.raises(CheckpointCorruptedError, match="recovery refused"):
        FileBackedMemorySaver(path)


def test_m14_interrupt_clarification_pauses_and_resumes(poc):
    payload = fixture(
        case_id="m14",
        task_kind="fact",
        kb_candidates=["dell-u2723qe-cn"],
        needs_clarification=True,
        clarification_question="是否要求中国大陆版本？",
    )
    interrupted = poc.invoke(payload, thread_id="m14")
    assert "__interrupt__" in interrupted
    assert poc.tools.attempts_for("kb_search") == 0
    resumed = poc.resume(thread_id="m14", value="是")
    assert resumed["clarification_answer"] == "是"
    assert resumed["final_report"]["checker_executed"] is True
    assert poc.tools.attempts_for("kb_search") == 1


def test_m15_checker_exception_is_fail_closed(poc):
    result = poc.invoke(fixture(case_id="m15", checker_error=True), thread_id="m15")
    assert result["checker_executed"] is True
    assert result["checker_degraded"] is True
    assert result["final_report"]["status"] == "refused"
    assert result["final_report"]["recommended_model_ids"] == []


def test_m16_checker_cannot_be_bypassed(poc):
    payload = fixture(
        case_id="m16",
        attempt_bypass_candidates=["invented-monitor-cn", "dell-u2723qe-cn"],
    )
    result = poc.invoke(payload, thread_id="m16")
    eligible = set(result["verification"]["eligible_model_ids"])
    assert set(result["final_report"]["recommended_model_ids"]) <= eligible
    assert "invented-monitor-cn" in result["final_report"]["blocked_bypass_candidates"]
    with pytest.raises(SafetyGateBypassError):
        poc.nodes["build_report"]({"fixture": payload})

    edges = [item.split("->", 1) for item in poc.topology()["edges"]]
    predecessors: dict[str, set[str]] = {}
    for source, target in edges:
        predecessors.setdefault(target, set()).add(source)
    assert predecessors["build_report"] == {"constraint_gate"}
    assert predecessors["safe_refusal"] == {"constraint_gate"}


def test_m17_events_are_bounded_and_map_to_sse_monitor(poc):
    result = poc.invoke(fixture(case_id="m17"), thread_id="m17")
    names = {item["event"] for item in result["events"]}
    assert {
        "requirements_parsed",
        "parallel_started",
        "tool_results_merged",
        "constraint_check_started",
        "constraint_check_completed",
        "agent_completed",
    } <= names
    assert all(set(item) == {"event", "node", "status", "summary", "parent_step"} for item in result["events"])
    serialized = str(result["events"]).lower()
    assert "authorization" not in serialized
    assert "api_key" not in serialized
    assert "prompt" not in serialized
