from __future__ import annotations

from pathlib import Path

import pytest

from smartbuy.domain_packs import DomainPackLoader
from smartbuy.eval.audit_v2_9g_online_funnel import audit
from smartbuy.eval.v2_9g_feasibility import (
    BrowserPoCSettings,
    assess_rendered_html,
    render_with_playwright,
)
from smartbuy.source_search import SourceCandidate, SourceCandidateStatus


ROOT = Path(__file__).resolve().parents[3]


def _candidate(status: SourceCandidateStatus = SourceCandidateStatus.REGION_MATCHED) -> SourceCandidate:
    return SourceCandidate(
        title="Example Display X100",
        url="https://official.example/us/products/example-x100",
        hostname="official.example",
        queried_at="2026-09-05T00:00:00Z",
        local_request_id="fixture-request",
        provider="fixture",
        engine="fixture",
        target_model="X100",
        target_region="US",
        observed_region="US" if status == SourceCandidateStatus.REGION_MATCHED else "CA",
        status=status,
        model_match_source="url",
        region_match_source="url",
    )


def test_rendered_fixture_normalizes_requested_fields() -> None:
    html = (ROOT / "smartbuy/tests/fixtures/v2_9g/rendered_monitor.html").read_text(
        encoding="utf-8"
    )
    pack = DomainPackLoader().load(ROOT / "smartbuy/domain_packs/monitor")
    extraction, fields = assess_rendered_html(
        html,
        candidate=_candidate(),
        final_url="https://official.example/us/products/example-x100",
        target_fields=[
            "resolution",
            "display_size_inch",
            "usb_c_power_delivery_w",
        ],
        pack=pack,
        settings=BrowserPoCSettings(),
    )
    assert extraction.detected_region == "US"
    assert fields == ["display_size_inch", "resolution", "usb_c_power_delivery_w"]


@pytest.mark.asyncio
async def test_browser_poc_is_default_off_and_rejects_unvalidated_region() -> None:
    pack = DomainPackLoader().load(ROOT / "smartbuy/domain_packs/monitor")
    disabled = await render_with_playwright(
        _candidate(),
        target_fields=["resolution"],
        allowed_domains=["official.example"],
        pack=pack,
        settings=BrowserPoCSettings(),
    )
    assert disabled == {
        "status": "disabled",
        "network_executed": False,
        "latency_ms": 0.0,
    }
    rejected = await render_with_playwright(
        _candidate(SourceCandidateStatus.REGION_MISMATCH),
        target_fields=["resolution"],
        allowed_domains=["official.example"],
        pack=pack,
        settings=BrowserPoCSettings(enabled=True),
    )
    assert rejected["status"] == "rejected"
    assert rejected["reason"] == "candidate_not_region_matched"
    assert rejected["network_executed"] is False


def test_monotonic_funnel_keeps_candidate_branches_separate() -> None:
    result = {
        "run_id": "fixture-run",
        "cases": [
            {
                "case_id": "fixture-1",
                "domain_id": "monitor",
                "search_executed": True,
                "search_attempts": [
                    {"domain_matched_count": 2, "model_matched_count": 2}
                ],
                "extraction_attempts": [
                    {
                        "candidate_status": "region_matched",
                        "evidence_count": 0,
                        "extractions": [
                            {
                                "status": "http_error",
                                "http_status": 403,
                                "detected_region": "unknown",
                                "snippet_count": 0,
                            }
                        ],
                    },
                    {
                        "candidate_status": "region_mismatch",
                        "evidence_count": 0,
                        "extractions": [
                            {
                                "status": "success",
                                "http_status": 200,
                                "detected_region": "CA",
                                "snippet_count": 3,
                            }
                        ],
                    },
                ],
            }
        ],
    }
    payload = audit(result, {"fixture-1": {"case_id": "fixture-1", "region": "US"}})
    counts = {
        item["stage"]: item["passed_tasks"] for item in payload["task_level_funnel"]
    }
    assert counts["target_region_validation"] == 1
    assert counts["page_fetch"] == 0
    assert payload["page_fetch_included_region_failed_tasks"] == ["fixture-1"]
    assert payload["cases"][0]["first_failure_stage"] == "page_fetch"
