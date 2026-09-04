from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from smartbuy.domain_packs import DomainPackLoader
from smartbuy.eval.run_v2_9f_online_regression import _report_stop_reason
from smartbuy.open_research import (
    EvidenceNormalizer,
    ExtractedSnippet,
    ExtractionStatus,
    OpenResearchService,
    OpenResearchSettings,
    StaticHTMLExtractor,
    TemporaryEvidenceStore,
    URLSafetyPolicy,
    WebExtractionResult,
)
from smartbuy.open_research.html_parser import parse_html
from smartbuy.open_research.pdf_parser import parse_pdf
from smartbuy.source_search import SourceCandidate, SourceCandidateStatus


async def _public_resolver(_hostname: str) -> list[str]:
    return ["93.184.216.34"]


def test_online_runner_uses_existing_open_report_contract_for_stop_reason() -> None:
    completed = SimpleNamespace(
        report=SimpleNamespace(degraded_reasons=[], status="completed")
    )
    degraded = SimpleNamespace(
        report=SimpleNamespace(degraded_reasons=["requested_field_missing"], status="degraded")
    )
    assert _report_stop_reason(completed, "success") == "completed"
    assert _report_stop_reason(degraded, "success") == "requested_field_missing"
    assert _report_stop_reason(None, "no_official_source") == "no_official_source"


def _minimal_text_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, payload in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(payload)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(output)


def _candidate(url: str) -> SourceCandidate:
    return SourceCandidate(
        title="Acme Audio X900 official specifications",
        url=url,
        hostname="audio.example",
        site_name="Acme Audio",
        queried_at="2026-09-04T00:00:00Z",
        local_request_id="v29f-local",
        provider="fixture",
        engine="fixture",
        target_model="X900",
        target_region="US",
        observed_region="US",
        status=SourceCandidateStatus.REGION_MATCHED,
        model_match_source="url",
        region_match_source="url",
    )


def test_parser_discovers_only_model_bound_specification_and_attachment_links() -> None:
    parsed = parse_html(
        """
        <html lang="en-US"><head><title>Acme X900</title></head><body>
          <a href="/en-us/support/x900-tech-specs">X900 technical specifications</a>
          <a href="/en-us/manuals/x900-user-guide.pdf">X900 user guide PDF</a>
          <a href="/en-us/support/other-model">Other product support</a>
        </body></html>
        """,
        base_url="https://audio.example/en-us/products/x900",
        target_terms={"battery", "weight"},
        target_model="X900",
        max_snippets=20,
    )
    assert [item.kind for item in parsed.related_links] == [
        "support",
        "attachment",
    ]
    assert all("x900" in item.url for item in parsed.related_links)


def test_bounded_pdf_parser_extracts_exact_page_text_without_writing_files() -> None:
    title, snippets, pages, identity = parse_pdf(
        _minimal_text_pdf("Acme X900 battery life 30 hours weight 240 grams"),
        target_terms={"battery", "weight"},
        target_model="X900",
        max_pages=5,
        max_snippets=10,
    )
    assert title is None
    assert pages == 1
    assert identity is True
    assert snippets and snippets[0].kind == "pdf_text"
    assert "30 hours" in snippets[0].text


def test_embedded_state_extracts_requested_fields_without_executing_script() -> None:
    parsed = parse_html(
        """
        <html lang="en-US"><head><title>Acme X900</title></head><body>
        <script>window.__STATE__={model:"X900",battery:[{facet:"Battery life",
        value:"up to 90 hrs"}],physical:{facet:"Weight",value:"10 oz (283 g)"}};</script>
        </body></html>
        """,
        base_url="https://audio.example/en-us/x900",
        target_terms={"battery life", "weight"},
        target_model="X900",
        max_snippets=20,
    )
    state = [item for item in parsed.snippets if item.kind == "embedded_state"]
    assert state
    assert any("90 hrs" in item.text for item in state)
    assert any("283 g" in item.text for item in state)


@pytest.mark.asyncio
async def test_open_research_follows_bounded_model_specific_spec_link(tmp_path: Path) -> None:
    base = "https://audio.example/en-us/products/x900"
    specs = "https://audio.example/en-us/support/x900-tech-specs"

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == base:
            html = (
                '<html lang="en-US"><head><title>Acme X900</title></head><body>'
                '<h1>Acme X900</h1><a href="/en-us/support/x900-tech-specs">'
                "X900 technical specifications</a></body></html>"
            )
        elif str(request.url) == specs:
            html = (
                '<html lang="en-US"><head><title>Acme X900 specifications</title></head>'
                "<body><h1>Acme X900</h1><table><tr><th>Weight</th><td>240 grams</td>"
                "</tr></table></body></html>"
            )
        else:
            return httpx.Response(404, request=request)
        return httpx.Response(
            200,
            text=html,
            headers={"content-type": "text/html"},
            request=request,
        )

    settings = OpenResearchSettings(enabled=True, evidence_root=tmp_path)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    extractor = StaticHTMLExtractor(
        settings,
        safety_policy=URLSafetyPolicy(_public_resolver),
        client=client,
    )
    service = OpenResearchService(
        settings,
        DomainPackLoader().load(Path("smartbuy/domain_packs/headphone")),
        extractor,
        TemporaryEvidenceStore(tmp_path),
    )
    outcome = await service.research(
        _candidate(base),
        target_fields=["weight_g"],
        allowed_domains=["audio.example"],
        provisional_product_id="acme-x900-us-open",
        configuration="X900-US",
        user_id="fixture-user",
        session_id="fixture-session",
        thread_id="fixture-thread",
        request_id="fixture-request",
    )
    await client.aclose()
    assert outcome.report.verified_fields == ["weight_g"]
    assert outcome.evidence[0].normalized_value == 240
    assert outcome.evidence[0].final_url == specs
    assert len(outcome.additional_extractions) == 1
    assert "model_bound_related_links_discovered" in outcome.report.tool_trace


@pytest.mark.parametrize(
    ("pack_name", "field", "text", "expected"),
    [
        ("monitor", "display_size_inch", "Acme View M900 display size: 31.5-inch", 31.5),
        ("monitor", "usb_c_power_delivery_w", "Acme View M900 USB-C Power Delivery: 96 W", 96),
        ("laptop", "battery_wh", "Acme Book L900 battery capacity: 75 Wh", 75),
        ("headphone", "water_resistance", "Acme Audio X900 is rated IP57", "IP57"),
    ],
)
def test_domain_driven_normalization_handles_unseen_product_identifiers(
    pack_name: str, field: str, text: str, expected: object
) -> None:
    pack = DomainPackLoader().load(Path("smartbuy/domain_packs") / pack_name)
    extraction = WebExtractionResult(
        requested_url="https://example.invalid/en-us/acme",
        final_url="https://example.invalid/en-us/acme",
        title=text.split(" ", 3)[0] + " official specifications",
        detected_region="US",
        fetched_at="2026-09-04T00:00:00Z",
        content_hash="d" * 64,
        status=ExtractionStatus.SUCCESS,
        snippets=[ExtractedSnippet(kind="specification", text=text, locator="fixture[0]")],
    )
    model = {"monitor": "M900", "laptop": "L900", "headphone": "X900"}[pack_name]
    records, unsupported = EvidenceNormalizer(pack).normalize(
        extraction,
        user_scope="u",
        session_scope="s",
        thread_scope="t",
        request_scope="r",
        provisional_product_id=f"acme-{model.casefold()}-us-open",
        target_model=model,
        product_region="US",
        target_fields=[field],
        configuration=f"{model}-US",
    )
    assert unsupported == []
    assert records and records[0].normalized_value == expected
    assert records[0].usable_for_trusted_checker is False


def test_battery_runtime_does_not_conflict_with_charge_duration() -> None:
    pack = DomainPackLoader().load(Path("smartbuy/domain_packs/headphone"))
    extraction = WebExtractionResult(
        requested_url="https://audio.example/en-us/x900",
        final_url="https://audio.example/en-us/x900",
        title="Acme X900 official specifications",
        detected_region="US",
        fetched_at="2026-09-04T00:00:00Z",
        content_hash="e" * 64,
        status=ExtractionStatus.SUCCESS,
        snippets=[
            ExtractedSnippet(
                kind="specification", text="Battery Life | 30 hours", locator="table[0]"
            ),
            ExtractedSnippet(
                kind="specification", text="Battery Charge Time | 3 hours", locator="table[1]"
            ),
        ],
    )
    records, _ = EvidenceNormalizer(pack).normalize(
        extraction,
        user_scope="u",
        session_scope="s",
        thread_scope="t",
        request_scope="r",
        provisional_product_id="acme-x900-us-open",
        target_model="X900",
        product_region="US",
        target_fields=["battery_hours"],
        configuration="X900-US",
    )
    assert [item.normalized_value for item in records] == [30]
