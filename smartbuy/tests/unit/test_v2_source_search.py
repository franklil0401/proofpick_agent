from __future__ import annotations

import json

import httpx
import pytest

from smartbuy.observability import UsageLedger
from smartbuy.providers import ZhipuSourceSearchProvider
from smartbuy.source_search import (
    DeterministicSourceValidator,
    SourceCandidateStatus,
    SourceIsolationError,
    SourceSearchRequest,
    SourceSearchSettings,
    SourceSearchStatus,
    SourceSearchTriggerReason,
    assert_source_candidates_isolated,
)
from smartbuy.source_search.validator import infer_region
from smartbuy.tools import SourceSearchTool


def source_settings(**updates) -> SourceSearchSettings:
    values = {
        "enabled": True,
        "api_key": "placeholder-credential",
        "max_rps": 15,
        "retry_delay_seconds": 0,
    }
    values.update(updates)
    return SourceSearchSettings(**values)


def test_source_search_feature_flag_defaults_off_without_reading_a_key(monkeypatch) -> None:
    monkeypatch.delenv("PROOFPICK_SOURCE_SEARCH_ENABLED", raising=False)
    monkeypatch.setenv("ZhiPu_api_key", "must-not-be-loaded-while-disabled")
    settings = SourceSearchSettings.from_environment()
    assert settings.enabled is False
    assert settings.api_key is None
    assert settings.availability() == {
        "PROOFPICK_SOURCE_SEARCH_ENABLED": "disabled",
        "ZhiPu_api_key": "missing",
    }


def source_request(**updates) -> SourceSearchRequest:
    values = {
        "query": "Dell U2723QE CN USB-C 90W official",
        "product_category": "monitor",
        "target_model": "U2723QE",
        "target_fields": ["usb_c_power_delivery_w"],
        "region": "CN",
        "allowed_domains": ["dell.com"],
        "trigger_reason": SourceSearchTriggerReason.EXPLICIT_USER_REQUEST,
    }
    values.update(updates)
    return SourceSearchRequest(**values)


def raw_item(url: str, *, title: str = "Dell U2723QE", media: str | None = "Dell") -> dict:
    item = {"link": url, "title": title, "publish_date": "2026-01-01"}
    if media is not None:
        item["media"] = media
    return item


def make_provider(handler, **setting_updates):
    ledger = UsageLedger()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def no_sleep(_: float) -> None:
        return None

    provider = ZhipuSourceSearchProvider(
        source_settings(**setting_updates),
        client=client,
        ledger=ledger,
        sleep=no_sleep,
    )
    return provider, ledger


def test_validator_enforces_url_domain_model_region_and_metadata_boundaries() -> None:
    validator = DeterministicSourceValidator(source_settings().configured_domains)
    outcome = validator.validate(
        [
            raw_item("https://www.dell.com/zh-cn/shop/u2723qe/apd/1"),
            raw_item("https://www.dell.com/en-us/shop/u2723qe/apd/2"),
            raw_item("https://www.dell.com/shop/u2723qe/apd/3"),
            raw_item("https://www.dell.com/zh-cn/shop/s2722qc/apd/4"),
            raw_item("https://www.dell.com/zh-cn/shop/u2723qea/apd/5"),
            raw_item("https://dell.com.evil.example/zh-cn/u2723qe"),
            raw_item("javascript:alert(1)"),
        ],
        source_request(),
        provider="zhipu",
        engine="search_pro",
        queried_at="2026-09-01T00:00:00+00:00",
        local_request_id="local-1",
        provider_request_id="provider-1",
    )

    assert [item.status for item in outcome.usable_candidates] == [
        SourceCandidateStatus.REGION_MATCHED
    ]
    assert {item.status for item in outcome.navigation_candidates} == {
        SourceCandidateStatus.REGION_MISMATCH,
        SourceCandidateStatus.REGION_UNKNOWN,
    }
    assert {item.status for item in outcome.rejected_candidates} == {
        SourceCandidateStatus.MODEL_MISMATCH,
        SourceCandidateStatus.DOMAIN_REJECTED,
        SourceCandidateStatus.INVALID_URL,
    }
    assert outcome.stats.scanned_result_count == 7
    assert all(not item.usable_for_evidence for item in outcome.usable_candidates)


def test_validator_rejects_unconfigured_requested_domain() -> None:
    validator = DeterministicSourceValidator(source_settings().configured_domains)
    with pytest.raises(ValueError, match="allowlist"):
        validator.validate_request(source_request(allowed_domains=["example.com"]))


@pytest.mark.asyncio
async def test_provider_rejects_unconfigured_domain_before_network() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"search_result": []})

    provider, _ = make_provider(handler)
    result = await provider.search(source_request(allowed_domains=["example.com"]))
    await provider.aclose()
    assert calls == 0
    assert result.status == SourceSearchStatus.PROVIDER_ERROR
    assert result.search_executed is False
    assert result.error == "InvalidSourceSearchRequest"


def test_optional_site_name_can_be_missing_without_losing_required_metadata() -> None:
    validator = DeterministicSourceValidator(source_settings().configured_domains)
    outcome = validator.validate(
        [raw_item("https://www.dell.com/zh-cn/u2723qe/a", media=None)],
        source_request(),
        provider="zhipu",
        engine="search_pro",
        queried_at="2026-09-01T00:00:00+00:00",
        local_request_id="local-media",
        provider_request_id=None,
    )
    assert len(outcome.usable_candidates) == 1
    assert outcome.usable_candidates[0].site_name is None
    assert outcome.stats.site_name_missing_count == 1
    assert outcome.stats.required_metadata_count == 1


def test_validator_caps_raw_scan_and_usable_results() -> None:
    validator = DeterministicSourceValidator(source_settings().configured_domains)
    items = [
        raw_item(f"https://www.dell.com/zh-cn/shop/u2723qe/apd/{index}")
        for index in range(70)
    ]
    outcome = validator.validate(
        items,
        source_request(),
        provider="zhipu",
        engine="search_pro",
        queried_at="2026-09-01T00:00:00+00:00",
        local_request_id="local-2",
        provider_request_id=None,
    )
    assert outcome.stats.raw_result_count == 70
    assert outcome.stats.scanned_result_count == 50
    assert len(outcome.usable_candidates) == 10


@pytest.mark.asyncio
async def test_search_pro_falls_back_to_sogou_and_preserves_safe_lists() -> None:
    engines: list[str] = []
    queries: list[str] = []
    provider_domain_filters: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        engines.append(body["search_engine"])
        queries.append(body["search_query"])
        provider_domain_filters.append(body.get("search_domain_filter"))
        if body["search_engine"] == "search_pro":
            results = [raw_item("https://www.dell.com/en-us/shop/u2723qe/apd/1")]
        else:
            results = [raw_item("https://www.dell.com/zh-cn/shop/u2723qe/apd/2")]
        return httpx.Response(200, json={"request_id": "safe-provider-id", "search_result": results})

    provider, ledger = make_provider(handler)
    result = await provider.search(source_request())
    await provider.aclose()

    assert result.status == SourceSearchStatus.SUCCESS
    assert engines == ["search_pro", "search_pro", "search_pro", "search_pro_sogou"]
    assert len(set(queries)) == 4
    assert "U2723QE" in queries[0] and "site:dell.com" in queries[0]
    assert "technical specifications" in queries[1]
    assert queries[2].startswith("U2723QE China zh-cn official specifications")
    assert queries[3].startswith('"U2723QE" CN official')
    assert provider_domain_filters == ["dell.com", "dell.com", None, None]
    assert result.usable_result_count == 1
    assert result.usable_candidates[0].observed_region == "CN"
    assert result.navigation_candidates[0].observed_region == "US"
    assert result.estimated_cost_cny == pytest.approx(0.14)
    assert ledger.summary()["call_count"] == 4


@pytest.mark.asyncio
async def test_primary_provider_failure_can_recover_with_sogou() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        engine = json.loads(request.content)["search_engine"]
        calls.append(engine)
        if engine == "search_pro":
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={"search_result": [raw_item("https://www.dell.com/zh-cn/u2723qe/a")]},
        )

    provider, _ = make_provider(handler, max_retries=1)
    result = await provider.search(source_request())
    await provider.aclose()

    assert calls == ["search_pro", "search_pro", "search_pro_sogou"]
    assert result.status == SourceSearchStatus.SUCCESS
    assert result.attempts[0].error == "ZhipuSourceSearchHTTPError"
    assert result.attempts[1].usable_result_count == 1


@pytest.mark.asyncio
async def test_no_region_match_is_an_explicit_degraded_result() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"search_result": [raw_item("https://www.dell.com/en-us/shop/u2723qe/a")]},
        )

    provider, _ = make_provider(handler)
    result = await provider.search(source_request())
    await provider.aclose()

    assert result.status == SourceSearchStatus.NO_REGION_MATCHED_SOURCE
    assert result.usable_candidates == []
    assert result.navigation_candidates
    assert result.degraded is True


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.asyncio
async def test_auth_errors_are_not_retried_or_fallback(status: int) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    provider, ledger = make_provider(handler)
    result = await provider.search(source_request())
    await provider.aclose()

    assert calls == 1
    assert result.status == SourceSearchStatus.PROVIDER_ERROR
    assert len(result.attempts) == 1
    assert ledger.summary()["call_count"] == 1


@pytest.mark.parametrize("failure", ["429", "503", "timeout"])
@pytest.mark.asyncio
async def test_retryable_errors_are_bounded(failure: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("simulated", request=request)
            return httpx.Response(int(failure))
        return httpx.Response(
            200,
            json={"search_result": [raw_item("https://www.dell.com/zh-cn/u2723qe/a")]},
        )

    provider, ledger = make_provider(handler, max_retries=1)
    result = await provider.search(source_request())
    await provider.aclose()

    assert calls == 4
    assert result.status == SourceSearchStatus.SUCCESS
    assert result.retries == 1
    assert ledger.summary()["call_count"] == 4


@pytest.mark.asyncio
async def test_empty_results_are_not_cached_or_fabricated() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"search_result": []})

    provider, _ = make_provider(handler)
    first = await provider.search(source_request())
    second = await provider.search(source_request())
    await provider.aclose()

    assert first.status == SourceSearchStatus.NO_OFFICIAL_SOURCE
    assert second.status == SourceSearchStatus.NO_OFFICIAL_SOURCE
    assert calls == 8
    assert first.usable_candidates == second.usable_candidates == []


@pytest.mark.asyncio
async def test_complete_results_have_consistent_cold_and_hot_cache_outputs() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"search_result": [raw_item("https://www.dell.com/zh-cn/u2723qe/a")]},
        )

    provider, _ = make_provider(handler)
    cold = await provider.search(source_request())
    hot = await provider.search(source_request())
    await provider.aclose()

    assert calls == 3
    assert cold.usable_candidates == hot.usable_candidates
    assert cold.cache_status.value == "miss"
    assert hot.cache_status.value == "hit"
    assert hot.estimated_cost_cny == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["usb_c_video", "resolution"])
async def test_tool_blocks_unnecessary_or_premature_network_calls(field: str) -> None:
    class NeverProvider:
        calls = 0

        async def search(self, _request):
            self.calls += 1
            raise AssertionError("network must not be called")

    provider = NeverProvider()
    tool = SourceSearchTool(source_settings(), provider)
    arguments = source_request(target_fields=[field]).model_dump(mode="json")
    arguments["_local_evidence_checked"] = True
    arguments["_local_evidence_sufficient"] = True
    result = await tool.invoke(arguments)
    assert result.error_code == "LOCAL_EVIDENCE_SUFFICIENT"
    assert result.data["search_executed"] is False

    arguments["_local_evidence_sufficient"] = False
    arguments["_local_evidence_checked"] = False
    arguments["trigger_reason"] = "missing_local_evidence"
    result = await tool.invoke(arguments)
    assert result.error_code == "LOCAL_EVIDENCE_CHECK_REQUIRED"
    assert provider.calls == 0


@pytest.mark.parametrize("model", ["FuturePanel-X1", "FuturePanel-X2"])
@pytest.mark.asyncio
async def test_out_of_catalog_models_execute_explicit_discovery(model: str) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "search_result": [
                    raw_item(f"https://www.dell.com/zh-cn/monitor/{model.casefold()}")
                ]
            },
        )

    provider, _ = make_provider(handler)
    tool = SourceSearchTool(source_settings(), provider)
    request = source_request(
        query=f"Dell {model} CN official specification",
        target_model=model,
        trigger_reason="out_of_catalog_model",
    )
    result = await tool.invoke(request.model_dump(mode="json"))
    await provider.aclose()
    assert result.status == "success"
    assert result.data["search_executed"] is True


@pytest.mark.asyncio
async def test_disabled_tool_keeps_local_path_available() -> None:
    settings = SourceSearchSettings(enabled=False)
    result = await SourceSearchTool(settings, None).invoke(source_request().model_dump(mode="json"))
    assert result.status == "unavailable"
    assert result.data["search_executed"] is False


def test_source_candidates_cannot_enter_evidence_or_checker() -> None:
    validator = DeterministicSourceValidator(source_settings().configured_domains)
    outcome = validator.validate(
        [raw_item("https://www.dell.com/zh-cn/u2723qe/a")],
        source_request(),
        provider="zhipu",
        engine="search_pro",
        queried_at="2026-09-01T00:00:00+00:00",
        local_request_id="local-3",
        provider_request_id=None,
    )
    candidate = outcome.usable_candidates[0]
    with pytest.raises(SourceIsolationError):
        candidate.to_evidence_record()
    with pytest.raises(SourceIsolationError):
        candidate.to_checker_input()
    with pytest.raises(SourceIsolationError):
        assert_source_candidates_isolated(outcome.usable_candidates)


def test_region_inference_uses_bounded_path_segments_and_locale_query() -> None:
    assert infer_region("https://example.com/products/en-us/model") == "US"
    assert infer_region("https://example.com/product?locale=en-CA") == "CA"
    assert infer_region("https://example.com/about-us/product") == "unknown"


def test_exact_title_can_discover_generic_official_url_but_remains_isolated() -> None:
    validator = DeterministicSourceValidator(source_settings().configured_domains)
    outcome = validator.validate(
        [raw_item("https://www.dell.com/en-us/shop/product/apd/123", title="Dell U2723QE")],
        source_request(region="US"),
        provider="zhipu",
        engine="search_pro",
        queried_at="2026-09-04T00:00:00Z",
        local_request_id="local-title",
        provider_request_id=None,
    )
    assert len(outcome.usable_candidates) == 1
    assert outcome.usable_candidates[0].model_match_source == "title"
    assert outcome.usable_candidates[0].usable_for_evidence is False
