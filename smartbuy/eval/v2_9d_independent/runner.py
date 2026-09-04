"""Freeze and execute the second independent ProofPick RC2 evaluation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema

from smartbuy.config import load_bailian_settings
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.eval.v2_9b_independent.runner import (
    _append_journal,
    _atomic,
    _domain_agent,
    _host_allowed,
    _journal,
    _monitor_agent,
    _outside_repo,
    _row,
    _runtime_contract,
)
from smartbuy.open_research import OpenResearchService, OpenResearchSettings, StaticHTMLExtractor, TemporaryEvidenceStore
from smartbuy.orchestration import ReactOrchestrator
from smartbuy.orchestration.contracts import OrchestratorRequest
from smartbuy.providers import BailianProvider, RetryPolicy, ZhipuSourceSearchProvider
from smartbuy.source_search import SourceSearchRequest, SourceSearchSettings, SourceSearchTriggerReason

from .scorer import score_online, score_trusted


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CASES = HERE / "trusted_cases.jsonl"
ONLINE_CASES = HERE / "online_cases.jsonl"
MANIFEST = HERE / "case_manifest.json"
TRUSTED_SCHEMA = HERE / "trusted_case.schema.json"
ONLINE_SCHEMA = HERE / "online_case.schema.json"
POLICY = HERE / "scoring_policy.json"
RC_FILE = HERE / "release_candidate.json"
RC2_MANIFEST = ROOT / "smartbuy/docs/v2/v2_release_candidate_rc2_manifest.md"
PRODUCTION_COMMIT = "2d41773981c69b815efa21c0bf21675d095b920d"
PRODUCTION_TREE = "9273e9f41a3ad62ac6712a02a6ee6a4486a90f24"
RC2_COMMIT = "104a11e298d6f97d92b1a10a69a63c7b0d218a55"
RC2_PAYLOAD_SHA = "026e1ccff278c8285231223e3f2510f658e0ce2e68921c6ea94bf0a84eec1e2b"
V1_COMMIT = "d51b6668a6a45c1b01ef4e64da3c4b9ac84ed10c"
MAX_TRUSTED_REQUESTS = 500
MAX_TRUSTED_COST_CNY = 10.0
MAX_ONLINE_SEARCH_CALLS = 30
MAX_ONLINE_COST_CNY = 2.0


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _validate_cases() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    trusted, online = _jsonl(CASES), _jsonl(ONLINE_CASES)
    ts = json.loads(TRUSTED_SCHEMA.read_text(encoding="utf-8"))
    oschema = json.loads(ONLINE_SCHEMA.read_text(encoding="utf-8"))
    for row in trusted:
        jsonschema.validate(row, ts)
    for row in online:
        jsonschema.validate(row, oschema)
    if len(trusted) != 90 or len(online) != 15:
        raise RuntimeError("case count changed")
    if _sha(CASES) != manifest["trusted_case_sha256"] or _sha(ONLINE_CASES) != manifest["online_case_sha256"]:
        raise RuntimeError("case hash changed")
    if manifest["first_run_completed"] is not False:
        raise RuntimeError("case manifest is not pre-run")
    if any(row["evaluation_state"] != "frozen_unrun" or row["run_count"] != 0 for row in [*trusted, *online]):
        raise RuntimeError("case state changed")
    return trusted, online


def _manifest_payload_sha() -> str:
    text = RC2_MANIFEST.read_text(encoding="utf-8")
    begin = text.index("<!-- RC2-PAYLOAD-BEGIN -->") + len("<!-- RC2-PAYLOAD-BEGIN -->")
    end = text.index("<!-- RC2-PAYLOAD-END -->")
    payload = text[begin:end].strip() + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _definition_hashes() -> dict[str, str]:
    paths = [
        CASES, ONLINE_CASES, MANIFEST, TRUSTED_SCHEMA, ONLINE_SCHEMA, POLICY,
        HERE / "generate_cases.py", HERE / "validate_freeze.py", HERE / "scorer.py", HERE / "runner.py",
    ]
    return {path.relative_to(ROOT).as_posix(): _sha(path) for path in paths}


def _payload(runtime_root: Path) -> dict[str, Any]:
    _validate_cases()
    if _git("rev-parse", f"{PRODUCTION_COMMIT}^{{tree}}") != PRODUCTION_TREE:
        raise RuntimeError("RC2 production tree changed")
    if _git("rev-parse", f"{RC2_COMMIT}^{{commit}}") != RC2_COMMIT:
        raise RuntimeError("RC2 manifest commit unavailable")
    if _git("rev-parse", "v1.0.0-portfolio^{commit}") != V1_COMMIT:
        raise RuntimeError("V1 tag moved")
    if _manifest_payload_sha() != RC2_PAYLOAD_SHA:
        raise RuntimeError("RC2 manifest payload changed")
    return {
        "schema_version": "proofpick-v2-9d-independent-rc-v1",
        "release_candidate": "proofpick-v2-9c-rc2",
        "production_commit": PRODUCTION_COMMIT, "production_tree": PRODUCTION_TREE,
        "rc_manifest_commit": RC2_COMMIT, "rc_manifest_payload_sha256": RC2_PAYLOAD_SHA,
        "v1_commit": V1_COMMIT, "definitions": _definition_hashes(),
        "runtime": _runtime_contract(runtime_root),
        "orchestrator": "react", "cache": "cold_disabled",
        "limits": {
            "trusted_provider_requests": MAX_TRUSTED_REQUESTS, "trusted_cost_cny": MAX_TRUSTED_COST_CNY,
            "online_search_calls": MAX_ONLINE_SEARCH_CALLS, "online_cost_cny": MAX_ONLINE_COST_CNY,
        },
    }


def freeze(runtime_root: Path, output: Path) -> dict[str, Any]:
    payload = _payload(runtime_root)
    payload["run_id"] = f"v2-9d-independent-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    payload["frozen_at"] = _now()
    payload["config_sha256"] = _stable(payload)
    _atomic(output, payload)
    return payload


def _assert_rc(runtime_root: Path, path: Path) -> dict[str, Any]:
    rc = json.loads(path.read_text(encoding="utf-8"))
    current = _payload(runtime_root)
    comparable = {key: value for key, value in rc.items() if key not in {"run_id", "frozen_at", "config_sha256"}}
    if current != comparable:
        raise RuntimeError("definitions, RC2, or runtime changed after evaluator freeze")
    check = {**comparable, "run_id": rc["run_id"], "frozen_at": rc["frozen_at"]}
    if _stable(check) != rc["config_sha256"]:
        raise RuntimeError("evaluator RC hash is invalid")
    return rc


async def run_trusted(runtime_root: Path, rc_path: Path, journal_path: Path, output: Path) -> dict[str, Any]:
    cases, _ = _validate_cases()
    rc = _assert_rc(runtime_root, rc_path)
    completed = _journal(journal_path, rc["run_id"])
    if [row["case_id"] for row in completed] != [row["case_id"] for row in cases[:len(completed)]]:
        raise RuntimeError("trusted journal is not a frozen-order prefix")
    rows = [row["result"] for row in completed]
    retry = RetryPolicy(max_retries=2, base_delay_seconds=0.25, max_delay_seconds=2.0)
    async with BailianProvider(load_bailian_settings(), timeout_seconds=30, retry_policy=retry) as provider:
        monitor = ReactOrchestrator(_monitor_agent(runtime_root, provider))
        agents = {domain: ReactOrchestrator(_domain_agent(domain, runtime_root, provider)) for domain in ("laptop", "headphone")}
        for sequence, case in enumerate(cases[len(rows):], start=len(rows) + 1):
            events_before = len(provider.ledger.snapshot())
            usage = provider.ledger.snapshot()
            if events_before >= MAX_TRUSTED_REQUESTS or sum(float(item["estimated_cost_cny"]) for item in usage) >= MAX_TRUSTED_COST_CNY:
                raise RuntimeError("trusted budget exhausted")
            orchestrator = monitor if case["domain_id"] == "monitor" else agents[case["domain_id"]]
            prefix = {"monitor": "显示器：", "laptop": "笔记本：", "headphone": "耳机："}[case["domain_id"]]
            started = time.perf_counter()
            result = await orchestrator.run(OrchestratorRequest(
                query=prefix + case["question"], session_id=f"{rc['run_id']}-{case['case_id']}",
                user_id=f"independent-{case['case_id']}", thread_id=f"{rc['run_id']}-{case['case_id']}",
            ))
            if result.report is None:
                raise RuntimeError(f"missing report: {case['case_id']}")
            row = _row(case, result.report, (time.perf_counter() - started) * 1000, provider.ledger.snapshot()[events_before:])
            _append_journal(journal_path, {
                "run_id": rc["run_id"], "sequence": sequence, "case_id": case["case_id"],
                "completed_at": _now(), "result": row,
            })
            rows.append(row)
    scoring = score_trusted(cases, rows, json.loads(POLICY.read_text(encoding="utf-8")))
    events = [event for row in rows for event in row["api_events"]]
    latencies = [float(row["wall_latency_ms"]) for row in rows]
    payload = {
        "schema_version": "proofpick-v2-9d-independent-trusted-first-v1",
        "classification": "immutable first run on independently frozen RC2 cases",
        "run_id": rc["run_id"], "run_number": 1, "created_at": _now(),
        "rc_config_sha256": rc["config_sha256"], "case_sha256": _sha(CASES),
        "checkpoint_resumed": bool(completed), "completed_cases_replayed": 0,
        "scoring": scoring,
        "latency": {"average_ms": statistics.mean(latencies), "p95_ms": sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)]},
        "api": {
            "request_count": len(events),
            "by_model": {model: sum(item["model"] == model for item in events) for model in sorted({item["model"] for item in events})},
            "input_tokens": sum(int(item["input_tokens"]) for item in events),
            "output_tokens": sum(int(item["output_tokens"]) for item in events),
            "estimated_cost_cny": sum(float(item["estimated_cost_cny"]) for item in events),
            "retry_count": sum(max(0, int(item["attempts"]) - 1) for item in events),
            "failed_requests": sum(not item["success"] for item in events),
        },
        "cases": rows,
    }
    _atomic(output, payload)
    return payload


async def run_online(runtime_root: Path, rc_path: Path, journal_path: Path, output: Path) -> dict[str, Any]:
    _, cases = _validate_cases()
    rc = _assert_rc(runtime_root, rc_path)
    completed = _journal(journal_path, rc["run_id"])
    if [row["case_id"] for row in completed] != [row["case_id"] for row in cases[:len(completed)]]:
        raise RuntimeError("online journal is not a frozen-order prefix")
    rows = [row["result"] for row in completed]
    key = os.getenv("ZhiPu_api_key", "").strip()
    if not key:
        raise RuntimeError("ZhiPu_api_key is missing")
    domains = tuple(sorted({domain for case in cases for domain in case["allowed_domains"]}))
    provider = ZhipuSourceSearchProvider(SourceSearchSettings(
        enabled=True, api_key=key, configured_domains=domains, max_search_calls=2, max_cost_cny=1.0,
    ))
    try:
        for sequence, case in enumerate(cases[len(rows):], start=len(rows) + 1):
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
            usage = provider.ledger.summary()
            if int(usage["call_count"]) > MAX_ONLINE_SEARCH_CALLS or float(usage["estimated_cost_cny"]) > MAX_ONLINE_COST_CNY:
                raise RuntimeError("online budget exhausted")
    finally:
        await provider.aclose()
    scoring = score_online(cases, rows, json.loads(POLICY.read_text(encoding="utf-8")))
    payload = {
        "schema_version": "proofpick-v2-9d-independent-online-first-v1",
        "classification": "immutable first online run on independently frozen RC2 cases",
        "run_id": rc["run_id"], "run_number": 1, "created_at": _now(),
        "rc_config_sha256": rc["config_sha256"], "case_sha256": _sha(ONLINE_CASES),
        "checkpoint_resumed": bool(completed), "completed_cases_replayed": 0,
        "scoring": scoring, "api": provider.ledger.summary(), "cases": rows,
    }
    _atomic(output, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--rc", type=Path, default=RC_FILE)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--freeze-rc", action="store_true")
    actions.add_argument("--run-trusted-once", action="store_true")
    actions.add_argument("--run-online-once", action="store_true")
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    runtime = _outside_repo(args.runtime_root)
    if args.freeze_rc:
        payload = freeze(runtime, args.rc)
        print(json.dumps({"status": "frozen", "run_id": payload["run_id"], "config_sha256": payload["config_sha256"]}, ensure_ascii=False))
        return 0
    if args.journal is None or args.output is None:
        parser.error("run actions require --journal and --output")
    journal, output = _outside_repo(args.journal), args.output
    if args.run_trusted_once:
        payload = asyncio.run(run_trusted(runtime, args.rc, journal, output))
    else:
        payload = asyncio.run(run_online(runtime, args.rc, journal, output))
    print(json.dumps({"status": "completed", "scoring": payload["scoring"]["metrics"], "api": payload["api"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
