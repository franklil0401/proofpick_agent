"""Independently recompute saved raw scores; never invokes a provider."""

import json

from smartbuy.eval.v2_9i_independent.score_v2 import score_case_v2

from .aggregate import aggregate
from .freeze import BASE, file_hash, save
from .run import verified_inputs


def main():
    _, cases, catalog = verified_inputs()
    cases = {case["case_id"]: case for case in cases}
    path = BASE / "results/first.jsonl"
    raw = [json.loads(line) for line in path.read_text(encoding="utf8").splitlines()]
    assert len(raw) == len({row["case_id"] for row in raw})
    assert all(row["case_id"] in cases for row in raw)
    scores = [score_case_v2(cases[row["case_id"]], row, catalog) for row in raw]
    saved = json.loads((BASE / "results/first_scores.json").read_text(encoding="utf8"))
    assert saved["cases"] == scores
    summary = aggregate(scores, raw)
    assert saved["summary"] == summary
    output = {"raw_sha256": file_hash(path), "scores_sha256": file_hash(BASE / "results/first_scores.json"),
              "unique_execution_ids": len(raw), "scorer_recalculation_equal": True,
              "unrun_ids": [case_id for case_id in cases if case_id not in {row["case_id"] for row in raw}],
              "summary": summary, "model_calls_in_audit": 0}
    save(BASE / "results/recalculation_audit.json", output)
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
