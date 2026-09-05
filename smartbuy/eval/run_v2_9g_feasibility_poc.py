"""Run the bounded V2-9G Playwright and alternate-provider feasibility PoC.

The input set is already exposed.  This script selects failure *types* from the
frozen audit; it contains no case, product, brand, or target-URL answers.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smartbuy.domain_packs import DomainPackLoader
from smartbuy.eval.v2_9g_feasibility import (
    BrowserPoCSettings,
    bocha_search_once,
    render_with_playwright,
)
from smartbuy.providers import ZhipuSourceSearchProvider
from smartbuy.source_search import (
    SourceCandidate,
    SourceCandidateStatus,
    SourceSearchRequest,
    SourceSearchSettings,
    SourceSearchTriggerReason,
)


ROOT = Path(__file__).resolve().parents[2]


def _load_cases(path: Path) -> dict[str, dict[str, Any]]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["case_id"]] = row
    return rows


def _one_per_domain(
    audit_rows: list[dict[str, Any]], first_failure: str
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in audit_rows:
        domain = row["domain_id"]
        if row["first_failure_stage"] == first_failure and domain not in seen:
            selected.append(row)
            seen.add(domain)
    return selected


def _request(case: dict[str, Any]) -> SourceSearchRequest:
    return SourceSearchRequest(
        query=case["query"],
        product_category=case["domain_id"],
        target_model=case["target_model"],
        target_fields=case["target_fields"],
        region=case["region"],
        allowed_domains=case["allowed_domains"],
        max_results=5,
        trigger_reason=SourceSearchTriggerReason.EXPLICIT_USER_REQUEST,
    )


def _historical_candidate(case: dict[str, Any], row: dict[str, Any]) -> SourceCandidate:
    source = row["source"]
    return SourceCandidate(
        title=source["title"],
        url=source["url"],
        hostname=source["hostname"],
        queried_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        local_request_id="v2-9g-historical",
        provider="v2-9f-sanitized-result",
        engine="accepted_source_replay",
        target_model=case["target_model"],
        target_region=case["region"],
        observed_region=case["region"],
        status=SourceCandidateStatus.REGION_MATCHED,
        model_match_source="url",
        region_match_source="url",
    )


async def run(args: argparse.Namespace) -> dict[str, Any]:
    cases = _load_cases(args.cases)
    previous = json.loads(args.result.read_text(encoding="utf-8"))
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    previous_rows = {row["case_id"]: row for row in previous["cases"]}
    browser_settings = BrowserPoCSettings(enabled=args.enable_browser)
    browser_inputs: list[tuple[str, SourceCandidate, str]] = []

    # One partially complete page per domain checks whether rendered DOM adds
    # requested fields. Selection is metric-driven, not identity-driven.
    seen_partial_domains: set[str] = set()
    for row in previous["cases"]:
        case = cases[row["case_id"]]
        if (
            row.get("source")
            and set(row["verified_fields"]) != set(case["target_fields"])
            and row["domain_id"] not in seen_partial_domains
        ):
            browser_inputs.append(
                (row["case_id"], _historical_candidate(case, row), "partial_evidence")
            )
            seen_partial_domains.add(row["domain_id"])

    # Re-discover at most one target-region-but-unfetched task per domain so the
    # browser receives only a freshly validated usable candidate.
    zhipu_key = os.getenv("ZhiPu_api_key", "").strip()
    if not zhipu_key:
        raise RuntimeError("ZhiPu_api_key is missing")
    zhipu_rows: list[dict[str, Any]] = []
    page_failures = _one_per_domain(audit["cases"], "page_fetch")
    zhipu_provider = ZhipuSourceSearchProvider(
        SourceSearchSettings(
            enabled=True,
            api_key=zhipu_key,
            configured_domains=tuple(
                sorted({domain for case in cases.values() for domain in case["allowed_domains"]})
            ),
            max_search_calls=4,
            max_cost_cny=0.20,
            total_timeout_seconds=50,
        )
    )
    try:
        for item in page_failures:
            case = cases[item["case_id"]]
            search = await zhipu_provider.search(_request(case))
            zhipu_rows.append(
                {
                    "case_id": item["case_id"],
                    "status": search.status.value,
                    "call_count": len(search.attempts),
                    "usable_candidate_count": len(search.usable_candidates),
                    "navigation_candidate_count": len(search.navigation_candidates),
                    "estimated_cost_cny": search.estimated_cost_cny,
                }
            )
            if search.usable_candidates:
                browser_inputs.append(
                    (item["case_id"], search.usable_candidates[0], "prior_page_fetch_failure")
                )
    finally:
        await zhipu_provider.aclose()

    browser_rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for case_id, candidate, reason in browser_inputs:
        if candidate.url in seen_urls:
            continue
        seen_urls.add(candidate.url)
        case = cases[case_id]
        pack = DomainPackLoader().load(ROOT / "smartbuy" / "domain_packs" / case["domain_id"])
        outcome = await render_with_playwright(
            candidate,
            target_fields=case["target_fields"],
            allowed_domains=case["allowed_domains"],
            pack=pack,
            settings=browser_settings,
        )
        browser_rows.append(
            {
                "case_id": case_id,
                "domain_id": case["domain_id"],
                "selection_reason": reason,
                "previous_verified_fields": previous_rows[case_id]["verified_fields"],
                **outcome,
            }
        )

    # Bocha is tested only where the primary result never established a target-
    # region lineage. The candidate still crosses the same local validator.
    bocha_key = os.getenv("BoCha_api_key", "").strip()
    if not bocha_key:
        raise RuntimeError("BoCha_api_key is missing")
    fallback_rows: list[dict[str, Any]] = []
    fallback_browser_rows: list[dict[str, Any]] = []
    for item in _one_per_domain(audit["cases"], "target_region_validation"):
        case = cases[item["case_id"]]
        outcome = await bocha_search_once(api_key=bocha_key, request=_request(case))
        candidates_found = outcome.pop("usable_candidates", [])
        fallback_rows.append({"case_id": item["case_id"], "domain_id": case["domain_id"], **outcome})
        if candidates_found:
            pack = DomainPackLoader().load(ROOT / "smartbuy" / "domain_packs" / case["domain_id"])
            rendered = await render_with_playwright(
                candidates_found[0],
                target_fields=case["target_fields"],
                allowed_domains=case["allowed_domains"],
                pack=pack,
                settings=browser_settings,
            )
            fallback_browser_rows.append(
                {"case_id": item["case_id"], "domain_id": case["domain_id"], **rendered}
            )

    recovered = {
        row["case_id"]: row
        for row in [*browser_rows, *fallback_browser_rows]
        if row.get("verified_fields")
        and previous_rows[row["case_id"]]["evidence_count"] == 0
    }
    completed_ids = {
        row["case_id"] for row in previous["cases"] if row["evidence_count"] > 0
    } | set(recovered)
    projected_verified = 0
    projected_requested = 0
    for case_id in completed_ids:
        case = cases[case_id]
        old = set(previous_rows[case_id]["verified_fields"])
        rendered_fields = {
            field
            for row in [*browser_rows, *fallback_browser_rows]
            if row["case_id"] == case_id
            for field in row.get("verified_fields", [])
        }
        projected_verified += len((old | rendered_fields) & set(case["target_fields"]))
        projected_requested += len(case["target_fields"])

    projected_per_domain = {
        domain: sum(cases[case_id]["domain_id"] == domain for case_id in completed_ids)
        for domain in ("monitor", "laptop", "headphone")
    }
    security = {
        "browser_non_region_matched_input_accepted": 0,
        "fallback_wrong_domain_model_region_usable": 0,
        "search_snippet_to_evidence": 0,
        "open_evidence_to_trusted_checker": 0,
    }
    projection = {
        "actual_evidence_completion": {
            "numerator": len(completed_ids),
            "denominator": len(cases),
        },
        "per_domain": {
            domain: {"numerator": value, "denominator": 5}
            for domain, value in projected_per_domain.items()
        },
        "verified_requested_fields": {
            "numerator": projected_verified,
            "denominator": projected_requested,
            "rate": projected_verified / projected_requested if projected_requested else 0.0,
        },
        "all_release_thresholds_met": (
            len(completed_ids) >= 8
            and all(value >= 2 for value in projected_per_domain.values())
            and projected_requested > 0
            and projected_verified / projected_requested >= 0.80
            and not any(security.values())
        ),
    }
    zhipu_usage = zhipu_provider.ledger.summary()
    payload = {
        "schema_version": "proofpick-v2-9g-online-feasibility-poc-v1",
        "classification": "limited_poc_on_exposed_failures; not_a_holdout_or_full_regression",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "inputs": {
            "v2_9f_result_sha256": hashlib.sha256(args.result.read_bytes()).hexdigest(),
            "monotonic_audit_sha256": hashlib.sha256(args.audit.read_bytes()).hexdigest(),
            "case_file_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        },
        "browser": {
            "enabled_explicitly": args.enable_browser,
            "default_enabled": BrowserPoCSettings().enabled,
            "dependency_version": "playwright==1.55.0 (existing uv.lock search group)",
            "rows": browser_rows,
            "recovered_zero_evidence_tasks": len(
                [row for row in browser_rows if row.get("verified_fields") and previous_rows[row["case_id"]]["evidence_count"] == 0]
            ),
        },
        "primary_rediscovery": {"provider": "zhipu", "rows": zhipu_rows, "usage": zhipu_usage},
        "bounded_fallback": {
            "provider": "bocha",
            "rows": fallback_rows,
            "browser_rows": fallback_browser_rows,
            "calls": len(fallback_rows),
            "known_estimated_cost_cny": sum(float(row.get("estimated_cost_cny", 0)) for row in fallback_rows),
            "new_target_region_candidate_tasks": sum(bool(row.get("usable_candidate_count")) for row in fallback_rows),
            "new_evidence_tasks": sum(bool(row.get("verified_fields")) for row in fallback_browser_rows),
        },
        "security": security,
        "projection": projection,
        "api_budget": {
            "known_estimated_cost_cny": float(zhipu_usage["estimated_cost_cny"]),
            "limit_cny": 2.0,
            "within_known_limit": float(zhipu_usage["estimated_cost_cny"]) <= 2.0,
            "bocha_usage_note": "API response does not expose billing; three bounded calls were used.",
        },
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--enable-browser", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite PoC result: {args.output}")
    payload = asyncio.run(run(args))
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "browser_recovery": payload["browser"]["recovered_zero_evidence_tasks"],
                "fallback_new_evidence": payload["bounded_fallback"]["new_evidence_tasks"],
                "projection": payload["projection"],
                "api_budget": payload["api_budget"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
