"""Run bounded Stage 4 dry-run or full end-to-end evaluation."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
from pathlib import Path
from typing import Any

from smartbuy.agent import PurchaseDecisionAgent
from smartbuy.config import load_bailian_settings
from smartbuy.db.build_database import DEFAULT_OUTPUT
from smartbuy.memory import LongTermPreferenceStore, SessionMemoryStore
from smartbuy.observability import UsageLedger
from smartbuy.providers import BailianProvider
from smartbuy.tools import EvidenceCheckTool, KBSearchTool, Text2SQLTool, WebSearchTool


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = Path(__file__).with_name("stage4_cases.jsonl")
RESULTS_PATH = PROJECT_ROOT / "smartbuy/data/processed/stage4_e2e_results.json"
DRY_RESULTS_PATH = PROJECT_ROOT / "smartbuy/data/processed/stage4_dry_run_results.json"
STAGE_COST_LIMIT_CNY = 10.0


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _observed_models(report: Any) -> set[str]:
    return {
        *report.recommended_model_ids,
        *(item.model_id for item in report.evidence),
        *(item.model_id for item in report.candidates if item.overall_status.value == "matched"),
    }


def _multihop_pass(report: Any) -> bool:
    domain_traces = [
        item
        for item in report.trace
        if item.tool in {"text2sql", "kb_search", "evidence_check"}
        and item.status in {"success", "degraded"}
    ]
    tools = [item.tool for item in domain_traces]
    has_chain = all(name in tools for name in ("text2sql", "kb_search", "evidence_check"))
    ordered = (
        has_chain
        and tools.index("text2sql") < tools.index("kb_search") < tools.index("evidence_check")
    )
    dependencies = [item for item in domain_traces if item.tool in {"kb_search", "evidence_check"}]
    return ordered and all(item.parent_step is not None for item in dependencies)


async def evaluate(*, dry_run: bool, case_ids: set[str] | None = None) -> dict[str, Any]:
    cases = load_cases()
    if case_ids:
        cases = [case for case in cases if case["case_id"] in case_ids]
        missing = case_ids - {case["case_id"] for case in cases}
        if missing:
            raise ValueError(f"unknown case id: {sorted(missing)[0]}")
    if dry_run:
        cases = cases[:4]
    settings = load_bailian_settings()
    ledger = UsageLedger()
    provider = BailianProvider(settings, ledger=ledger, timeout_seconds=30.0)
    agent = PurchaseDecisionAgent(
        provider,
        {
            "text2sql": Text2SQLTool(DEFAULT_OUTPUT),
            "kb_search": KBSearchTool(settings, provider),
            "evidence_check": EvidenceCheckTool(DEFAULT_OUTPUT),
            "web_search": WebSearchTool(),
        },
        session_memory=SessionMemoryStore(),
        preference_memory=LongTermPreferenceStore("C:/ai/smartbuy-stage4/eval_preferences.json"),
    )
    rows = []
    try:
        for case in cases:
            if float(ledger.summary()["estimated_cost_cny"]) >= STAGE_COST_LIMIT_CNY:
                raise RuntimeError("Stage 4 API cost limit reached before evaluation completed")
            report = await agent.run(case["question"], session_id=f"eval-{case['case_id']}")
            tools = set(report.tools_used)
            expected_tools = set(case["expected_tools"])
            observed_models = _observed_models(report)
            expected_models = set(case["expected_model_ids"])
            recall = (
                len(observed_models & expected_models) / len(expected_models)
                if expected_models else 1.0
            )
            rows.append(
                {
                    "case_id": case["case_id"],
                    "category": case["category"],
                    "expected_tools": sorted(expected_tools),
                    "actual_tools": report.tools_used,
                    "tool_selection_pass": expected_tools.issubset(tools),
                    "expected_model_ids": sorted(expected_models),
                    "observed_model_ids": sorted(observed_models),
                    "model_recall": round(recall, 6),
                    "should_abstain": case["should_abstain"],
                    "actual_abstain": report.abstained,
                    "abstention_pass": report.abstained == case["should_abstain"],
                    "multihop_required": case["multihop"],
                    "multihop_pass": _multihop_pass(report) if case["multihop"] else True,
                    "schema_pass": report.report_version == "smartbuy-decision-v1",
                    "latency_ms": report.latency_ms,
                    "tool_call_count": report.tool_call_count,
                    "stop_reason": report.stop_reason,
                    "degraded_states": report.degraded_states,
                    "candidates": [
                        {"model_id": item.model_id, "overall_status": item.overall_status.value}
                        for item in report.candidates
                    ],
                    "trace": [item.model_dump(mode="json") for item in report.trace],
                    "usage": report.usage,
                }
            )
    finally:
        await provider.aclose()
    latencies = [row["latency_ms"] for row in rows]
    positive = [row for row in rows if row["expected_model_ids"]]
    multihop = [row for row in rows if row["multihop_required"]]
    metrics = {
        "case_count": len(rows),
        "tool_selection_accuracy": round(statistics.fmean(row["tool_selection_pass"] for row in rows), 6),
        "model_recall": round(statistics.fmean(row["model_recall"] for row in positive), 6) if positive else 1.0,
        "abstention_accuracy": round(statistics.fmean(row["abstention_pass"] for row in rows), 6),
        "multihop_completion_rate": round(statistics.fmean(row["multihop_pass"] for row in multihop), 6)
        if multihop else 1.0,
        "schema_pass_rate": round(statistics.fmean(row["schema_pass"] for row in rows), 6),
        "end_to_end_pass_rate": round(
            statistics.fmean(
                row["tool_selection_pass"] and row["model_recall"] == 1.0 and row["abstention_pass"]
                and row["multihop_pass"] and row["schema_pass"]
                for row in rows
            ),
            6,
        ),
        "average_latency_ms": round(statistics.fmean(latencies), 3),
        "p95_latency_ms": round(percentile(latencies, 0.95), 3),
        "average_tool_calls": round(statistics.fmean(row["tool_call_count"] for row in rows), 3),
    }
    return {
        "evaluation_version": "smartbuy-stage4-e2e-v1",
        "mode": "dry_run" if dry_run else "full",
        "metrics": metrics,
        "usage": ledger.summary(),
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="run the first four cases before any full batch")
    parser.add_argument("--case-id", action="append", default=[], help="run selected case id(s)")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or (DRY_RESULTS_PATH if args.dry_run else RESULTS_PATH)
    payload = asyncio.run(evaluate(dry_run=args.dry_run, case_ids=set(args.case_id) or None))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"mode": payload["mode"], "metrics": payload["metrics"], "usage": payload["usage"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
