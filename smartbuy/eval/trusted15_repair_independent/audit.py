"""Offline raw-response reassessment and stronger clarification corroboration."""

import json

from smartbuy.eval.v2_9i_independent.score_v2 import score_case_v2

from .freeze import BASE, PRIOR, file_hash, save, stable
from .metrics import metrics
from .preflight import main as production_audit
from .run import verified_inputs


def main():
    _, selected, catalog = verified_inputs()
    cases = {case["case_id"]: case for case in selected}
    raw = [json.loads(line) for line in (BASE / "results/first.jsonl").read_text(encoding="utf8").splitlines()]
    assert len(raw) == len({row["case_id"] for row in raw})
    assert [row["case_id"] for row in raw] == list(cases)[:len(raw)]
    scores = [score_case_v2(cases[row["case_id"]], row, catalog) for row in raw]
    saved = json.loads((BASE / "results/first_scores.json").read_text(encoding="utf8"))
    assert stable(scores) == stable(saved["cases"])
    summary = metrics(scores, raw)
    assert summary == saved["summary"]
    previous = json.loads((PRIOR / "results/first_scores.json").read_text(encoding="utf8"))
    old_scores = {s["case_id"]: s for s in previous["cases"]}
    paired = [{"case_id": s["case_id"], "old_passed": old_scores[s["case_id"]]["passed"],
               "new_passed": s["passed"], "new_reasons": s["reasons"]} for s in scores]
    corroboration = []
    for row in raw:
        c, report = cases[row["case_id"]], row["response"].get("report") or {}
        if c["kind"] == "negative" and c["gold"]["negative"] == "clarify":
            corroboration.append({"case_id": c["case_id"], "state": report.get("clarification_state"),
                                  "questions": report.get("pending_questions", []), "paid_calls": len(row["usage"]),
                                  "business_tools": report.get("tools_used", []),
                                  "recommended_ids": report.get("recommended_model_ids", []),
                                  "abstained": report.get("abstained"), "coverage": report.get("usage", {}).get("requirement_coverage")})
    runtime = production_audit()
    assert runtime == json.loads((BASE / "preflight.json").read_text(encoding="utf8"))
    output = {"raw_sha256": file_hash(BASE / "results/first.jsonl"),
              "scores_sha256": file_hash(BASE / "results/first_scores.json"), "raw_recalculation_equal": True,
              "production_runtime_unchanged": True, "summary": summary, "old_same15_summary": previous["summary"],
              "paired": paired, "clarification_corroboration": corroboration, "model_calls_in_audit": 0}
    save(BASE / "results/recalculation_audit.json", output)
    print(json.dumps({k: v for k, v in output.items() if k not in {"paired", "old_same15_summary"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
