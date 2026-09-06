"""Phase-specific aggregation; individual frozen scoring is unchanged."""

from __future__ import annotations

import math
from collections import Counter

from smartbuy.eval.v2_9i_independent.score import summarize


def aggregate(scores, raw):
    result = summarize(scores)
    result.pop("release_gate_passed")
    result["planned"] = 79
    result["remaining"] = 79 - len(raw)
    result["scored"] = len(scores)
    result["executed"] = len(raw)
    result["by_kind"] = {kind: {"passed": sum(r["passed"] for r in scores if r["kind"] == kind),
                                "total": sum(r["kind"] == kind for r in scores)}
                         for kind in ["fact", "comparison", "filter", "negative"]}
    fc = [s for s in scores if s["kind"] in {"fact", "comparison"}]
    result["fact_comparison_requested_evidence"] = [sum(s["covered_fact_pairs"] for s in fc),
                                                     sum(s["expected_fact_pairs"] for s in fc)]
    filters = [s for s in scores if s["kind"] == "filter" and s["allowed_ids"]]
    result["sufficient_data_empty_recommendations"] = [sum(not s["recommended_ids"] for s in filters), len(filters)]
    claims = result["recommendation_fact_evidence"]
    result["trusted79_gate_passed"] = (len(raw) == len(scores) == 79
        and all(result["domains"][domain]["passed"] >= minimum for domain, minimum in
                {"monitor": 16, "laptop": 24, "headphone": 24}.items())
        and result["f1"] is not None and result["f1"] >= 0.95
        and claims[1] > 0 and claims[0] / claims[1] >= 0.95 and not result["safety"])
    usage = [entry for row in raw for entry in row["usage"]]
    result["usage"] = {"ledger_records": len(usage), "models": dict(Counter(u["model"] for u in usage)),
                       "http_attempts": sum(u["attempts"] for u in usage),
                       "retries": sum(max(0, u["attempts"] - 1) for u in usage),
                       "failed_records": sum(not u["success"] for u in usage),
                       "input_tokens": sum(u["input_tokens"] for u in usage),
                       "output_tokens": sum(u["output_tokens"] for u in usage),
                       "estimated_cost_cny": round(sum(u["estimated_cost_cny"] for u in usage), 9)}
    times = sorted(row["latency_ms"] for row in raw)
    result["latency_ms"] = {"mean": sum(times) / len(times) if times else None,
                            "p95_nearest_rank": times[math.ceil(0.95 * len(times)) - 1] if times else None}
    return result
