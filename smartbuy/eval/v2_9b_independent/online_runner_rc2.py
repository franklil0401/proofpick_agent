"""Evaluator-only RC2 for the V2-9B online safety run.

RC1 was stopped by a harness KeyError after reaching one case.  This file
keeps that incident immutable, replaces the reached case, and uses an
append-only external journal so no completed online task is silently replayed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema

from smartbuy.domain_packs import DomainPackLoader
from smartbuy.open_research import OpenResearchService, OpenResearchSettings, StaticHTMLExtractor, TemporaryEvidenceStore
from smartbuy.providers import ZhipuSourceSearchProvider
from smartbuy.source_search import SourceSearchRequest, SourceSearchSettings, SourceSearchTriggerReason

from .runner import PRODUCTION_COMMIT, RC_COMMIT, V1_COMMIT, _git, _host_allowed, _outside_repo, _runtime_contract
from .scorer import score_online


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CASES = HERE / "online_cases_rc2.jsonl"
MANIFEST = HERE / "online_case_manifest_rc2.json"
SCHEMA = HERE / "online_case.schema.json"
POLICY = HERE / "scoring_policy.json"
SCORER = HERE / "scorer.py"
RUNNER = HERE / "online_runner_rc2.py"
RC1_FAILURE = ROOT / "smartbuy/eval/results/v2_9b_independent_online_harness_failure.json"
MAX_SEARCH_CALLS = 30
MAX_COST_CNY = 2.0


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _load_cases() -> list[dict[str, Any]]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line]
    for row in rows:
        jsonschema.validate(row, schema)
    if (
        len(rows) != 15
        or _sha(CASES) != manifest["case_sha256"]
        or manifest["first_run_completed"] is not False
        or any(row["evaluation_state"] != "frozen_unrun" or row["run_count"] != 0 for row in rows)
        or any(sum(row["domain_id"] == domain for row in rows) != 5 for domain in ("monitor", "laptop", "headphone"))
        or "web-mon-001" in {row["case_id"] for row in rows}
        or "web-mon-006" not in {row["case_id"] for row in rows}
    ):
        raise RuntimeError("online evaluator RC2 case freeze is invalid")
    return rows


def _rc_payload(runtime_root: Path) -> dict[str, Any]:
    _load_cases()
    if _git("rev-parse", f"{RC_COMMIT}^{{commit}}") != RC_COMMIT:
        raise RuntimeError("V2-9A RC commit is unavailable")
    if _git("rev-parse", "v1.0.0-portfolio^{commit}") != V1_COMMIT:
        raise RuntimeError("V1 tag moved")
    definitions = (CASES, MANIFEST, SCHEMA, POLICY, SCORER, RUNNER, RC1_FAILURE)
    return {
        "schema_version": "proofpick-v2-9b-independent-online-rc2-v1",
        "release_candidate": "proofpick-v2-9a-rc1",
        "production_commit": PRODUCTION_COMMIT,
        "production_tree": _git("rev-parse", f"{PRODUCTION_COMMIT}^{{tree}}"),
        "rc_manifest_commit": RC_COMMIT,
        "v1_commit": V1_COMMIT,
        "definitions": {path.relative_to(ROOT).as_posix(): _sha(path) for path in definitions},
        "runtime": _runtime_contract(runtime_root),
        "replaces_online_case": "web-mon-001",
        "replacement_online_case": "web-mon-006",
        "limits": {"search_calls": MAX_SEARCH_CALLS, "cost_cny": MAX_COST_CNY},
    }


def _atomic(path: Path, payload: Any) -> None:
    if path.exists():
        raise RuntimeError(f"immutable output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def freeze(runtime_root: Path, output: Path) -> dict[str, Any]:
    payload = _rc_payload(runtime_root)
    payload["run_id"] = f"v2-9b-online-rc2-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    payload["frozen_at"] = _now()
    payload["config_sha256"] = _stable(payload)
    _atomic(output, payload)
    return payload


def _assert_rc(runtime_root: Path, path: Path) -> dict[str, Any]:
    rc = json.loads(path.read_text(encoding="utf-8"))
    comparable = {key: value for key, value in rc.items() if key not in {"run_id", "frozen_at", "config_sha256"}}
    if comparable != _rc_payload(runtime_root):
        raise RuntimeError("online RC2 changed after freeze")
    sealed = {**comparable, "run_id": rc["run_id"], "frozen_at": rc["frozen_at"]}
    if _stable(sealed) != rc["config_sha256"]:
        raise RuntimeError("online RC2 hash is invalid")
    return rc


def _append(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _journal(path: Path, run_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if any(row.get("run_id") != run_id for row in rows):
        raise RuntimeError("online journal belongs to another run")
    if len({row["case_id"] for row in rows}) != len(rows):
        raise RuntimeError("online journal duplicates a completed case")
    return rows


async def run(runtime_root: Path, rc_path: Path, journal_path: Path, output: Path) -> dict[str, Any]:
    cases = _load_cases()
    rc = _assert_rc(runtime_root, rc_path)
    completed = _journal(journal_path, rc["run_id"])
    if [row["case_id"] for row in completed] != [row["case_id"] for row in cases[:len(completed)]]:
        raise RuntimeError("online journal is not a prefix of frozen order")
    rows = [row["result"] for row in completed]
    key = os.getenv("ZhiPu_api_key", "").strip()
    if not key:
        raise RuntimeError("ZhiPu_api_key is missing")
    domains = tuple(sorted({domain for case in cases for domain in case["allowed_domains"]}))
    provider = ZhipuSourceSearchProvider(SourceSearchSettings(
        enabled=True, api_key=key, configured_domains=domains,
        max_search_calls=2, max_cost_cny=1.0,
    ))
    try:
        for sequence, case in enumerate(cases[len(rows):], start=len(rows) + 1):
            started = time.perf_counter()
            search = await provider.search(SourceSearchRequest(
                query=case["query"], product_category=case["domain_id"],
                target_model=case["target_model"], target_fields=case["target_fields"],
                region=case["region"], allowed_domains=case["allowed_domains"],
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
                "trusted_eligible": False, "checker_entry_count": 0,
                "terminal_status": search.status.value, "source": None,
                "verified_fields": [], "unknown_fields": case["target_fields"], "conflict_fields": [],
            }
            if candidate is not None:
                pack = DomainPackLoader().load(ROOT / "smartbuy/domain_packs" / case["domain_id"])
                research_settings = OpenResearchSettings(
                    enabled=True,
                    evidence_root=runtime_root / "online-rc2" / case["case_id"] / "temporary-evidence",
                )
                service = OpenResearchService(
                    research_settings, pack, StaticHTMLExtractor(research_settings),
                    TemporaryEvidenceStore(research_settings.evidence_root),
                )
                try:
                    outcome = await service.research(
                        candidate, target_fields=case["target_fields"],
                        allowed_domains=case["allowed_domains"],
                        provisional_product_id=f"{case['domain_id']}-{case['case_id']}-open",
                        configuration=case["target_model"], user_id="v2-9b-independent",
                        session_id=case["case_id"], thread_id=case["case_id"],
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
                    "verified_fields": outcome.report.verified_fields,
                    "unknown_fields": outcome.report.unknown_fields,
                    "conflict_fields": outcome.report.conflict_fields,
                    "extraction": {"status": outcome.extraction.status, "final_url": outcome.extraction.final_url, "detected_region": outcome.extraction.detected_region, "fetched_at": outcome.extraction.fetched_at, "content_hash": outcome.extraction.content_hash},
                })
            row["wall_latency_ms"] = (time.perf_counter() - started) * 1000
            _append(journal_path, {"run_id": rc["run_id"], "sequence": sequence, "case_id": case["case_id"], "completed_at": _now(), "result": row})
            rows.append(row)
            usage = provider.ledger.summary()
            if int(usage["call_count"]) > MAX_SEARCH_CALLS or float(usage["estimated_cost_cny"]) > MAX_COST_CNY:
                raise RuntimeError("online RC2 budget exhausted")
    finally:
        await provider.aclose()
    scoring = score_online(cases, rows, json.loads(POLICY.read_text(encoding="utf-8")))
    payload = {
        "schema_version": "proofpick-v2-9b-independent-online-first-rc2-v1",
        "classification": "immutable first completed run after documented evaluator-only RC1 abort",
        "run_id": rc["run_id"], "run_number": 1, "created_at": _now(),
        "rc_config_sha256": rc["config_sha256"], "case_sha256": _sha(CASES),
        "checkpoint_resumed": bool(completed), "completed_cases_replayed": 0,
        "scoring": scoring, "api": provider.ledger.summary(), "cases": rows,
    }
    _atomic(output, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--rc", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--freeze-rc", action="store_true")
    action.add_argument("--run-once", action="store_true")
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    runtime = _outside_repo(args.runtime_root)
    if args.freeze_rc:
        payload = freeze(runtime, args.rc)
        print(json.dumps({"status": "frozen", "run_id": payload["run_id"], "config_sha256": payload["config_sha256"]}, ensure_ascii=False))
        return 0
    if args.journal is None or args.output is None:
        parser.error("--run-once requires --journal and --output")
    payload = asyncio.run(run(runtime, args.rc, _outside_repo(args.journal), args.output))
    print(json.dumps({"status": "completed", "scoring": payload["scoring"]["metrics"], "api": payload["api"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
