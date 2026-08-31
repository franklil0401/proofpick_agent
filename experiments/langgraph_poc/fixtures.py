"""Load frozen V1 cases into deterministic PoC tool fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STAGE4_CASES = PROJECT_ROOT / "smartbuy/eval/stage4_cases.jsonl"
STAGE5_CASES = PROJECT_ROOT / "smartbuy/eval/stage5_natural_cases.jsonl"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def stage5_representative_fixtures() -> list[dict[str, Any]]:
    """Return the ten frozen deterministic checker cases from V1."""
    fixtures: list[dict[str, Any]] = []
    for case in load_jsonl(STAGE5_CASES):
        pool = list(case["candidate_pool_model_ids"])
        fixtures.append(
            {
                "case_id": case["case_id"],
                "question": case["question"],
                "task_kind": "mixed",
                "sql_candidates": pool,
                "kb_candidates": list(reversed(pool)),
                "expected_eligible_model_ids": case["expected_eligible_model_ids"],
                "expected_statuses": case["expected_statuses"],
            }
        )
    return fixtures


def stage4_regression_fixtures() -> list[dict[str, Any]]:
    """Map all 16 frozen V1 workflow cases to Fake Tool inputs."""
    fixtures: list[dict[str, Any]] = []
    for case in load_jsonl(STAGE4_CASES):
        pool = list(case["expected_model_ids"])
        fact_only = case["expected_tools"] == ["kb_search"]
        fixtures.append(
            {
                "case_id": case["case_id"],
                "question": case["question"],
                "task_kind": "fact" if fact_only else "mixed",
                "sql_candidates": [] if fact_only else pool,
                "kb_candidates": pool,
                "should_abstain": case["should_abstain"],
            }
        )
    return fixtures


def fixture(
    *,
    case_id: str = "poc-001",
    question: str = "中国版中找 27 英寸、4K、USB-C 视频且供电不少于 90W 的显示器。",
    task_kind: str = "mixed",
    sql_candidates: list[str] | None = None,
    kb_candidates: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "case_id": case_id,
        "question": question,
        "task_kind": task_kind,
        "sql_candidates": sql_candidates
        if sql_candidates is not None
        else ["dell-u2723qe-cn", "asus-pa279crv-cn"],
        "kb_candidates": kb_candidates
        if kb_candidates is not None
        else ["asus-pa279crv-cn", "dell-u2723qe-cn"],
    }
    payload.update(extra)
    return payload
