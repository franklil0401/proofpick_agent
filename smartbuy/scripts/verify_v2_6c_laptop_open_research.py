"""Run the bounded V2-6C Laptop Open Research acceptance outside Git."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

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


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LAPTOP_PACK = PROJECT_ROOT / "smartbuy" / "domain_packs" / "laptop"
TARGET_FIELDS = [
    "display_size_inch",
    "resolution",
    "refresh_rate_hz",
    "panel_type",
    "memory_gb",
    "storage_gb",
    "battery_wh",
    "weight_kg",
    "usb_c",
    "thunderbolt",
]


def _outside_project(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return resolved
    raise ValueError("live Open Research output and evidence must stay outside Git")


async def run(runtime_root: Path, output: Path) -> int:
    runtime_root = _outside_project(runtime_root)
    output = _outside_project(output)
    key = os.getenv("ZhiPu_api_key", "").strip()
    if not key:
        print(json.dumps({"ZhiPu_api_key": "missing"}, ensure_ascii=False))
        return 2
    search_settings = SourceSearchSettings(
        enabled=True,
        api_key=key,
        max_search_calls=2,
        max_cost_cny=0.20,
    )
    provider = ZhipuSourceSearchProvider(search_settings)
    research_settings = OpenResearchSettings(
        enabled=True,
        evidence_root=runtime_root / "temporary-evidence",
    )
    service = OpenResearchService(
        research_settings,
        DomainPackLoader().load(LAPTOP_PACK),
        StaticHTMLExtractor(research_settings),
        TemporaryEvidenceStore(research_settings.evidence_root),
    )
    try:
        search = await provider.search(
            SourceSearchRequest(
                query="ASUS Zenbook S 14 UX5406 US official specs memory battery",
                product_category="laptop",
                target_model="UX5406",
                target_fields=TARGET_FIELDS,
                region="US",
                allowed_domains=["asus.com"],
                trigger_reason=SourceSearchTriggerReason.EXPLICIT_USER_REQUEST,
                max_results=5,
            )
        )
        candidate = next(iter(search.usable_candidates), None)
        if candidate is None:
            payload = {
                "schema_version": "proofpick-v2-6c-r4-laptop-open-research-v1",
                "search_status": search.status,
                "search_executed": search.search_executed,
                "search_attempts": [item.model_dump(mode="json") for item in search.attempts],
                "estimated_search_cost_cny": provider.ledger.summary()["estimated_cost_cny"],
                "report_status": "degraded",
                "reason": "no_region_matched_source",
            }
        else:
            outcome = await service.research(
                candidate,
                target_fields=TARGET_FIELDS,
                allowed_domains=["asus.com"],
                provisional_product_id="asus-zenbook-s14-ux5406-us-open",
                configuration="UX5406",
                user_id="v2-6c-r4-verifier",
                session_id="v2-6c-r4-verifier",
                thread_id="laptop-open-research",
                request_id="v2-6c-r4-laptop-open-research",
            )
            report = outcome.report
            evidence = [
                {
                    key: getattr(item, key)
                    for key in (
                        "evidence_id",
                        "field_name",
                        "normalized_value",
                        "unit",
                        "source_url",
                        "final_url",
                        "source_title",
                        "source_region",
                        "product_region",
                        "configuration",
                        "observed_at",
                        "content_hash",
                        "evidence_scope",
                        "usable_for_trusted_checker",
                    )
                }
                for item in outcome.evidence
            ]
            payload = {
                "schema_version": "proofpick-v2-6c-r4-laptop-open-research-v1",
                "target_model": candidate.target_model,
                "target_region": candidate.target_region,
                "source_candidate": {
                    "url": candidate.url,
                    "hostname": candidate.hostname,
                    "status": candidate.status,
                    "queried_at": candidate.queried_at,
                },
                "search_status": search.status,
                "search_executed": search.search_executed,
                "search_attempts": [item.model_dump(mode="json") for item in search.attempts],
                "estimated_search_cost_cny": provider.ledger.summary()["estimated_cost_cny"],
                "extraction": {
                    "status": outcome.extraction.status,
                    "final_url": outcome.extraction.final_url,
                    "detected_region": outcome.extraction.detected_region,
                    "fetched_at": outcome.extraction.fetched_at,
                    "content_hash": outcome.extraction.content_hash,
                },
                "report_status": report.status,
                "verified_fields": report.verified_fields,
                "unknown_fields": report.unknown_fields,
                "conflict_fields": report.conflict_fields,
                "temporary_evidence_count": report.temporary_evidence_count,
                "temporary_store_status": outcome.temporary_store_status,
                "trusted_eligible": report.trusted_eligible,
                "evidence": evidence,
                "lineage_complete": all(
                    item["source_url"]
                    and item["source_region"]
                    and item["observed_at"]
                    and item["content_hash"]
                    for item in evidence
                ),
                "trusted_boundary_intact": all(
                    item["evidence_scope"] == "open"
                    and item["usable_for_trusted_checker"] is False
                    for item in evidence
                ),
                "llm_calls": 0,
            }
    finally:
        await service.aclose()
        await provider.aclose()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0 if payload.get("report_status") == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path("C:/ai/proofpick-v2/laptop-open-research-r4"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("C:/ai/proofpick-v2/laptop-open-research-r4/result.json"),
    )
    args = parser.parse_args()
    return asyncio.run(run(args.runtime_root, args.output))


if __name__ == "__main__":
    raise SystemExit(main())
