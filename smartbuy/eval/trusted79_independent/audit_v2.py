"""Read-only post-run audit with JSON serialization-compatible equality."""

from __future__ import annotations

import json
from collections import Counter

from smartbuy.eval.v2_9i_independent.score_v2 import score_case_v2

from .aggregate import aggregate
from .freeze import BASE, file_hash, save, stable
from .run import verified_inputs


def json_equal(left, right):
    return stable(left) == stable(right)


def main():
    _, selected, catalog = verified_inputs()
    cases = {case["case_id"]: case for case in selected}
    path = BASE / "results/first.jsonl"
    raw = [json.loads(line) for line in path.read_text(encoding="utf8").splitlines()]
    assert len(raw) == len({row["case_id"] for row in raw})
    assert [row["case_id"] for row in raw] == list(cases)[:len(raw)]
    scores = [score_case_v2(cases[row["case_id"]], row, catalog) for row in raw]
    saved = json.loads((BASE / "results/first_scores.json").read_text(encoding="utf8"))
    assert json_equal(saved["cases"], scores)
    summary = aggregate(scores, raw)
    assert saved["summary"] == summary
    safety_row = raw[-1]
    report = safety_row["response"]["report"]
    assert safety_row["case_id"] == "rc3i-monitor-026"
    assert cases[safety_row["case_id"]]["gold"]["negative"] == "clarify"
    assert not report["pending_questions"] and report["clarification_state"] == "not_required"
    assert len(report["recommended_model_ids"]) == 12
    assert len(safety_row["usage"]) == 5
    details = []
    for row, score in zip(raw, scores, strict=True):
        r = row["response"]["report"]
        c = cases[row["case_id"]]
        if score["safety"]:
            stage = "clarification_preflight"
        elif c["kind"] == "comparison" and r["task_type"] != "comparison":
            stage = "intent_resolution"
        elif score["false_constraints"] or score["missed_constraints"]:
            stage = "constraint_resolution"
        elif r.get("pending_questions"):
            stage = "requirement_coverage"
        elif not score["passed"]:
            stage = "evidence_or_reporting"
        else:
            stage = None
        details.append({"case_id": c["case_id"], "query": c["query"], "kind": c["kind"],
                        "passed": score["passed"], "first_failure_stage_inferred": stage,
                        "reasons": score["reasons"], "reported_task_type": r["task_type"],
                        "recommended_count": len(r["recommended_model_ids"]),
                        "pending_questions": r.get("pending_questions", []),
                        "false_constraints": score["false_constraints"], "missed_constraints": score["missed_constraints"],
                        "missing_fact_pairs": score["missing_fact_pairs"], "calls": score["calls"]})
    findings = {"production_clarification_failure_confirmed": True,
                "question": cases[safety_row["case_id"]]["query"],
                "actual_status": safety_row["response"]["status"],
                "pending_questions": report["pending_questions"],
                "clarification_state": report["clarification_state"],
                "model_requests": len(safety_row["usage"]),
                "recommendations": report["recommended_model_ids"],
                "hard_constraints": report["hard_constraints"],
                "requirement_coverage": report["usage"]["requirement_coverage"],
                "trace": report["trace"],
                "distinction": "Checker enforced the reduced effective set; this is missing upstream requirements/clarification, not an override of Checker results."}
    output = {"raw_sha256": file_hash(path), "scores_sha256": file_hash(BASE / "results/first_scores.json"),
              "unique_execution_ids": len(raw), "json_serialized_score_recalculation_equal": True,
              "summary_equal": True, "model_calls_in_audit": 0,
              "unrun_ids": list(cases)[len(raw):], "summary": summary,
              "first_failure_stages_inferred": dict(Counter(d["first_failure_stage_inferred"] for d in details if not d["passed"])),
              "safety_audit": findings, "cases": details}
    save(BASE / "results/recalculation_audit_v2.json", output)
    print(json.dumps({k: v for k, v in output.items() if k not in {"unrun_ids", "safety_audit", "cases"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
