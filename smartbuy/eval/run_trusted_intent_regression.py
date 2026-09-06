"""Offline, response-reconstructed development checks through Portfolio HTTP.

This is NOT the independent runner or a rerun of its hidden inputs/scorer.
Only three already-executed artifacts informed the separately reviewed fixture.
The fake planner supplies bounded actions, while production intent, constraints,
SQLite filtering, Evidence Check and final Checker must enforce correctness.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from smartbuy.agent import PurchaseDecisionAgent
from smartbuy.db.build_database import build_database
from smartbuy.memory import LongTermPreferenceStore
from smartbuy.observability import UsageLedger
from smartbuy.tools import EvidenceCheckTool, Text2SQLTool, ToolResult, WebSearchTool


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("trusted_intent_exposed_v1.json")
DEFAULT_OUTPUT = Path(__file__).parent / "results" / "trusted_intent_offline_regression.json"
api = importlib.import_module("smartbuy.api.router")


def _call(name, arguments):
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": f"offline-{name}", "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }]}


class OfflinePlanner:
    def __init__(self, case):
        self.calls = 0
        self.ledger = UsageLedger()
        ids = case["expected_ids"] if case["kind"] == "comparison" else []
        constraints = ([{"field": "model_id", "operator": "in", "value": ids}] if ids else [
            {"field": field, "operator": operator, "value": value}
            for field, operator, value in case["expected_constraints"]
        ])
        # Deliberately preserve the exposed faulty planner classification for
        # comparisons: the authoritative input-intent gate must override it.
        self.messages = [
            _call("set_requirements", {
                "summary": case["query"], "task_type": "filter", "hard_constraints": constraints,
                "required_fields": case["requested_fields"], "soft_preferences": [],
                "excluded_model_ids": [], "pending_questions": [],
            }),
            _call("text2sql", {"sql": "SELECT model_id FROM products", "filters": [],
                               "reason": "Offline planned structured observation"}),
            _call("kb_search", {"query": case["query"], "model_ids": ids,
                                "required_fields": case["requested_fields"], "parent_step": 2,
                                "reason": "Offline catalog-backed retrieval, not live vector search"}),
            _call("evidence_check", {"model_ids": ids, "required_fields": case["requested_fields"],
                                     "constraints": [], "parent_step": 3,
                                     "reason": "Run the unchanged governed Evidence Check"}),
            _call("finish_decision", {"stop_reason": "Offline contract check finished", "pending_questions": []}),
        ]

    async def chat(self, *_args, **_kwargs):
        self.calls += 1
        message = self.messages.pop(0) if self.messages else {"role": "assistant", "content": ""}
        return SimpleNamespace(data=message)


class CatalogFixtureKB:
    """A deterministic fixture lookup, explicitly not a vector-retrieval metric."""

    name = "kb_search"
    schema = {"type": "function", "function": {
        "name": "kb_search", "description": "Offline governed fixture retrieval",
        "parameters": {"type": "object", "properties": {}},
    }}

    def __init__(self, database):
        self.database = database
        self.calls = 0

    async def invoke(self, arguments):
        self.calls += 1
        connection = sqlite3.connect(f"file:{self.database.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        hits = []
        try:
            ids = arguments.get("model_ids") or [row[0] for row in connection.execute("SELECT model_id FROM products")]
            wanted = set(arguments.get("required_fields") or [])
            for model_id in ids:
                rows = connection.execute(
                    "SELECT e.*,s.url,s.source_type,s.region,s.accessed_at FROM evidence_records e "
                    "JOIN source_records s ON e.source_id=s.source_id WHERE e.model_id=? ORDER BY e.evidence_id",
                    (model_id,),
                ).fetchall()
                by_source = {}
                for row in rows:
                    if wanted and row["normalized_field"] not in wanted:
                        continue
                    hit = by_source.setdefault(row["source_id"], {
                        "model_id": model_id, "source_id": row["source_id"], "source_url": row["url"],
                        "source_type": row["source_type"], "region": row["region"],
                        "section": "offline governed ledger fixture", "accessed_at": row["accessed_at"],
                        "evidence_bindings": [],
                    })
                    hit["evidence_bindings"].append({
                        "evidence_id": row["evidence_id"], "field": row["normalized_field"],
                        "source_id": row["source_id"], "source_url": row["url"],
                    })
                hits.extend(by_source.values())
        finally:
            connection.close()
        return ToolResult(tool=self.name, status="success", summary="Offline ledger-backed KB fixture", data={"hits": hits})


def _signature(field, operator, value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = float(value)
    return field, operator, json.dumps(value, ensure_ascii=False, sort_keys=True)


def validate_fixture(fixture, database):
    """Independently check fixture IDs and simple expected filters against SQLite."""
    cases = fixture["cases"]
    if len(cases) != 15 or len({case["case_id"] for case in cases}) != 15:
        raise ValueError("fixture must retain the explicitly reviewed fifteen development cases")
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(products)")}
        existing = {row[0] for row in connection.execute("SELECT model_id FROM products")}
        for case in cases:
            if set(case["expected_ids"]) - existing or set(case["requested_fields"]) - columns:
                raise ValueError("fixture references unknown governed identities or fields")
            if case["kind"] != "filter":
                continue
            terms, parameters = [], []
            for field, operator, value in case["expected_constraints"]:
                if field not in columns or operator not in {"eq", "gte", "lte"}:
                    raise ValueError("unsupported development-filter contract")
                terms.append(f'"{field}" ' + {"eq": "=", "gte": ">=", "lte": "<="}[operator] + " ?")
                parameters.append(value)
            found = {row[0] for row in connection.execute(
                "SELECT model_id FROM products WHERE " + " AND ".join(terms), parameters,
            )}
            if found != set(case["expected_ids"]):
                raise ValueError(f"declared result-set fixture is not supported by SQLite: {case['case_id']}")
    finally:
        connection.close()
    return {"case_count": 15, "known_identity_and_field_checks": 15, "sqlite_filter_result_set_checks": 9}


def _score(case, report, planner, kb, database):
    expected = {_signature(*item) for item in case["expected_constraints"]}
    active_rows = [item for item in report["constraint_set"]["constraints"]
                   if item["active"] and item["hard_or_soft"] == "hard"]
    actual = {_signature(item["field"], item["operator"], item["normalized_value"]) for item in active_rows}
    candidates = {item["model_id"] for item in report["candidates"]}
    recommended = set(report["recommended_model_ids"])
    pairs = {(model_id, field) for model_id in case["expected_ids"] for field in case["requested_fields"]}
    covered, invalid_bindings = set(), []
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        for candidate in report["candidates"]:
            for field in candidate["fields"]:
                pair = candidate["model_id"], field["field"]
                if pair not in pairs or field["status"] != "matched" or field["actual_value"] is None:
                    continue
                for reference in field["evidence"]:
                    row = connection.execute(
                        "SELECT e.*,s.url,s.region FROM evidence_records e JOIN source_records s "
                        "ON e.source_id=s.source_id WHERE e.evidence_id=?", (reference.get("evidence_id"),),
                    ).fetchone()
                    valid = bool(row is not None and row["model_id"] == pair[0]
                                 and row["normalized_field"] == pair[1]
                                 and row["source_id"] == reference["source_id"]
                                 and row["url"] == reference["source_url"]
                                 and row["region"] == reference["region"]
                                 and json.loads(row["normalized_value"]) == field["actual_value"])
                    if valid:
                        covered.add(pair)
                    else:
                        invalid_bindings.append([*pair, reference.get("evidence_id")])
    finally:
        connection.close()
    reasons = []
    if expected != actual:
        reasons.append("development_constraint_contract")
    if case["kind"] == "filter":
        if report["task_type"] != "filter" or recommended != set(case["expected_ids"]):
            reasons.append("development_filter_result_set")
    elif case["kind"] == "comparison":
        if report["task_type"] != "comparison" or candidates != set(case["expected_ids"]):
            reasons.append("development_comparison_identity")
        if recommended or any(item["eligible"] or item.get("recommendation_reason") for item in report["candidates"]):
            reasons.append("comparison_became_purchase_recommendation")
    else:
        if not (report["clarification_state"] == "pending" and report["pending_questions"]
                and planner.calls == 0 and kb.calls == 0 and report["tool_call_count"] == 0 and not recommended):
            reasons.append("zero_cost_clarification_gate")
    if pairs - covered:
        reasons.append("requested_fact_evidence_incomplete")
    if invalid_bindings:
        reasons.append("invalid_governed_reference")
    return {
        "case_id": case["case_id"], "historical_case_id": case["historical_case_id"],
        "query_origin": case["query_origin"], "kind": case["kind"], "passed": not reasons, "reasons": reasons,
        "tp": len(expected & actual), "fp": len(actual - expected), "fn": len(expected - actual),
        "requested_fact_evidence": [len(covered), len(pairs)], "missing_pairs": sorted(pairs - covered),
        "invalid_bindings": invalid_bindings, "effective_hard_constraints": active_rows,
        "candidate_ids": sorted(candidates), "recommended_ids": sorted(recommended),
        "clarification_state": report["clarification_state"], "pending_questions": report["pending_questions"],
        "task_type": report["task_type"], "abstained": report["abstained"],
        "tool_path": [{"step": row["step"], "tool": row["tool"], "status": row["status"]} for row in report["trace"]],
        "fact_completion": report["usage"].get("fact_completion"),
        "requirement_coverage": report["usage"].get("requirement_coverage"),
        "fake_planner_calls": planner.calls, "fake_kb_calls": kb.calls,
        "actual_api_calls": 0, "estimated_cost_cny": 0,
    }


def run():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    # Configure this dedicated offline process like the documented default
    # launcher; no credential is inspected, and production loaders are replaced.
    for name in ("PROOFPICK_NATURAL_CONSTRAINTS_ENABLED", "PROOFPICK_DOMAIN_PACK_ENABLED", "PROOFPICK_PRODUCT_PACK_ENABLED"):
        os.environ[name] = "false"
    os.environ["PROOFPICK_DOMAIN_AGENT_ENABLED"] = "true"
    os.environ["PROOFPICK_ORCHESTRATOR"] = "react"
    records = []
    with tempfile.TemporaryDirectory(prefix="proofpick-intent-offline-") as directory:
        runtime = Path(directory)
        database = runtime / "governed.sqlite"
        database_audit = build_database(database)
        fixture_audit = validate_fixture(fixture, database)
        for case in fixture["cases"]:
            planner, kb = OfflinePlanner(case), CatalogFixtureKB(database)
            agent = PurchaseDecisionAgent(planner, {
                "text2sql": Text2SQLTool(database), "kb_search": kb,
                "evidence_check": EvidenceCheckTool(database), "web_search": WebSearchTool(),
            }, preference_memory=LongTermPreferenceStore(runtime / "preferences.json"))
            app = FastAPI()
            app.include_router(api.router)
            started = time.perf_counter()
            with patch.object(api, "_agent", agent), patch.object(api, "_orchestrator", None), TestClient(app) as client:
                response = client.post("/api/smartbuy/portfolio/run", json={
                    "domain_id": "monitor", "mode": "trusted", "query": case["query"],
                    "session_id": case["case_id"], "use_long_term_memory": False,
                })
            if response.status_code != 200 or "report" not in response.json():
                raise RuntimeError(f"offline Portfolio contract failed: {case['case_id']} HTTP {response.status_code}")
            record = _score(case, response.json()["report"], planner, kb, database)
            record["local_latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
            records.append(record)
    tp, fp, fn = (sum(row[key] for row in records) for key in ("tp", "fp", "fn"))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {
        "classification": fixture["classification"], "method": "response-reconstructed Portfolio API, fake planner and KB, real SQLite/Evidence/Checker",
        "production_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "worktree_diff_sha256": hashlib.sha256(subprocess.check_output(["git", "diff", "--", "smartbuy"], cwd=ROOT)).hexdigest(),
        "fixture_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        "source_commit": fixture["source_commit"], "source_files": fixture["source_files"],
        "limitations": fixture["limitations"], "fixture_validation": fixture_audit, "database": database_audit,
        "historical_independent_first_unchanged": {"passed": 4, "total_executed": 15, "planned": 79, "not_run": 64, "f1": 0.8292682926829268},
        "summary": {
            "development_passed": sum(row["passed"] for row in records), "total": len(records),
            "by_kind": {kind: {"passed": sum(row["passed"] for row in records if row["kind"] == kind), "total": count}
                        for kind, count in Counter(row["kind"] for row in records).items()},
            "tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            "requested_fact_evidence": [sum(row["requested_fact_evidence"][index] for row in records) for index in (0, 1)],
            "actual_api_calls": 0, "estimated_cost_cny": 0,
        },
        "cases": records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("keep previous results immutable; choose a distinct output file")
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0 if result["summary"]["development_passed"] == result["summary"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
