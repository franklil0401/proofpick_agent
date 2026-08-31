"""Local comparison helpers for graph parallelism and source-level capabilities."""

from __future__ import annotations

import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smartbuy.constraints import CandidateConstraintVerifier, ConstraintNormalizer

from .contracts import deterministic_merge
from .fake_tools import FakeToolRegistry
from .fixtures import fixture
from .graph import LangGraphPoc


def sequential_reference_pipeline(
    registry: FakeToolRegistry,
    payload: dict[str, Any],
    *,
    database_path: Path,
    repetitions: int,
) -> list[float]:
    normalizer = ConstraintNormalizer()
    verifier = CandidateConstraintVerifier(
        database_path, as_of=datetime(2026, 8, 27, 0, 0, tzinfo=UTC)
    )
    durations: list[float] = []
    for _ in range(repetitions):
        started = time.perf_counter()
        constraints = normalizer.build(payload["question"], source_turn=1)
        sql = registry.execute_with_retry(
            "text2sql", payload, max_attempts=1, timeout_ms=500.0
        )
        kb = registry.execute_with_retry(
            "kb_search", payload, max_attempts=1, timeout_ms=500.0
        )
        deterministic_merge([sql, kb])
        verifier.verify_candidates(constraints, sql["candidate_ids"])
        durations.append((time.perf_counter() - started) * 1000.0)
    return durations


def parallel_benchmark(database_path: Path, *, repetitions: int = 5) -> dict[str, float | int]:
    payload = fixture(
        case_id="parallel-benchmark",
        delays_ms={"text2sql": 40.0, "kb_search": 40.0},
    )
    parallel: list[float] = []
    overlap_passes = 0
    for index in range(repetitions):
        registry = FakeToolRegistry()
        graph = LangGraphPoc(database_path, tools=registry)
        started = time.perf_counter()
        graph.invoke(payload, thread_id=f"parallel-{index}")
        parallel.append((time.perf_counter() - started) * 1000.0)
        spans = {str(item["tool"]): item for item in registry.call_spans}
        sql = spans["text2sql"]
        kb = spans["kb_search"]
        overlap_passes += int(
            max(float(sql["start"]), float(kb["start"]))
            < min(float(sql["end"]), float(kb["end"]))
        )

    sequential = sequential_reference_pipeline(
        FakeToolRegistry(), payload, database_path=database_path, repetitions=repetitions
    )
    parallel_median = statistics.median(parallel)
    sequential_median = statistics.median(sequential)
    return {
        "repetitions": repetitions,
        "overlap_passes": overlap_passes,
        "parallel_median_ms": round(parallel_median, 3),
        "sequential_median_ms": round(sequential_median, 3),
        "median_reduction_percent": round(
            (sequential_median - parallel_median) / sequential_median * 100.0, 3
        ),
    }


def source_capability_evidence(project_root: Path) -> dict[str, int]:
    """Count public checkpoint/interrupt entry points in the V1 loop."""
    source = (project_root / "smartbuy/agent/react.py").read_text(encoding="utf-8")
    return {
        "v1_checkpoint_api_count": source.count("checkpoint"),
        "v1_interrupt_api_count": source.count("interrupt"),
    }
