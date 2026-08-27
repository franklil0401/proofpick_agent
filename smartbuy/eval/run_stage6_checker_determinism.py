"""Verify byte-equivalent Constraint Checker output for identical local inputs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from smartbuy.constraints import CandidateConstraintVerifier, ConstraintNormalizer
from smartbuy.db.build_database import DEFAULT_OUTPUT


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = Path(__file__).with_name("stage6_natural_cases.jsonl")
FOUR_GROUP_RESULTS = PROJECT_ROOT / "smartbuy/data/processed/stage6_four_group_results.json"
OUTPUT = PROJECT_ROOT / "smartbuy/data/processed/stage6_checker_determinism_results.json"
AS_OF = datetime(2026, 8, 27, 0, 0, tzinfo=UTC)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate() -> dict:
    cases = load_jsonl(CASES_PATH)
    predictions = json.loads(FOUR_GROUP_RESULTS.read_text(encoding="utf-8"))["predictions"]
    first_checker = {
        row["case_id"]: row
        for row in predictions
        if row["experiment_group"] == "agentic_rag_checker" and row["repetition"] == 1
    }
    rows = []
    for case in cases:
        prediction = first_checker[case["case_id"]]
        pool = list(dict.fromkeys(prediction.get("observed_model_ids", [])))
        constraints = ConstraintNormalizer().build(case["question"], source_turn=1)
        verifier = CandidateConstraintVerifier(DEFAULT_OUTPUT, as_of=AS_OF)
        serialized = [
            verifier.verify_candidates(constraints, pool).model_dump_json()
            for _ in range(3)
        ]
        rows.append(
            {
                "case_id": case["case_id"],
                "candidate_pool_size": len(pool),
                "three_run_byte_equivalent": len(set(serialized)) == 1,
            }
        )
    passed = sum(item["three_run_byte_equivalent"] for item in rows)
    return {
        "evaluation_version": "smartbuy-stage6-checker-determinism-v1",
        "input_policy": "每个 case 固定首次增强组 observed_model_ids 与冻结 query/as_of，连续执行三次。",
        "case_count": len(rows),
        "byte_equivalent": {
            "numerator": passed,
            "denominator": len(rows),
            "rate": round(passed / len(rows), 6),
        },
        "checker_api_calls": 0,
        "checker_estimated_cost_cny": 0.0,
        "cases": rows,
    }


def main() -> int:
    payload = evaluate()
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(payload["byte_equivalent"], ensure_ascii=False, sort_keys=True))
    return 0 if payload["byte_equivalent"]["rate"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
