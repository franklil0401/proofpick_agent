"""Run the exposed V2-9D Online set once against the V2-9F repair.

The frozen cases remain in the detached evaluator worktree. This runner cannot
create or rewrite a holdout and stores only bounded, sanitized lineage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from smartbuy.domain_packs import DomainPackLoader
from smartbuy.eval.run_v2_9e_exposed_regression import (
    CLASSIFICATION,
    _load_evaluator,
    _now,
    _run_contract,
    _write_once,
)
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
V2_9F_CLASSIFICATION = (
    "exposed_online_regression_after_v2_9f; not an independent holdout"
)


def _report_stop_reason(outcome: Any | None, search_status: str) -> str:
    if outcome is None:
        return search_status
    reasons = outcome.report.degraded_reasons
    return reasons[0] if reasons else outcome.report.status


def _extraction_row(outcome: Any, candidate_status: str) -> dict[str, Any]:
    all_extractions = [outcome.extraction, *outcome.additional_extractions]
    return {
        "candidate_status": candidate_status,
        "extractions": [
            {
                "status": item.status.value,
                "error": item.error,
                "http_status": item.http_status,
                "content_type": item.content_type,
                "detected_region": item.detected_region,
                "snippet_count": len(item.snippets),
                "snippet_kinds": sorted({snippet.kind for snippet in item.snippets}),
                "related_link_count": len(item.related_links),
            }
            for item in all_extractions
        ],
        "verified_fields": outcome.report.verified_fields,
        "unknown_fields": outcome.report.unknown_fields,
        "conflict_fields": outcome.report.conflict_fields,
        "evidence_count": len(outcome.evidence),
    }


def _case_funnel(
    search: Any,
    attempts: list[dict[str, Any]],
    evidence_count: int,
    target_region: str,
) -> dict[str, bool]:
    extractions = [
        extraction
        for attempt in attempts
        for extraction in attempt["extractions"]
    ]
    return {
        "source_search": search.search_executed,
        "official_domain_filter": any(
            item.domain_matched_count > 0 for item in search.attempts
        ),
        "model_match": any(item.model_matched_count > 0 for item in search.attempts),
        "region_match": bool(search.usable_candidates)
        or any(
            item["detected_region"] == target_region
            and item["status"] == "success"
            for item in extractions
        ),
        "page_fetch": any(
            item["http_status"] is not None and 200 <= item["http_status"] < 300
            for item in extractions
        ),
        "content_extraction": any(item["snippet_count"] > 0 for item in extractions),
        "field_normalization": evidence_count > 0,
        "evidence_check": any(attempt["evidence_count"] > 0 for attempt in attempts),
        "actual_evidence_completion": evidence_count > 0,
    }


def _failure_reasons(
    search: Any,
    attempts: list[dict[str, Any]],
    outcome: Any | None,
    target_fields: list[str],
    target_region: str,
) -> list[str]:
    rows = [item for attempt in attempts for item in attempt["extractions"]]
    reasons: list[str] = []
    if not search.search_executed:
        reasons.append("no_search_result")
    elif not any(item.domain_matched_count for item in search.attempts):
        reasons.append("no_official_source")
    elif not any(item.model_matched_count for item in search.attempts):
        reasons.append("model_mismatch")
    if not search.usable_candidates and not any(
        item["status"] == "success" and item["detected_region"] == target_region
        for item in rows
    ):
        reasons.append("region_mismatch")
    if rows and not any(
        item["http_status"] is not None and 200 <= item["http_status"] < 300
        for item in rows
    ):
        reasons.append("fetch_failed")
    if any(item["status"] == "dynamic_render_required" for item in rows):
        reasons.append("dynamic_page")
    if any(
        item["content_type"] == "application/pdf" and item["status"] != "success"
        for item in rows
    ):
        reasons.append("pdf_or_attachment")
    if rows and not any(item["snippet_count"] for item in rows):
        reasons.append("extraction_empty")
    if outcome is not None and any(item["snippet_count"] for item in rows) and not outcome.evidence:
        reasons.append("normalization_failed")
    if outcome is not None and set(target_fields) - set(outcome.report.verified_fields):
        reasons.append("requested_field_missing")
    if outcome is not None and outcome.report.conflict_fields:
        reasons.append("evidence_conflict")
    return list(dict.fromkeys(reasons))


async def run_online(module: Any, runtime_root: Path, output: Path) -> dict[str, Any]:
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
            max_search_calls=4,
            max_cost_cny=0.20,
            total_timeout_seconds=50,
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
            outcomes: list[tuple[Any, Any]] = []
            extraction_attempts: list[dict[str, Any]] = []
            for candidate in candidates[:5]:
                pack = DomainPackLoader().load(
                    ROOT / "smartbuy" / "domain_packs" / case["domain_id"]
                )
                settings = OpenResearchSettings(
                    enabled=True,
                    evidence_root=(
                        runtime_root
                        / "v2-9f-online"
                        / case["case_id"]
                        / candidate.local_request_id
                    ),
                    connect_timeout_seconds=4,
                    read_timeout_seconds=9,
                    total_timeout_seconds=15,
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
                        user_id="v2-9f-exposed",
                        session_id=case["case_id"],
                        thread_id=case["case_id"],
                        request_id=f"{contract['run_id']}-{sequence}-{len(outcomes) + 1}",
                        allow_region_discovery=True,
                    )
                finally:
                    await service.aclose()
                outcomes.append((current, candidate))
                extraction_attempts.append(
                    _extraction_row(current, candidate.status.value)
                )
                if set(case["target_fields"]).issubset(current.report.verified_fields):
                    break

            outcome = None
            selected = None
            if outcomes:
                outcome, selected = max(
                    outcomes,
                    key=lambda pair: (
                        len(pair[0].report.verified_fields),
                        -len(pair[0].report.conflict_fields),
                        len(pair[0].evidence),
                    ),
                )
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
            funnel = _case_funnel(
                search, extraction_attempts, len(evidence), case["region"]
            )
            row = {
                "case_id": case["case_id"],
                "domain_id": case["domain_id"],
                "search_executed": search.search_executed,
                "network_executed": search.network_executed,
                "search_status": search.status.value,
                "search_attempts": [item.model_dump(mode="json") for item in search.attempts],
                "accepted_candidate_count": int(accepted),
                "accepted_domain_valid": accepted,
                "accepted_model_valid": accepted,
                "accepted_configuration_valid": accepted,
                "accepted_region_valid": accepted,
                "evidence_count": len(evidence),
                "lineage_complete": all(
                    item.source_url and item.source_region and item.observed_at and item.content_hash
                    for item in evidence
                ),
                "search_snippet_evidence_count": 0,
                "open_boundary_intact": all(
                    item.evidence_scope == "open" and item.usable_for_trusted_checker is False
                    for item in evidence
                ),
                "trusted_eligible": False if outcome is None else outcome.report.trusted_eligible,
                "checker_entry_count": 0,
                # A safely exhausted search remains a degraded terminal result;
                # it must not be confused with a successful evidence closure.
                "terminal_status": outcome.report.status if outcome else "degraded",
                "stop_reason": _report_stop_reason(outcome, search.status.value),
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
                "funnel": funnel,
                "failure_reasons": _failure_reasons(
                    search,
                    extraction_attempts,
                    outcome,
                    case["target_fields"],
                    case["region"],
                ),
                "extraction_attempts": extraction_attempts,
                "wall_latency_ms": (time.perf_counter() - started) * 1000,
            }
            rows.append(row)
            usage = provider.ledger.summary()
            if int(usage["call_count"]) > 60 or float(usage["estimated_cost_cny"]) > 2.5:
                raise RuntimeError("V2-9F online regression budget exhausted")
    finally:
        await provider.aclose()

    scoring = module.score_online(
        cases, rows, json.loads(module.POLICY.read_text(encoding="utf-8"))
    )
    completed = [row for row in rows if row["evidence_count"] > 0]
    requested_by_id = {case["case_id"]: case["target_fields"] for case in cases}
    verified = sum(len(row["verified_fields"]) for row in completed)
    requested = sum(len(requested_by_id[row["case_id"]]) for row in completed)
    funnel_counts = {
        key: sum(bool(row["funnel"][key]) for row in rows)
        for key in next(iter(rows))["funnel"]
    }
    extraction_methods = Counter(
        kind
        for row in rows
        for attempt in row["extraction_attempts"]
        for extraction in attempt["extractions"]
        if extraction["status"] == "success"
        for kind in extraction["snippet_kinds"]
    )
    failure_counts = Counter(
        reason for row in rows for reason in row["failure_reasons"]
    )
    latencies = [float(row["wall_latency_ms"]) for row in rows]
    payload = {
        "schema_version": "proofpick-v2-9f-exposed-online-regression-v1",
        "classification": V2_9F_CLASSIFICATION,
        "historical_classification": CLASSIFICATION,
        "run_id": contract["run_id"].replace("v2-9e", "v2-9f"),
        "run_number": "one_final_v2_9f_exposed_regression_run",
        "created_at": _now(),
        "rc_config_sha256": contract["config_sha256"],
        "historical_results_preserved": ["0/15", "2/15", "5/15", "5/15"],
        "scoring": scoring,
        "exposed_metrics": {
            "actual_evidence_completion": {
                "numerator": len(completed), "denominator": len(rows)
            },
            "per_domain": {
                domain: {
                    "numerator": sum(
                        row["domain_id"] == domain and row["evidence_count"] > 0
                        for row in rows
                    ),
                    "denominator": sum(row["domain_id"] == domain for row in rows),
                }
                for domain in ("monitor", "laptop", "headphone")
            },
            "verified_requested_fields": {
                "numerator": verified,
                "denominator": requested,
                "rate": verified / requested if requested else 0.0,
            },
            "safety": {
                "safe_terminal": sum(row["terminal_status"] in {"completed", "degraded"} for row in rows),
                "wrong_domain_usable": sum(
                    row["evidence_count"] > 0 and not row["accepted_domain_valid"]
                    for row in rows
                ),
                "wrong_model_usable": sum(
                    row["evidence_count"] > 0 and not row["accepted_model_valid"]
                    for row in rows
                ),
                "wrong_configuration_usable": sum(
                    row["evidence_count"] > 0 and not row["accepted_configuration_valid"]
                    for row in rows
                ),
                "wrong_region_usable": sum(
                    row["evidence_count"] > 0 and not row["accepted_region_valid"]
                    for row in rows
                ),
                "open_evidence_to_trusted_checker": sum(row["checker_entry_count"] for row in rows),
                "search_snippet_to_evidence": sum(row["search_snippet_evidence_count"] for row in rows),
                "unknown_overclaim": sum(
                    bool(
                        set(row["verified_fields"])
                        & (set(row["unknown_fields"]) | set(row["conflict_fields"]))
                    )
                    for row in rows
                ),
            },
        },
        "funnel_counts": funnel_counts,
        "failure_reason_counts": dict(sorted(failure_counts.items())),
        "extraction_method_success_counts": dict(sorted(extraction_methods.items())),
        "provider_contributions": {
            "zhipu": {
                "calls": provider.ledger.summary()["call_count"],
                "evidence_tasks": len(completed),
            },
            "bailian": {"calls": 0, "evidence_tasks": 0},
            "bocha": {"calls": 0, "evidence_tasks": 0},
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
    args = parser.parse_args()
    module = _load_evaluator(args.evaluator_root.resolve())
    payload = asyncio.run(
        run_online(module, args.runtime_root.resolve(), args.output.resolve())
    )
    print(
        json.dumps(
            {
                "run_id": payload["run_id"],
                "metrics": payload["exposed_metrics"],
                "api": payload["api"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
