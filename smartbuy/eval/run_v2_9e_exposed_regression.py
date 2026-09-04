"""Run the already-exposed V2-9D definitions without copying evaluator code.

This adapter is intentionally unable to create a holdout. It loads the frozen
definitions from a detached evaluator worktree and labels every output as an
exposed regression after V2-9E repair.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
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
from urllib.parse import urlsplit

from smartbuy.domain_packs import DomainPackLoader
from smartbuy.open_research import (
    OpenResearchService,
    OpenResearchSettings,
    StaticHTMLExtractor,
    TemporaryEvidenceStore,
)
from smartbuy.providers import ZhipuSourceSearchProvider
from smartbuy.source_search import (
    SourceSearchRequest,
    SourceSearchSettings,
    SourceSearchTriggerReason,
)
from smartbuy.source_search.validator import hostname_allowed


ROOT = Path(__file__).resolve().parents[2]
EVALUATOR_COMMIT = "126486861e08a33a94d4c6c5ffeafc121db2ee5e"
CLASSIFICATION = "exposed_regression_after_v2_9e; not an independent holdout"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git(*args: str, root: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, encoding="utf-8"
    ).strip()


def _stable(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_once(path: Path, payload: Any) -> None:
    if path.exists():
        raise RuntimeError(f"exposed regression output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _load_evaluator(eval_root: Path):
    if _git("rev-parse", "HEAD", root=eval_root) != EVALUATOR_COMMIT:
        raise RuntimeError("evaluator worktree is not the frozen V2-9D commit")
    import smartbuy.eval as eval_package

    external_eval = str((eval_root / "smartbuy" / "eval").resolve())
    if external_eval not in eval_package.__path__:
        eval_package.__path__.append(external_eval)
    module = importlib.import_module("smartbuy.eval.v2_9d_independent.runner")
    base = importlib.import_module("smartbuy.eval.v2_9b_independent.runner")
    # Evaluator definitions stay in the detached worktree; production modules,
    # Domain Packs and prompts come from the current repair branch.
    module.ROOT = ROOT
    base.ROOT = ROOT
    return module


def _run_contract(module, runtime_root: Path, kind: str) -> dict[str, Any]:
    trusted, online = module._validate_cases()
    cases = trusted if kind == "trusted" else online
    return {
        "run_id": f"v2-9e-exposed-{kind}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}",
        "config_sha256": _stable(
            {
                "classification": CLASSIFICATION,
                "production_commit": _git("rev-parse", "HEAD"),
                "production_tree": _git("rev-parse", "HEAD^{tree}"),
                "evaluator_commit": EVALUATOR_COMMIT,
                "case_ids": [item["case_id"] for item in cases],
                "runtime": module._runtime_contract(runtime_root),
                "cache": "cold_disabled",
            }
        ),
    }


async def run_trusted(
    module, runtime_root: Path, journal: Path, output: Path
) -> dict[str, Any]:
    contract = _run_contract(module, runtime_root, "trusted")
    module._assert_rc = lambda _runtime, _path: contract
    temporary = output.with_suffix(".independent-adapter.tmp.json")
    temporary.unlink(missing_ok=True)
    payload = await module.run_trusted(runtime_root, output, journal, temporary)
    temporary.unlink(missing_ok=True)
    payload.update(
        {
            "schema_version": "proofpick-v2-9e-exposed-trusted-regression-v1",
            "classification": CLASSIFICATION,
            "run_number": "one_exposed_regression_run",
            "production_commit": _git("rev-parse", "HEAD"),
            "production_tree": _git("rev-parse", "HEAD^{tree}"),
            "evaluator_commit": EVALUATOR_COMMIT,
            "historical_first_result_preserved": "72/90",
        }
    )
    _write_once(output, payload)
    return payload


async def run_online(module, runtime_root: Path, output: Path) -> dict[str, Any]:
    _, cases = module._validate_cases()
    contract = _run_contract(module, runtime_root, "online")
    api_key = os.getenv("ZhiPu_api_key", "").strip()
    if not api_key:
        raise RuntimeError("ZhiPu_api_key is missing")
    domains = tuple(sorted({domain for case in cases for domain in case["allowed_domains"]}))
    provider = ZhipuSourceSearchProvider(
        SourceSearchSettings(
            enabled=True,
            api_key=api_key,
            configured_domains=domains,
            max_search_calls=2,
            max_cost_cny=1.0,
        )
    )
    rows: list[dict[str, Any]] = []
    try:
        for sequence, case in enumerate(cases, start=1):
            started = time.perf_counter()
            search = await provider.search(
                SourceSearchRequest(
                    query=case["query"],
                    product_category=case["domain_id"],
                    target_model=case["target_model"],
                    target_fields=case["target_fields"],
                    region=case["region"],
                    allowed_domains=case["allowed_domains"],
                    max_results=5,
                    trigger_reason=SourceSearchTriggerReason.EXPLICIT_USER_REQUEST,
                )
            )
            candidates = list(search.usable_candidates)
            candidates.extend(
                item
                for item in search.navigation_candidates
                if item.url not in {candidate.url for candidate in candidates}
            )
            outcome = None
            selected = None
            attempts: list[dict[str, Any]] = []
            for candidate in candidates[:3]:
                pack = DomainPackLoader().load(
                    ROOT / "smartbuy" / "domain_packs" / case["domain_id"]
                )
                settings = OpenResearchSettings(
                    enabled=True,
                    evidence_root=(
                        runtime_root / "v2-9e-online" / case["case_id"] / candidate.local_request_id
                    ),
                )
                service = OpenResearchService(
                    settings,
                    pack,
                    StaticHTMLExtractor(settings),
                    TemporaryEvidenceStore(settings.evidence_root),
                )
                try:
                    current = await service.research(
                        candidate,
                        target_fields=case["target_fields"],
                        allowed_domains=case["allowed_domains"],
                        provisional_product_id=f"{case['domain_id']}-{case['case_id']}-open",
                        configuration=case["target_model"],
                        user_id="v2-9e-exposed",
                        session_id=case["case_id"],
                        thread_id=case["case_id"],
                        request_id=f"{contract['run_id']}-{sequence}",
                        allow_region_discovery=True,
                    )
                finally:
                    await service.aclose()
                attempts.append(
                    {
                        "candidate_status": candidate.status.value,
                        "extraction_status": current.extraction.status.value,
                        "detected_region": current.extraction.detected_region,
                        "verified_fields": current.report.verified_fields,
                    }
                )
                if outcome is None or len(current.evidence) > len(outcome.evidence):
                    outcome, selected = current, candidate
                if set(case["target_fields"]).issubset(current.report.verified_fields):
                    outcome, selected = current, candidate
                    break
            evidence = list(outcome.evidence) if outcome else []
            accepted = bool(
                outcome
                and evidence
                and outcome.extraction.detected_region == case["region"]
                and outcome.extraction.final_url
                and hostname_allowed(
                    urlsplit(outcome.extraction.final_url).hostname,
                    case["allowed_domains"],
                )
            )
            row = {
                "case_id": case["case_id"],
                "domain_id": case["domain_id"],
                "search_executed": search.search_executed,
                "network_executed": search.network_executed,
                "search_status": search.status.value,
                "search_attempt_count": len(search.attempts),
                "accepted_candidate_count": int(accepted),
                "accepted_domain_valid": accepted,
                "accepted_model_valid": accepted,
                "accepted_region_valid": accepted,
                "evidence_count": len(evidence),
                "lineage_complete": all(
                    item.source_url and item.source_region and item.observed_at and item.content_hash
                    for item in evidence
                ),
                "open_boundary_intact": all(
                    item.evidence_scope == "open" and item.usable_for_trusted_checker is False
                    for item in evidence
                ),
                "trusted_eligible": False if outcome is None else outcome.report.trusted_eligible,
                "checker_entry_count": 0,
                "terminal_status": outcome.report.status if outcome else search.status.value,
                "source": (
                    None
                    if not accepted
                    else {
                        "url": outcome.extraction.final_url,
                        "hostname": urlsplit(outcome.extraction.final_url).hostname,
                        "title": outcome.extraction.title,
                        "observed_region": outcome.extraction.detected_region,
                        "discovered_from": selected.status.value if selected else None,
                    }
                ),
                "verified_fields": outcome.report.verified_fields if outcome else [],
                "unknown_fields": outcome.report.unknown_fields if outcome else case["target_fields"],
                "conflict_fields": outcome.report.conflict_fields if outcome else [],
                "funnel": {
                    "raw_result_count": search.raw_result_count,
                    "scanned_result_count": search.scanned_result_count,
                    "usable_candidates": len(search.usable_candidates),
                    "navigation_candidates": len(search.navigation_candidates),
                    "extraction_attempts": attempts,
                },
                "wall_latency_ms": (time.perf_counter() - started) * 1000,
            }
            rows.append(row)
            usage = provider.ledger.summary()
            if int(usage["call_count"]) > 30 or float(usage["estimated_cost_cny"]) > 2.0:
                raise RuntimeError("online exposed regression budget exhausted")
    finally:
        await provider.aclose()
    scoring = module.score_online(
        cases, rows, json.loads(module.POLICY.read_text(encoding="utf-8"))
    )
    completed = [row for row in rows if row["evidence_count"] > 0]
    verified = sum(len(row["verified_fields"]) for row in completed)
    requested = sum(len(next(case for case in cases if case["case_id"] == row["case_id"])["target_fields"]) for row in completed)
    latencies = [float(row["wall_latency_ms"]) for row in rows]
    payload = {
        "schema_version": "proofpick-v2-9e-exposed-online-regression-v1",
        "classification": CLASSIFICATION,
        "run_id": contract["run_id"],
        "run_number": "one_exposed_regression_run",
        "created_at": _now(),
        "rc_config_sha256": contract["config_sha256"],
        "production_commit": _git("rev-parse", "HEAD"),
        "production_tree": _git("rev-parse", "HEAD^{tree}"),
        "evaluator_commit": EVALUATOR_COMMIT,
        "historical_first_result_preserved": "0/15 actual evidence completion",
        "scoring": scoring,
        "exposed_metrics": {
            "actual_evidence_completion": {"numerator": len(completed), "denominator": len(rows)},
            "per_domain": {
                domain: {
                    "numerator": sum(row["domain_id"] == domain and row["evidence_count"] > 0 for row in rows),
                    "denominator": sum(row["domain_id"] == domain for row in rows),
                }
                for domain in ("monitor", "laptop", "headphone")
            },
            "verified_requested_fields": {
                "numerator": verified,
                "denominator": requested,
                "rate": verified / requested if requested else 0.0,
            },
        },
        "latency": {
            "average_ms": statistics.mean(latencies),
            "p95_ms": sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)],
        },
        "api": provider.ledger.summary(),
        "cases": rows,
    }
    _write_once(output, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluator-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--journal", type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--trusted", action="store_true")
    action.add_argument("--online", action="store_true")
    args = parser.parse_args()
    module = _load_evaluator(args.evaluator_root.resolve())
    if args.trusted:
        if args.journal is None:
            parser.error("--trusted requires --journal")
        payload = asyncio.run(
            run_trusted(module, args.runtime_root.resolve(), args.journal.resolve(), args.output.resolve())
        )
        metrics = payload["scoring"]["metrics"]
    else:
        payload = asyncio.run(run_online(module, args.runtime_root.resolve(), args.output.resolve()))
        metrics = payload["exposed_metrics"]
    print(json.dumps({"run_id": payload["run_id"], "metrics": metrics, "api": payload["api"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
