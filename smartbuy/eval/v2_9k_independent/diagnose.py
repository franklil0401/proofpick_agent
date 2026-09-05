"""Read-only audit of the preserved RC4 fact-query failure; no Agent rerun."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections import Counter
from pathlib import Path

from smartbuy.tools.evidence_check import EvidenceCheckTool

BASE = Path(__file__).resolve().parent


async def main():
    rows = [json.loads(x) for x in (BASE / "results/exposed_first.jsonl").read_text(encoding="utf8").splitlines()]
    failed = next(r for r in rows if r["case_id"] == "rc3i-monitor-007")
    report = failed["response"]["report"]
    db = Path("C:/ppv2rc3evalrun/monitor/smartbuy_monitors_v1.sqlite")
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        product = dict(connection.execute(
            "SELECT model_id,region,width_mm,resolution FROM products WHERE model_id=?",
            ("asus-pa27jcv-cn",),
        ).fetchone())
        references = [dict(row) for row in connection.execute(
            "SELECT e.evidence_id,e.model_id,e.normalized_field,e.normalized_value,e.source_id,s.region,s.url "
            "FROM evidence_records e JOIN source_records s ON s.source_id=e.source_id "
            "WHERE e.model_id=? AND e.normalized_field IN (?,?)",
            ("asus-pa27jcv-cn", "width_mm", "resolution"),
        )]
    direct = await EvidenceCheckTool(db).invoke({
        "model_ids": [product["model_id"]], "required_fields": ["width_mm", "resolution"],
        "constraints": [], "reason": "Read-only diagnostic; not a replacement Agent result.",
    })
    usage = [u for row in rows for u in row["usage"]]
    return {
        "classification": "confirmed_fact_completion_contract_gap_not_scorer_false_positive",
        "case_id": failed["case_id"],
        "original_http_status": failed["http_status"],
        "original_trace": report["trace"],
        "original_unresolved_facts": report["unresolved_facts"],
        "original_abstained": report["abstained"],
        "original_stop_reason": report["stop_reason"],
        "original_evidence_values": [e["value"] for e in report["evidence"]],
        "catalog_product": product,
        "catalog_references": references,
        "readonly_evidence_check": direct.model_dump(mode="json"),
        "root_cause_locations": [
            {"path": "smartbuy/agent/react.py", "line": 525,
             "finding": "Finish gate checks candidate_rows, while KB writes candidate_pool_rows."},
            {"path": "smartbuy/agent/react.py", "line": 1278,
             "finding": "Deterministic Evidence fallback covers filter/comparison/dynamic, excludes fact."},
            {"path": "smartbuy/agent/reporting.py", "line": 323,
             "finding": "KB hits plus empty assessment states can mark evidence sufficient despite missing requested facts."},
        ],
        "live_usage": {
            "requests": len(usage), "models": dict(Counter(u["model"] for u in usage)),
            "input_tokens": sum(u.get("input_tokens", 0) for u in usage),
            "output_tokens": sum(u.get("output_tokens", 0) for u in usage),
            "estimated_cost_cny": sum(float(u.get("estimated_cost_cny", 0)) for u in usage),
            "provider_retries": sum(max(0, u.get("attempts", 1) - 1) for u in usage),
            "api_failures": sum(not u.get("success", True) for u in usage),
        },
        "diagnostic_api_calls": 0, "production_changes": 0,
        "evaluator_or_gold_changes_after_freeze": 0,
        "remaining_trusted_unrun": 79, "online_unrun": 15,
        "diagnostic_command_notes": [
            "Two initial read-only probes referenced nonexistent field_evidence table and execute method; corrected after inspecting schema and tool contract.",
            "These probes made no model requests and did not replace any live evaluation result.",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False))
