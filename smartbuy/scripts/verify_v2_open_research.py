"""Run bounded, sanitized V2-4 live acceptance checks outside the repository.

The command reads the configured Zhipu credential without printing it, discovers
official URLs through Source Search, and never stores full response HTML.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from smartbuy.domain_packs.loader import DEFAULT_MONITOR_PACK, DomainPackLoader
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
CASES = (
    {
        "case_id": "v2o-live-success",
        "query": "BenQ PD3226G United States 4K 144Hz Thunderbolt 90W official",
        "model": "PD3226G",
        "region": "US",
        "domain": "www.benq.com",
        "fields": [
            "display_size_inch",
            "resolution",
            "refresh_rate_hz",
            "has_usb_c",
            "usb_c_video",
            "usb_c_power_delivery_w",
        ],
        "provisional_id": "benq-pd3226g-us-open",
        "recovery": False,
    },
    {
        "case_id": "v2o-live-degraded",
        "query": "Dell P2725QE 中国大陆 USB-C 官方规格",
        "model": "P2725QE",
        "region": "CN",
        "domain": "www.dell.com",
        "fields": ["resolution", "usb_c_video", "usb_c_power_delivery_w"],
        "provisional_id": "dell-p2725qe-cn-open",
        "recovery": False,
    },
    {
        "case_id": "v2o-live-lg-hreflang",
        "query": "LG 27GS95QE-B 中国大陆 1440p 240Hz OLED 官方规格",
        "model": "27GS95QE-B",
        "region": "CN",
        "domain": "www.lg.com",
        "fields": ["resolution", "refresh_rate_hz", "is_oled"],
        "provisional_id": "lg-27gs95qe-b-cn-open",
        "recovery": True,
    },
    {
        "case_id": "v2o-live-benq-hreflang",
        "query": "BenQ PD2725U Canada 4K Thunderbolt 65W official",
        "model": "PD2725U",
        "region": "CA",
        "domain": "www.benq.com",
        "fields": ["resolution", "usb_c_video", "usb_c_power_delivery_w"],
        "provisional_id": "benq-pd2725u-ca-open",
        "recovery": True,
    },
)


def _outside_project(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return resolved
    raise ValueError("live V2-4 output and temporary evidence must stay outside Git")


async def run(runtime_root: Path, output: Path) -> int:
    runtime_root = _outside_project(runtime_root)
    output = _outside_project(output)
    key = os.getenv("ZhiPu_api_key", "").strip()
    if not key:
        print(json.dumps({"ZhiPu_api_key": "missing"}, ensure_ascii=False))
        return 2

    search_settings = SourceSearchSettings(enabled=True, api_key=key)
    provider = ZhipuSourceSearchProvider(search_settings)
    open_settings = OpenResearchSettings(
        enabled=True,
        evidence_root=runtime_root / "temporary-evidence",
    )
    extractor = StaticHTMLExtractor(open_settings)
    service = OpenResearchService(
        open_settings,
        DomainPackLoader().load(DEFAULT_MONITOR_PACK),
        extractor,
        TemporaryEvidenceStore(open_settings.evidence_root),
    )
    records: list[dict[str, Any]] = []
    try:
        for item in CASES:
            search = await provider.search(
                SourceSearchRequest(
                    query=item["query"],
                    product_category="monitor",
                    target_model=item["model"],
                    target_fields=item["fields"],
                    region=item["region"],
                    allowed_domains=[item["domain"]],
                    trigger_reason=SourceSearchTriggerReason.EXPLICIT_USER_REQUEST,
                )
            )
            candidate = next(
                iter(search.usable_candidates or search.navigation_candidates), None
            )
            if candidate is None:
                records.append(
                    {
                        "case_id": item["case_id"],
                        "model": item["model"],
                        "region": item["region"],
                        "search_status": search.status,
                        "search_attempt_count": len(search.attempts),
                        "extraction_status": "not_executed",
                        "report_status": "degraded",
                        "degraded_reason": "no_source_candidate",
                    }
                )
                continue
            outcome = await service.research(
                candidate,
                target_fields=item["fields"],
                allowed_domains=[item["domain"]],
                provisional_product_id=item["provisional_id"],
                configuration=item["model"],
                user_id="v2-live-verifier",
                session_id="v2-live-verifier",
                thread_id=item["case_id"],
                request_id=item["case_id"],
                allow_region_discovery=bool(item["recovery"]),
            )
            report = outcome.report
            records.append(
                {
                    "case_id": item["case_id"],
                    "model": item["model"],
                    "region": item["region"],
                    "search_status": search.status,
                    "search_attempt_count": len(search.attempts),
                    "source_candidate_status": candidate.status,
                    "source_hostname": candidate.hostname,
                    "extraction_status": outcome.extraction.status,
                    "http_status": outcome.extraction.http_status,
                    "detected_region": outcome.extraction.detected_region,
                    "content_type": outcome.extraction.content_type,
                    "content_length": outcome.extraction.content_length,
                    "content_hash": outcome.extraction.content_hash,
                    "report_status": report.status,
                    "verified_fields": report.verified_fields,
                    "unknown_fields": report.unknown_fields,
                    "conflict_fields": report.conflict_fields,
                    "temporary_evidence_count": report.temporary_evidence_count,
                    "temporary_store_status": outcome.temporary_store_status,
                    "trusted_eligible": report.trusted_eligible,
                    "canonical_recovery_attempted": outcome.canonical_recovery_attempted,
                    "canonical_recovery_succeeded": outcome.canonical_recovery_succeeded,
                }
            )
    finally:
        await service.aclose()
        await provider.aclose()

    payload = {
        "schema_version": "proofpick-v2-4-live-verification-v1",
        "provider": provider.name,
        "provider_version": provider.version,
        "case_count": len(records),
        "complete_open_research_count": sum(
            item.get("report_status") == "completed" for item in records
        ),
        "degraded_count": sum(item.get("report_status") == "degraded" for item in records),
        "estimated_search_cost_cny": provider.ledger.summary()["estimated_cost_cny"],
        "llm_call_count": 0,
        "records": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path("C:/ai/proofpick-v2/open-research-live"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("C:/ai/proofpick-v2/open-research-live/result.json"),
    )
    args = parser.parse_args()
    return asyncio.run(run(args.runtime_root, args.output))


if __name__ == "__main__":
    raise SystemExit(main())
