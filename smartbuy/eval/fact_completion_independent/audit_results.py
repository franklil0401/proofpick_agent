"""Audit preserved live responses; never invokes an Agent or model."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent


def main():
    raw_path = BASE / "results/exposed_first.jsonl"
    score_path = BASE / "results/exposed_scores.json"
    rows = [json.loads(line) for line in raw_path.read_text(encoding="utf8").splitlines()]
    scores = json.loads(score_path.read_text(encoding="utf8"))
    assert [row["case_id"] for row in rows] == [f"rc3i-monitor-{n:03}" for n in (1, 5, 7, 11)]
    assert scores["summary"]["passed"] == scores["summary"]["total"] == 4
    assert not scores["summary"]["safety"]
    checks = []
    for row in rows:
        report = row["response"]["report"]
        assert row["http_status"] == 200 and row["error"] is None
        if report["task_type"] != "fact":
            continue
        completion = report["usage"]["fact_completion"]
        assert completion["completion_status"] == "complete"
        assert completion["answer_sufficient"] is True and report["abstained"] is False
        assert not report["recommended_model_ids"]
        matrix = completion["matrix"]
        assert len(matrix) == completion["checked_count"] == completion["required_count"]
        assert len({(c["product_id"], c["field"]) for c in matrix}) == len(matrix)
        assert all(c["status"] == "verified_value" and c["evidence_ids"] for c in matrix)
        successful = [t for t in report["trace"] if t["tool"] == "evidence_check" and t["status"] == "success"]
        assert len(successful) == 1
        assert not completion["checks"]
        checks.append({"case_id": row["case_id"], "matrix_required": len(matrix),
                       "matrix_checked": len(matrix), "successful_evidence_calls": 1,
                       "deterministic_terminal_fallback_triggered": False,
                       "requested_fields_including_identity_helpers": [c["field"] for c in matrix],
                       "values": {c["field"]: c["actual_value"] for c in matrix}})
    usage = [u for row in rows for u in row["usage"]]
    return {"scope": "four_exposed_monitor_cases_only", "run_id": rows[0]["run_id"],
            "production_commit": rows[0]["production_commit"], "summary": scores["summary"],
            "completion_checks": checks, "facts_only_gold_coverage": [6, 6],
            "recommended_hard_field_coverage": [6, 6],
            "counts_note": "Scorer requested_fact_evidence includes both six fact-query pairs and six filter gold pairs.",
            "requests": len(usage), "models": dict(Counter(u["model"] for u in usage)),
            "input_tokens": sum(u.get("input_tokens", 0) for u in usage),
            "output_tokens": sum(u.get("output_tokens", 0) for u in usage),
            "provider_retries": sum(max(0, u.get("attempts", 1) - 1) for u in usage),
            "api_failures": sum(not u.get("success", True) for u in usage),
            "estimated_cost_cny": sum(float(u.get("estimated_cost_cny", 0)) for u in usage),
            "latencies_ms": [row["latency_ms"] for row in rows],
            "raw_lf_sha256": hashlib.sha256(raw_path.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
            "scores_lf_sha256": hashlib.sha256(score_path.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
            "remaining_trusted_unrun": 79, "online_unrun": 15,
            "audit_model_calls": 0,
            "caveat": "Live paths did not require terminal fallback; fallback and unknown/conflict branches were validated offline only."}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
