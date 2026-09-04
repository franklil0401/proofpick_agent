"""Resume the RC2 Online first run without replaying the eight completed cases."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import jsonschema

from smartbuy.domain_packs import DomainPackLoader
from smartbuy.eval.v2_9b_independent.runner import _append_journal, _atomic, _host_allowed, _journal, _outside_repo, _runtime_contract
from smartbuy.open_research import OpenResearchService, OpenResearchSettings, StaticHTMLExtractor, TemporaryEvidenceStore
from smartbuy.providers import ZhipuSourceSearchProvider
from smartbuy.source_search import SourceSearchRequest, SourceSearchSettings, SourceSearchTriggerReason

from .runner import PRODUCTION_COMMIT, PRODUCTION_TREE, RC2_COMMIT, RC2_PAYLOAD_SHA, V1_COMMIT, _git, _now
from .scorer import score_online


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CASES = HERE / "online_cases_rc2.jsonl"
BASE_CASES = HERE / "online_cases.jsonl"
MANIFEST = HERE / "online_case_manifest_rc2.json"
SCHEMA = HERE / "online_case_rc2.schema.json"
POLICY = HERE / "scoring_policy.json"
BASE_RC = HERE / "release_candidate.json"
RC = HERE / "online_release_candidate_rc2.json"
FAILURE = ROOT / "smartbuy/eval/results/v2_9d_independent_online_harness_failure.json"
MAX_CALLS = 30
MAX_COST_CNY = 2.0


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _load() -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line]
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for row in rows:
        jsonschema.validate(row, schema)
    if len(rows) != 15 or _sha(CASES) != manifest["case_sha256"] or manifest["completed_prefix_count"] != 8:
        raise RuntimeError("Online RC2 case freeze is invalid")
    base = [json.loads(line) for line in BASE_CASES.read_text(encoding="utf-8").splitlines() if line]
    if rows[:8] != base[:8]:
        raise RuntimeError("completed Online prefix changed")
    return rows


def _definition_hashes() -> dict[str, str]:
    paths = [CASES, MANIFEST, SCHEMA, POLICY, HERE / "scorer.py", HERE / "online_runner_rc2.py", FAILURE]
    return {path.relative_to(ROOT).as_posix(): _sha(path) for path in paths}


def _payload(runtime_root: Path) -> dict[str, Any]:
    _load()
    base = json.loads(BASE_RC.read_text(encoding="utf-8"))
    failure = json.loads(FAILURE.read_text(encoding="utf-8"))
    if base["production_commit"] != PRODUCTION_COMMIT or base["production_tree"] != PRODUCTION_TREE:
        raise RuntimeError("base evaluator RC does not bind RC2")
    if base["rc_manifest_commit"] != RC2_COMMIT or base["rc_manifest_payload_sha256"] != RC2_PAYLOAD_SHA:
        raise RuntimeError("base evaluator manifest binding changed")
    if _git("rev-parse", "v1.0.0-portfolio^{commit}") != V1_COMMIT:
        raise RuntimeError("V1 tag moved")
    if failure["run_id"] != base["run_id"] or failure["completed_case_count"] != 8:
        raise RuntimeError("harness failure evidence changed")
    return {
        "schema_version": "proofpick-v2-9d-independent-online-rc2-v1",
        "classification": "evaluator-only length-contract correction; completed cases are not replayed",
        "release_candidate": "proofpick-v2-9c-rc2", "production_commit": PRODUCTION_COMMIT,
        "production_tree": PRODUCTION_TREE, "rc_manifest_commit": RC2_COMMIT,
        "rc_manifest_payload_sha256": RC2_PAYLOAD_SHA, "v1_commit": V1_COMMIT,
        "base_evaluator_config_sha256": base["config_sha256"], "run_id": base["run_id"],
        "completed_prefix_count": 8, "definitions": _definition_hashes(),
        "runtime": _runtime_contract(runtime_root), "limits": {"search_calls": MAX_CALLS, "cost_cny": MAX_COST_CNY},
    }


def freeze(runtime_root: Path, output: Path) -> dict[str, Any]:
    payload = _payload(runtime_root)
    payload["frozen_at"] = _now()
    payload["config_sha256"] = _stable(payload)
    _atomic(output, payload)
    return payload


def _assert_rc(runtime_root: Path, path: Path) -> dict[str, Any]:
    rc = json.loads(path.read_text(encoding="utf-8"))
    current = _payload(runtime_root)
    comparable = {key: value for key, value in rc.items() if key not in {"frozen_at", "config_sha256"}}
    if current != comparable:
        raise RuntimeError("Online RC2 definitions or runtime changed")
    if _stable({**comparable, "frozen_at": rc["frozen_at"]}) != rc["config_sha256"]:
        raise RuntimeError("Online RC2 hash is invalid")
    return rc


def _prior_usage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    primary = sum(min(int(row["result"]["search_attempt_count"]), 1) for row in rows)
    fallback = sum(max(0, int(row["result"]["search_attempt_count"]) - 1) for row in rows)
    return {"call_count": primary + fallback, "search_pro": primary, "search_pro_sogou": fallback, "estimated_cost_cny": primary * 0.03 + fallback * 0.05}


async def run(runtime_root: Path, rc_path: Path, journal_path: Path, output: Path) -> dict[str, Any]:
    cases = _load()
    rc = _assert_rc(runtime_root, rc_path)
    completed = _journal(journal_path, rc["run_id"])
    if len(completed) != 8 or [row["case_id"] for row in completed] != [row["case_id"] for row in cases[:8]]:
        raise RuntimeError("expected exactly the eight immutable completed cases")
    rows = [row["result"] for row in completed]
    prior = _prior_usage(completed)
    key = os.getenv("ZhiPu_api_key", "").strip()
    if not key:
        raise RuntimeError("ZhiPu_api_key is missing")
    domains = tuple(sorted({domain for case in cases for domain in case["allowed_domains"]}))
    provider = ZhipuSourceSearchProvider(SourceSearchSettings(
        enabled=True, api_key=key, configured_domains=domains, max_search_calls=2, max_cost_cny=1.0,
    ))
    try:
        for sequence, case in enumerate(cases[8:], start=9):
            started = time.perf_counter()
            search = await provider.search(SourceSearchRequest(
                query=case["query"], product_category=case["domain_id"], target_model=case["target_model"],
                target_fields=case["target_fields"], region=case["region"], allowed_domains=case["allowed_domains"],
                max_results=5, trigger_reason=SourceSearchTriggerReason.EXPLICIT_USER_REQUEST,
            ))
            candidate = next(iter(search.usable_candidates), None)
            row: dict[str, Any] = {
                "case_id": case["case_id"], "domain_id": case["domain_id"],
                "search_executed": search.search_executed, "network_executed": search.network_executed,
                "search_status": search.status.value, "search_attempt_count": len(search.attempts),
                "accepted_candidate_count": int(candidate is not None),
                "accepted_domain_valid": bool(candidate and _host_allowed(candidate.hostname, case["allowed_domains"])),
                "accepted_model_valid": bool(candidate and candidate.status.value == "region_matched" and candidate.target_model == case["target_model"]),
                "accepted_region_valid": bool(candidate and candidate.status.value == "region_matched" and candidate.target_region == case["region"] and candidate.observed_region == case["region"]),
                "evidence_count": 0, "lineage_complete": True, "open_boundary_intact": True,
                "trusted_eligible": False, "checker_entry_count": 0, "terminal_status": search.status.value,
                "source": None, "verified_fields": [], "unknown_fields": case["target_fields"], "conflict_fields": [],
            }
            if candidate is not None:
                pack = DomainPackLoader().load(ROOT / "smartbuy/domain_packs" / case["domain_id"])
                settings = OpenResearchSettings(enabled=True, evidence_root=runtime_root / "online-v2-9d" / case["case_id"] / "temporary-evidence")
                service = OpenResearchService(settings, pack, StaticHTMLExtractor(settings), TemporaryEvidenceStore(settings.evidence_root))
                try:
                    outcome = await service.research(
                        candidate, target_fields=case["target_fields"], allowed_domains=case["allowed_domains"],
                        provisional_product_id=f"{case['domain_id']}-{case['case_id']}-open", configuration=case["target_model"],
                        user_id="v2-9d-independent", session_id=case["case_id"], thread_id=case["case_id"],
                        request_id=case["case_id"], allow_region_discovery=True,
                    )
                finally:
                    await service.aclose()
                evidence = list(outcome.evidence)
                row.update({
                    "terminal_status": outcome.report.status,
                    "source": {"url": candidate.url, "hostname": candidate.hostname, "title": candidate.title, "observed_region": candidate.observed_region},
                    "evidence_count": len(evidence),
                    "lineage_complete": all(item.source_url and item.source_region and item.observed_at and item.content_hash for item in evidence),
                    "open_boundary_intact": all(item.evidence_scope == "open" and item.usable_for_trusted_checker is False for item in evidence),
                    "trusted_eligible": outcome.report.trusted_eligible,
                    "verified_fields": outcome.report.verified_fields, "unknown_fields": outcome.report.unknown_fields,
                    "conflict_fields": outcome.report.conflict_fields,
                    "extraction": {"status": outcome.extraction.status, "final_url": outcome.extraction.final_url, "detected_region": outcome.extraction.detected_region, "fetched_at": outcome.extraction.fetched_at, "content_hash": outcome.extraction.content_hash},
                })
            row["wall_latency_ms"] = (time.perf_counter() - started) * 1000
            _append_journal(journal_path, {"run_id": rc["run_id"], "sequence": sequence, "case_id": case["case_id"], "completed_at": _now(), "result": row})
            rows.append(row)
            live = provider.ledger.summary()
            if int(live["call_count"]) + int(prior["call_count"]) > MAX_CALLS or float(live["estimated_cost_cny"]) + float(prior["estimated_cost_cny"]) > MAX_COST_CNY:
                raise RuntimeError("Online RC2 budget exhausted")
    finally:
        await provider.aclose()
    live = provider.ledger.summary()
    api = {
        "call_count": int(prior["call_count"]) + int(live["call_count"]),
        "search_pro": int(prior["search_pro"]) + sum(item["model"] == "search_pro" for item in provider.ledger.snapshot()),
        "search_pro_sogou": int(prior["search_pro_sogou"]) + sum(item["model"] == "search_pro_sogou" for item in provider.ledger.snapshot()),
        "estimated_cost_cny": float(prior["estimated_cost_cny"]) + float(live["estimated_cost_cny"]),
        "prior_completed_prefix_usage_reconstructed": True,
    }
    scoring = score_online(cases, rows, json.loads(POLICY.read_text(encoding="utf-8")))
    payload = {
        "schema_version": "proofpick-v2-9d-independent-online-first-rc2-v1",
        "classification": "immutable first completed Online run after documented evaluator-only abort",
        "run_id": rc["run_id"], "run_number": 1, "created_at": _now(),
        "rc_config_sha256": rc["config_sha256"], "case_sha256": _sha(CASES),
        "checkpoint_resumed": True, "completed_cases_replayed": 0,
        "harness_failure_evidence": FAILURE.relative_to(ROOT).as_posix(),
        "scoring": scoring, "api": api, "cases": rows,
    }
    _atomic(output, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--rc", type=Path, default=RC)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--freeze-rc", action="store_true")
    actions.add_argument("--run-once", action="store_true")
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    runtime = _outside_repo(args.runtime_root)
    if args.freeze_rc:
        payload = freeze(runtime, args.rc)
        print(json.dumps({"status": "frozen", "config_sha256": payload["config_sha256"]}, ensure_ascii=False))
        return 0
    if args.journal is None or args.output is None:
        parser.error("--run-once requires --journal and --output")
    payload = asyncio.run(run(runtime, args.rc, _outside_repo(args.journal), args.output))
    print(json.dumps({"status": "completed", "metrics": payload["scoring"]["metrics"], "api": payload["api"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
