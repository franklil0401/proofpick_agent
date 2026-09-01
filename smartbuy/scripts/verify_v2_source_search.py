"""Run the bounded V2-3 official-source coverage check without storing credentials/content."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from smartbuy.providers import ZhipuSourceSearchProvider
from smartbuy.source_search import (
    SourceSearchRequest,
    SourceSearchSettings,
    SourceSearchTriggerReason,
)


CASES = (
    ("v2s-001", "Dell U2723QE 中国大陆 USB-C 90W 官方规格", "U2723QE", "CN", "www.dell.com", ["usb_c_power_delivery_w"]),
    ("v2s-002", "Dell S2722QC 中国大陆 USB-C 65W 官方规格", "S2722QC", "CN", "www.dell.com", ["usb_c_power_delivery_w"]),
    ("v2s-003", "ASUS PA279CRV 中国大陆 USB-C 96W 官方规格", "PA279CRV", "CN", "www.asus.com.cn", ["usb_c_power_delivery_w"]),
    ("v2s-004", "ASUS PG27AQDM 中国大陆 1440p 240Hz OLED 官方规格", "PG27AQDM", "CN", "rog.asus.com", ["resolution", "refresh_rate_hz", "is_oled"]),
    ("v2s-005", "LG 27UP850K-W 中国大陆 USB-C 90W 官方规格", "27UP850K-W", "CN", "www.lg.com", ["usb_c_power_delivery_w"]),
    ("v2s-006", "LG 27GS95QE-B 中国大陆 1440p 240Hz OLED 官方规格", "27GS95QE-B", "CN", "www.lg.com", ["resolution", "refresh_rate_hz", "is_oled"]),
    ("v2s-007", "BenQ PD2705U United States 4K USB-C 65W official", "PD2705U", "US", "www.benq.com", ["resolution", "usb_c_power_delivery_w"]),
    ("v2s-008", "BenQ PD2725U Canada 4K Thunderbolt 65W official", "PD2725U", "CA", "www.benq.com", ["resolution", "usb_c_power_delivery_w"]),
)


async def run(output: Path | None = None) -> int:
    api_key = os.getenv("ZhiPu_api_key", "").strip()
    if not api_key:
        print(json.dumps({"ZhiPu_api_key": "missing"}, ensure_ascii=False))
        return 2
    settings = SourceSearchSettings(enabled=True, api_key=api_key)
    provider = ZhipuSourceSearchProvider(settings)
    records: list[dict[str, Any]] = []
    try:
        for case_id, query, model, region, domain, fields in CASES:
            result = await provider.search(
                SourceSearchRequest(
                    query=query,
                    product_category="monitor",
                    target_model=model,
                    target_fields=fields,
                    region=region,
                    allowed_domains=[domain],
                    trigger_reason=SourceSearchTriggerReason.EXPLICIT_USER_REQUEST,
                )
            )
            records.append(
                {
                    "case_id": case_id,
                    "target_model": model,
                    "target_region": region,
                    "status": result.status,
                    "search_executed": result.search_executed,
                    "usable_urls": [item.url for item in result.usable_candidates],
                    "navigation": [
                        {
                            "url": item.url,
                            "status": item.status,
                            "observed_region": item.observed_region,
                        }
                        for item in result.navigation_candidates
                    ],
                    "attempts": [
                        {
                            "engine": item.engine,
                            "requested_count": item.requested_count,
                            "raw_result_count": item.raw_result_count,
                            "scanned_result_count": item.scanned_result_count,
                            "usable_result_count": item.usable_result_count,
                            "navigation_result_count": item.navigation_result_count,
                            "latency_ms": round(item.latency_ms, 3),
                            "cache_status": item.cache_status,
                            "error": item.error,
                        }
                        for item in result.attempts
                    ],
                    "latency_ms": round(result.latency_ms, 3),
                    "estimated_cost_cny": result.estimated_cost_cny,
                }
            )
    finally:
        await provider.aclose()
    summary = {
        "provider": provider.name,
        "provider_version": provider.version,
        "case_count": len(records),
        "region_matched": sum(item["status"] == "success" for item in records),
        "no_region_matched_source": sum(
            item["status"] == "no_region_matched_source" for item in records
        ),
        "search_executed": sum(bool(item["search_executed"]) for item in records),
        "estimated_cost_cny": provider.ledger.summary()["estimated_cost_cny"],
        "cases": records,
    }
    serialized = json.dumps(summary, ensure_ascii=False, indent=2, default=str)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="optional sanitized JSON output path")
    args = parser.parse_args()
    return asyncio.run(run(args.output))


if __name__ == "__main__":
    raise SystemExit(main())
