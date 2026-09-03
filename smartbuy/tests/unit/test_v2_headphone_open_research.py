from __future__ import annotations

from pathlib import Path

from smartbuy.domain_packs import DomainPackLoader
from smartbuy.open_research import (
    EvidenceNormalizer,
    ExtractedSnippet,
    ExtractionStatus,
    WebExtractionResult,
)
from smartbuy.source_search.validator import infer_region
from smartbuy.open_research.html_parser import parse_html


def test_region_inference_supports_ireland_locale_paths() -> None:
    assert infer_region("https://www.apple.com/ie/shop/audio") == "IE"
    assert infer_region("https://support.apple.com/en-ie/guide") == "IE"


def test_target_model_context_is_bounded_across_adjacent_spec_blocks() -> None:
    html = """<html><body><h2>Example X</h2><p>Over-ear headphones</p>
    <p>Up to 30 hours of battery life</p><p>Unrelated footer</p></body></html>"""
    parsed = parse_html(
        html,
        base_url="https://example.com/us/example-x",
        target_terms={"battery", "over-ear"},
        target_model="Example X",
        max_snippets=20,
    )
    battery = next(item for item in parsed.snippets if "30 hours" in item.text)
    assert battery.text.startswith("Example X |")


def test_headphone_pack_drives_open_research_normalization() -> None:
    pack = DomainPackLoader().load(Path("smartbuy/domain_packs/headphone"))
    extraction = WebExtractionResult(
        requested_url="https://electronics.example/en-us/headphones/example-x.html",
        final_url="https://electronics.example/en-us/headphones/example-x.html",
        title="Example X official specifications",
        detected_region="US",
        fetched_at="2026-09-03T00:00:00Z",
        content_hash="a" * 64,
        status=ExtractionStatus.SUCCESS,
        snippets=[
            ExtractedSnippet(
                kind="specification",
                locator="specs[0]",
                text=(
                    "Example X over-ear headphones with Bluetooth, multipoint, "
                    "active noise cancellation, spatial audio and microphone."
                ),
            ),
            ExtractedSnippet(
                kind="specification",
                locator="specs[1]",
                text=(
                    "Example X battery life up to 30 hours; weight 254 grams; "
                    "LDAC and AAC codecs."
                ),
            ),
        ],
    )
    target_fields = [
        "form_factor",
        "bluetooth",
        "multipoint",
        "active_noise_cancellation",
        "spatial_audio",
        "microphone",
        "battery_hours",
        "weight_g",
        "supported_codecs",
    ]
    records, unsupported = EvidenceNormalizer(pack).normalize(
        extraction,
        user_scope="u",
        session_scope="s",
        thread_scope="t",
        request_scope="r",
        provisional_product_id="example-x-us-open",
        target_model="Example X",
        product_region="US",
        target_fields=target_fields,
        configuration="Example X",
    )
    values = {record.field_name: record.normalized_value for record in records}
    assert unsupported == []
    assert set(values) == set(target_fields)
    assert values["form_factor"] == "over_ear"
    assert values["battery_hours"] == 30.0
    assert values["weight_g"] == 254.0
    assert values["supported_codecs"] == ["LDAC", "AAC"]
    assert all(record.evidence_scope == "open" for record in records)
    assert all(record.usable_for_trusted_checker is False for record in records)
