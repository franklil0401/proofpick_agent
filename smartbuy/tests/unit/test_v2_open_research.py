from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from smartbuy.domain_packs.loader import DEFAULT_MONITOR_PACK, DomainPackLoader
from smartbuy.open_research import (
    EvidenceNormalizer,
    ExtractionStatus,
    OpenEvidenceChecker,
    OpenEvidenceRecord,
    OpenEvidenceStatus,
    OpenResearchReport,
    OpenResearchService,
    OpenResearchSettings,
    ScopedEvidenceValue,
    StaticHTMLExtractor,
    TemporaryEvidenceStore,
    URLSafetyError,
    URLSafetyPolicy,
    scope_token,
)
from smartbuy.source_search import SourceCandidate, SourceCandidateStatus


PUBLIC_IP = ["93.184.216.34"]


async def public_resolver(_hostname: str) -> list[str]:
    return PUBLIC_IP


def candidate(
    url: str = "https://www.benq.com/en-us/monitor/creative-pro/pd3226g.html",
    *,
    status: SourceCandidateStatus = SourceCandidateStatus.REGION_MATCHED,
    observed_region: str = "US",
    target_region: str = "US",
) -> SourceCandidate:
    return SourceCandidate(
        title="BenQ PD3226G official",
        url=url,
        hostname="www.benq.com",
        site_name="BenQ",
        queried_at="2026-09-02T00:00:00Z",
        local_request_id="request-safe",
        provider="fake",
        engine="fake",
        target_model="PD3226G",
        target_region=target_region,
        observed_region=observed_region,
        status=status,
    )


@pytest.mark.asyncio
async def test_url_safety_rejects_ssrf_userinfo_ports_and_suffix_spoofing() -> None:
    policy = URLSafetyPolicy(public_resolver)
    safe = await policy.validate(
        "https://www.benq.com/en-us/pd3226g.html#fragment", ["benq.com"]
    )
    assert safe.url == "https://www.benq.com/en-us/pd3226g.html"
    tracking = await policy.validate(
        "https://www.benq.com/en-us/pd3226g.html?sku=1&utm_source=test&cjevent=abc",
        ["benq.com"],
    )
    assert tracking.url == "https://www.benq.com/en-us/pd3226g.html?sku=1"
    cases = {
        "file:///etc/passwd": "scheme_rejected",
        "https://user:pass@www.benq.com/en-us/pd3226g.html": "userinfo_rejected",
        "https://www.benq.com:8443/en-us/pd3226g.html": "port_rejected",
        "https://127.0.0.1/pd3226g": "ip_literal_rejected",
        "https://benq.com.evil.example/pd3226g": "domain_rejected",
    }
    for url, code in cases.items():
        with pytest.raises(URLSafetyError, match=code):
            await policy.validate(url, ["benq.com"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "224.0.0.1",
        "0.0.0.0",
        "::1",
        "::ffff:10.0.0.1",
    ],
)
async def test_url_safety_rejects_non_public_dns(address: str) -> None:
    async def resolver(_hostname: str) -> list[str]:
        return [address]

    with pytest.raises(URLSafetyError, match="dns_non_public_address"):
        await URLSafetyPolicy(resolver).validate(
            "https://www.benq.com/en-us/pd3226g.html", ["benq.com"]
        )


def html_page() -> str:
    return """<!doctype html><html lang="en-US"><head>
    <title>BenQ PD3226G | 32 inch 4K UHD 144Hz Monitor</title>
    <link rel="canonical" href="https://www.benq.com/en-us/monitor/creative-pro/pd3226g.html">
    <link rel="alternate" hreflang="en-CA" href="https://www.benq.com/en-ca/monitor/creative-pro/pd3226g.html">
    <script type="application/ld+json">{"@type":"Product","model":"PD3226G","name":"BenQ PD3226G"}</script>
    </head><body>
    <h1>PD3226G 32 inch 4K UHD 144Hz</h1>
    <p>All-in-One Thunderbolt 4 carries video and delivers up to 90W of power. USB-C compatible.</p>
    <table><tr><th>Resolution</th><td>3840x2160</td></tr><tr><th>Refresh Rate</th><td>144Hz</td></tr></table>
    </body></html>"""


@pytest.mark.asyncio
async def test_static_extractor_success_and_redirect_checks(tmp_path) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/en-us/start/pd3226g.html":
            return httpx.Response(
                302,
                headers={"location": "/en-us/monitor/creative-pro/pd3226g.html"},
                request=request,
            )
        return httpx.Response(
            200,
            text=html_page(),
            headers={"content-type": "text/html; charset=utf-8"},
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    extractor = StaticHTMLExtractor(
        OpenResearchSettings(enabled=True, evidence_root=tmp_path),
        safety_policy=URLSafetyPolicy(public_resolver),
        client=client,
    )
    result = await extractor.extract(
        candidate("https://www.benq.com/en-us/start/pd3226g.html"),
        target_fields=["resolution", "refresh_rate_hz", "usb_c_power_delivery_w"],
        field_terms={"resolution", "refresh rate", "thunderbolt", "power"},
        allowed_domains=["benq.com"],
    )
    await client.aclose()
    assert result.status == ExtractionStatus.SUCCESS
    assert result.http_status == 200
    assert result.detected_region == "US"
    assert len(result.redirect_chain) == 1
    assert result.content_hash and len(result.content_hash) == 64
    assert result.canonical_url and result.canonical_url.startswith("https://www.benq.com/")
    assert any(item.hreflang == "en-CA" for item in result.alternate_links)
    assert any("3840x2160" in item.text for item in result.snippets)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_navigation_candidate_requires_hreflang_refetch_before_evidence(tmp_path) -> None:
    navigation_html = """<html lang="zh-CN"><head>
    <title>BenQ PD3226G China</title>
    <link rel="alternate" hreflang="en-US"
      href="https://www.benq.com/en-us/monitor/creative-pro/pd3226g.html">
    </head><body><p>PD3226G 中国区导航页。</p></body></html>"""
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        body = html_page() if "/en-us/" in request.url.path else navigation_html
        return httpx.Response(
            200,
            text=body,
            headers={"content-type": "text/html; charset=utf-8"},
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = OpenResearchSettings(enabled=True, evidence_root=tmp_path / "evidence")
    pack = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
    extractor = StaticHTMLExtractor(
        settings,
        safety_policy=URLSafetyPolicy(public_resolver),
        client=client,
    )
    service = OpenResearchService(
        settings,
        pack,
        extractor,
        TemporaryEvidenceStore(settings.evidence_root),
    )
    outcome = await service.research(
        candidate(
            "https://www.benq.com/zh-cn/monitor/creative-pro/pd3226g.html",
            status=SourceCandidateStatus.REGION_MISMATCH,
            observed_region="CN",
            target_region="US",
        ),
        target_fields=["resolution", "usb_c_power_delivery_w"],
        allowed_domains=["benq.com"],
        provisional_product_id="benq-pd3226g-us-open",
        configuration="PD3226G",
        user_id="user-a",
        session_id="session-a",
        thread_id="thread-a",
        request_id="request-recovery",
        allow_region_discovery=True,
    )
    await client.aclose()
    assert outcome.canonical_recovery_attempted is True
    assert outcome.canonical_recovery_succeeded is True
    assert outcome.report.status == "completed"
    assert outcome.report.product_region == "US"
    assert all(item.source_region == "US" for item in outcome.evidence)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_extractor_rejects_bad_redirect_non_html_oversize_timeout_and_dynamic(tmp_path) -> None:
    settings = OpenResearchSettings(
        enabled=True,
        evidence_root=tmp_path,
        max_html_bytes=64 * 1024,
        max_redirects=1,
    )

    async def run(handler, url="https://www.benq.com/en-us/pd3226g.html"):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
        extractor = StaticHTMLExtractor(
            settings,
            safety_policy=URLSafetyPolicy(public_resolver),
            client=client,
        )
        result = await extractor.extract(
            candidate(url),
            target_fields=["resolution"],
            field_terms={"resolution"},
            allowed_domains=["benq.com"],
        )
        await client.aclose()
        return result

    bad_redirect = await run(
        lambda request: httpx.Response(
            302,
            headers={"location": "https://benq.com.evil.example/en-us/pd3226g.html"},
            request=request,
        )
    )
    assert bad_redirect.status == ExtractionStatus.UNSAFE_URL

    non_html = await run(
        lambda request: httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}, request=request
        )
    )
    assert non_html.status == ExtractionStatus.NON_HTML

    oversized = await run(
        lambda request: httpx.Response(
            200,
            content=b"x" * (64 * 1024 + 1),
            headers={"content-type": "text/html"},
            request=request,
        )
    )
    assert oversized.status == ExtractionStatus.CONTENT_TOO_LARGE

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated", request=request)

    timed_out = await run(timeout_handler)
    assert timed_out.status == ExtractionStatus.TIMEOUT

    dynamic_html = "<html lang='en-US'><body>" + "<script src='x.js'></script>" * 6 + "</body></html>"
    dynamic = await run(
        lambda request: httpx.Response(
            200,
            text=dynamic_html,
            headers={"content-type": "text/html"},
            request=request,
        )
    )
    assert dynamic.status == ExtractionStatus.DYNAMIC_RENDER_REQUIRED

    def loop_handler(request: httpx.Request) -> httpx.Response:
        target = "/en-us/two/pd3226g.html" if request.url.path.endswith("one/pd3226g.html") else "/en-us/three/pd3226g.html"
        return httpx.Response(302, headers={"location": target}, request=request)

    redirect_limit = await run(loop_handler, "https://www.benq.com/en-us/one/pd3226g.html")
    assert redirect_limit.status == ExtractionStatus.REDIRECT_LIMIT


@pytest.mark.asyncio
async def test_full_open_pipeline_stores_minimal_evidence_outside_repo(tmp_path) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=html_page(),
                headers={"content-type": "text/html; charset=utf-8"},
                request=request,
            )
        )
    )
    settings = OpenResearchSettings(enabled=True, evidence_root=tmp_path / "evidence")
    pack = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
    extractor = StaticHTMLExtractor(
        settings,
        safety_policy=URLSafetyPolicy(public_resolver),
        client=client,
    )
    store = TemporaryEvidenceStore(settings.evidence_root)
    service = OpenResearchService(settings, pack, extractor, store)
    outcome = await service.research(
        candidate(),
        target_fields=[
            "display_size_inch",
            "resolution",
            "refresh_rate_hz",
            "has_usb_c",
            "usb_c_video",
            "usb_c_power_delivery_w",
            "width_mm",
        ],
        allowed_domains=["benq.com"],
        provisional_product_id="benq-pd3226g-us-open",
        configuration="PD3226G",
        user_id="user-a",
        session_id="session-a",
        thread_id="thread-a",
        request_id="request-a",
    )
    await client.aclose()
    assert outcome.report.status == "completed"
    assert outcome.report.trusted_eligible is False
    assert set(outcome.report.verified_fields) >= {
        "display_size_inch",
        "resolution",
        "refresh_rate_hz",
        "has_usb_c",
        "usb_c_video",
        "usb_c_power_delivery_w",
    }
    assert "width_mm" in outcome.report.unknown_fields
    assert outcome.temporary_store_status == "stored"
    stored = store.read(
        scope_token("user-a", "anonymous"),
        scope_token("session-a", "stateless"),
        scope_token("thread-a", "stateless"),
        scope_token("request-a", "request"),
    )
    assert stored.status == "ok"
    assert len(stored.records) == outcome.report.temporary_evidence_count
    assert all(item.evidence_scope == "open" for item in stored.records)
    assert all(item.usable_for_trusted_checker is False for item in stored.records)
    assert not list(tmp_path.rglob("*.html"))


def open_record(
    *,
    evidence_id: str,
    value: object,
    region: str = "US",
    product_region: str = "US",
    observed_at: str = "2026-09-02T00:00:00Z",
) -> OpenEvidenceRecord:
    return OpenEvidenceRecord(
        evidence_id=evidence_id,
        user_scope="a" * 32,
        session_scope="b" * 32,
        thread_scope="c" * 32,
        request_scope="d" * 32,
        provisional_product_id="benq-pd3226g-us-open",
        field_name="usb_c_power_delivery_w",
        raw_value=value,
        normalized_value=value,
        unit="W",
        source_url="https://www.benq.com/en-us/source/pd3226g.html",
        final_url="https://www.benq.com/en-us/source/pd3226g.html",
        source_title="Official source",
        source_region=region,
        product_region=product_region,
        exact_snippet=f"Power Delivery {value}W",
        snippet_locator="spec[1]",
        fetched_at=observed_at,
        observed_at=observed_at,
        content_hash="e" * 64,
        expires_at="2026-09-03T00:00:00Z",
        confidence="high",
    )


def governed(value: object) -> ScopedEvidenceValue:
    return ScopedEvidenceValue(
        evidence_id="governed-evidence",
        field_name="usb_c_power_delivery_w",
        normalized_value=value,
        unit="W",
        source_url="https://www.benq.com/en-us/governed/pd3226g.html",
        source_region="US",
        product_region="US",
        observed_at="2026-08-01T00:00:00Z",
        exact_snippet=f"Power Delivery {value}W",
        evidence_scope="governed",
    )


@pytest.mark.parametrize(
    ("open_records", "governed_records"),
    [
        ([open_record(evidence_id="open-" + "1" * 24, value=90)], [governed(85)]),
        (
            [
                open_record(evidence_id="open-" + "2" * 24, value=90),
                open_record(
                    evidence_id="open-" + "a" * 24,
                    value=65,
                    region="CA",
                ),
            ],
            [],
        ),
        (
            [
                open_record(evidence_id="open-" + "3" * 24, value=85, observed_at="2026-08-01T00:00:00Z"),
                open_record(evidence_id="open-" + "4" * 24, value=90, observed_at="2026-09-02T00:00:00Z"),
            ],
            [],
        ),
        (
            [
                open_record(evidence_id="open-" + "5" * 24, value=85),
                open_record(evidence_id="open-" + "6" * 24, value=90),
            ],
            [],
        ),
    ],
    ids=[
        "governed-versus-open",
        "same-model-cross-region-different-values",
        "old-versus-new",
        "same-page-multiple-values",
    ],
)
def test_four_conflict_classes_preserve_both_sides(open_records, governed_records) -> None:
    result = OpenEvidenceChecker().assess(
        ["usb_c_power_delivery_w"], open_records, governed_records=governed_records
    )[0]
    assert result.status == OpenEvidenceStatus.CONFLICT
    assert len(result.evidence) == len(open_records) + len(governed_records)


def test_single_wrong_region_evidence_is_unknown() -> None:
    ca = open_record(evidence_id="open-" + "b" * 24, value=65, region="CA")
    result = OpenEvidenceChecker().assess([ca.field_name], [ca])[0]

    assert result.status == OpenEvidenceStatus.UNKNOWN
    assert result.target_region_status == OpenEvidenceStatus.UNKNOWN
    assert result.reason == "region_mismatch_only"
    assert result.cross_region_conflict is False
    assert result.target_region == "US"
    assert result.target_region_evidence_ids == []
    assert result.non_target_region_evidence_ids == [ca.evidence_id]
    assert [item.evidence_id for item in result.non_comparable_evidence] == [
        ca.evidence_id
    ]


def test_two_regions_with_different_values_preserve_conflict() -> None:
    us = open_record(evidence_id="open-" + "c" * 24, value=90)
    ca = open_record(evidence_id="open-" + "d" * 24, value=65, region="CA")
    result = OpenEvidenceChecker().assess([us.field_name], [us, ca])[0]

    assert result.status == OpenEvidenceStatus.CONFLICT
    assert result.target_region_status == OpenEvidenceStatus.MATCHED
    assert result.cross_region_conflict is True
    assert set(result.conflict_evidence_ids) == {us.evidence_id, ca.evidence_id}
    preserved = {item.evidence_id: item for item in result.evidence}
    assert (preserved[us.evidence_id].source_region, preserved[us.evidence_id].normalized_value) == (
        "US",
        90,
    )
    assert (preserved[ca.evidence_id].source_region, preserved[ca.evidence_id].normalized_value) == (
        "CA",
        65,
    )
    assert all(item.unit == "W" for item in preserved.values())
    assert all(item.source_url for item in preserved.values())


def test_two_regions_with_same_value_are_not_conflict() -> None:
    us = open_record(evidence_id="open-" + "e" * 24, value=90)
    ca = open_record(evidence_id="open-" + "f" * 24, value=90, region="CA")
    result = OpenEvidenceChecker().assess([us.field_name], [us, ca])[0]

    assert result.status == OpenEvidenceStatus.MATCHED
    assert result.target_region_status == OpenEvidenceStatus.MATCHED
    assert result.cross_region_conflict is False
    assert result.values == [90]
    assert result.target_region_evidence_ids == [us.evidence_id]
    assert result.non_target_region_evidence_ids == [ca.evidence_id]


def test_same_value_wrong_region_only_is_still_unknown() -> None:
    ca = open_record(evidence_id="open-" + "0" * 24, value=90, region="CA")
    result = OpenEvidenceChecker().assess([ca.field_name], [ca])[0]

    assert result.status == OpenEvidenceStatus.UNKNOWN
    assert result.reason == "region_mismatch_only"
    assert result.cross_region_conflict is False
    assert result.values == []


def test_target_region_evidence_not_overridden_by_other_region() -> None:
    us = open_record(evidence_id="open-" + "9" * 24, value=90)
    ca = open_record(evidence_id="open-" + "8" * 24, value=65, region="CA")
    result = OpenEvidenceChecker().assess([us.field_name], [ca, us])[0]

    assert result.target_region_status == OpenEvidenceStatus.MATCHED
    target = [
        item
        for item in result.evidence
        if item.evidence_id in result.target_region_evidence_ids
    ]
    assert [(item.source_region, item.normalized_value) for item in target] == [
        ("US", 90)
    ]
    assert [(item.source_region, item.normalized_value) for item in result.non_comparable_evidence] == [
        ("CA", 65)
    ]


def test_cross_region_conflict_cannot_grant_trusted_eligibility() -> None:
    us = open_record(evidence_id="open-" + "7" * 24, value=90)
    ca = open_record(evidence_id="open-" + "6" * 24, value=65, region="CA")
    assessment = OpenEvidenceChecker().assess([us.field_name], [us, ca])[0]
    report = OpenResearchReport(
        provisional_product_id="benq-pd3226g-us-open",
        target_model="PD3226G",
        product_region="US",
        status="completed",
        field_assessments=[assessment],
        conflict_fields=[us.field_name],
    )

    assert assessment.status == OpenEvidenceStatus.CONFLICT
    assert report.trusted_eligible is False
    with pytest.raises(ValueError, match="Trusted Constraint Checker"):
        us.to_trusted_checker_input()


def test_temporary_store_expiry_corruption_deletion_and_disabled(tmp_path) -> None:
    store = TemporaryEvidenceStore(tmp_path / "evidence")
    record = open_record(evidence_id="open-" + "7" * 24, value=90)
    store.write([record])
    identity = (record.user_scope, record.session_scope, record.thread_scope, record.request_scope)
    expired = store.read(*identity, now=datetime(2026, 9, 4, tzinfo=UTC))
    assert expired.status == "expired"
    assert store.cleanup_expired(now=datetime(2026, 9, 4, tzinfo=UTC)) == 1
    assert store.read(*identity).status == "missing"

    store.write([record])
    path = next((tmp_path / "evidence").rglob("*.json"))
    path.write_text("{broken", encoding="utf-8")
    assert store.read(*identity).status == "corrupt"
    assert store.delete(*identity) is True
    assert TemporaryEvidenceStore(tmp_path / "disabled", enabled=False).read(*identity).status == "disabled"
    promotion = TemporaryEvidenceStore.promotion_candidate([record])
    assert promotion == {
        "status": "review_required",
        "auto_publish": False,
        "evidence_scope": "open",
        "record_count": 1,
        "evidence_ids": [record.evidence_id],
    }


def test_search_summary_cannot_be_normalized_without_extraction() -> None:
    pack = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
    normalizer = EvidenceNormalizer(pack)
    from smartbuy.open_research.models import WebExtractionResult

    extraction = WebExtractionResult(
        requested_url="https://www.benq.com/en-us/pd3226g.html",
        fetched_at="2026-09-02T00:00:00Z",
        status=ExtractionStatus.EXTRACTION_INCOMPLETE,
        degraded=True,
        error="search_summary_only",
    )
    records, _ = normalizer.normalize(
        extraction,
        user_scope="a" * 32,
        session_scope="b" * 32,
        thread_scope="c" * 32,
        request_scope="d" * 32,
        provisional_product_id="benq-pd3226g-us-open",
        target_model="PD3226G",
        product_region="US",
        target_fields=["resolution"],
    )
    assert records == []


def test_open_evidence_cannot_enter_trusted_checker() -> None:
    record = open_record(evidence_id="open-" + "8" * 24, value=90)
    with pytest.raises(ValueError, match="Trusted Constraint Checker"):
        record.to_trusted_checker_input()
    serialized = json.dumps(record.model_dump(mode="json"))
    assert '"usable_for_trusted_checker": false' in serialized
