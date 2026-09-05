"""Isolated, default-off helpers for the V2-9G Online feasibility PoC.

Nothing in this module is registered with the production API or Agent.  It is
kept under ``smartbuy.eval`` so Playwright and alternate-provider experiments
cannot silently become part of the trusted runtime.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from smartbuy.domain_packs.loader import LoadedDomainPack
from smartbuy.open_research.extractor import _detected_region, _page_matches_model
from smartbuy.open_research.html_parser import parse_html
from smartbuy.open_research.models import ExtractionStatus, WebExtractionResult
from smartbuy.open_research.normalizer import EvidenceNormalizer, field_terms
from smartbuy.open_research.url_safety import URLSafetyError, URLSafetyPolicy
from smartbuy.source_search.models import SourceCandidate, SourceCandidateStatus
from smartbuy.source_search.validator import (
    DeterministicSourceValidator,
    hostname_allowed,
    normalize_hostname,
    normalize_url,
)


@dataclass(frozen=True)
class BrowserPoCSettings:
    enabled: bool = False
    navigation_timeout_ms: int = 15_000
    settle_timeout_ms: int = 2_500
    max_html_bytes: int = 5 * 1024 * 1024
    max_redirects: int = 3
    max_snippets: int = 100

    @classmethod
    def from_environment(cls) -> BrowserPoCSettings:
        raw = os.getenv("PROOFPICK_V2_BROWSER_POC_ENABLED", "false").strip().casefold()
        if raw not in {"true", "false"}:
            raise ValueError("PROOFPICK_V2_BROWSER_POC_ENABLED must be true or false")
        return cls(enabled=raw == "true")


class BrowserPoCRejected(RuntimeError):
    pass


def _redirect_chain(response: Any) -> list[str]:
    chain: list[str] = []
    request = response.request if response is not None else None
    while request is not None:
        chain.append(str(request.url))
        request = request.redirected_from
    return list(reversed(chain))


def assess_rendered_html(
    html_text: str,
    *,
    candidate: SourceCandidate,
    final_url: str,
    target_fields: list[str],
    pack: LoadedDomainPack,
    settings: BrowserPoCSettings,
) -> tuple[WebExtractionResult, list[str]]:
    """Validate and normalize rendered HTML without persisting page content."""
    encoded = html_text.encode("utf-8")
    if len(encoded) > settings.max_html_bytes:
        raise BrowserPoCRejected("rendered_html_too_large")
    terms = field_terms(pack, target_fields)
    parsed = parse_html(
        html_text,
        base_url=final_url,
        target_terms=terms | set(target_fields),
        target_model=candidate.target_model,
        max_snippets=settings.max_snippets,
    )
    detected_region = _detected_region(final_url, parsed.language)
    if not _page_matches_model(parsed, candidate.target_model, final_url):
        raise BrowserPoCRejected("rendered_page_model_not_matched")
    if detected_region != candidate.target_region:
        raise BrowserPoCRejected("rendered_page_region_not_matched")
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    extraction = WebExtractionResult(
        requested_url=candidate.url,
        final_url=final_url,
        title=parsed.title or candidate.title,
        canonical_url=parsed.canonical_url,
        alternate_links=parsed.alternate_links,
        related_links=parsed.related_links,
        detected_region=detected_region,
        detected_language=parsed.language,
        fetched_at=now,
        http_status=200,
        content_type="text/html",
        content_length=len(encoded),
        content_hash=hashlib.sha256(encoded).hexdigest(),
        snippets=parsed.snippets,
        status=ExtractionStatus.SUCCESS,
    )
    records, _ = EvidenceNormalizer(pack).normalize(
        extraction,
        user_scope="poc-user",
        session_scope="poc-session",
        thread_scope="poc-thread",
        request_scope="poc-request",
        provisional_product_id="v2-9g-browser-poc",
        target_model=candidate.target_model,
        product_region=candidate.target_region,
        target_fields=target_fields,
        configuration=candidate.target_model,
    )
    return extraction, sorted({item.field_name for item in records})


async def render_with_playwright(
    candidate: SourceCandidate,
    *,
    target_fields: list[str],
    allowed_domains: list[str],
    pack: LoadedDomainPack,
    settings: BrowserPoCSettings,
    safety_policy: URLSafetyPolicy | None = None,
) -> dict[str, Any]:
    """Render one already region-matched official candidate under strict limits."""
    started = time.perf_counter()
    if not settings.enabled:
        return {"status": "disabled", "network_executed": False, "latency_ms": 0.0}
    if candidate.status != SourceCandidateStatus.REGION_MATCHED:
        return {
            "status": "rejected",
            "reason": "candidate_not_region_matched",
            "network_executed": False,
            "latency_ms": 0.0,
        }
    policy = safety_policy or URLSafetyPolicy()
    try:
        safe = await policy.validate(candidate.url, allowed_domains)
    except URLSafetyError as exc:
        return {
            "status": "rejected",
            "reason": exc.code,
            "network_executed": False,
            "latency_ms": 0.0,
        }

    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "status": "unavailable",
            "reason": "playwright_not_installed",
            "network_executed": False,
            "latency_ms": 0.0,
        }

    blocked_requests = 0
    allowed_hosts: set[str] = set()
    redirect_urls: list[str] = []
    browser = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                accept_downloads=False,
                java_script_enabled=True,
                service_workers="block",
            )

            async def route_request(route: Any, request: Any) -> None:
                nonlocal blocked_requests
                raw_url = str(request.url)
                normalized = normalize_url(raw_url)
                hostname = normalize_hostname(urlsplit(normalized).hostname) if normalized else None
                if (
                    normalized is None
                    or not hostname_allowed(hostname, allowed_domains)
                    or request.resource_type in {"image", "media", "font"}
                ):
                    blocked_requests += 1
                    await route.abort()
                    return
                if hostname not in allowed_hosts:
                    try:
                        await policy.validate(normalized, allowed_domains)
                    except URLSafetyError:
                        blocked_requests += 1
                        await route.abort()
                        return
                    allowed_hosts.add(hostname)
                await route.continue_()

            await context.route("**/*", route_request)
            page = await context.new_page()
            page.on("download", lambda download: asyncio.create_task(download.cancel()))
            response = await page.goto(
                safe.url,
                wait_until="domcontentloaded",
                timeout=settings.navigation_timeout_ms,
            )
            if response is None or response.status >= 400:
                raise BrowserPoCRejected(
                    f"http_{response.status if response is not None else 'missing'}"
                )
            try:
                await page.wait_for_load_state(
                    "networkidle", timeout=settings.settle_timeout_ms
                )
            except PlaywrightTimeoutError:
                pass
            final_url = str(page.url)
            final_safe = await policy.validate(final_url, allowed_domains)
            redirect_urls = _redirect_chain(response)
            if len(redirect_urls) - 1 > settings.max_redirects:
                raise BrowserPoCRejected("redirect_limit")
            html_text = await page.content()
            extraction, verified_fields = assess_rendered_html(
                html_text,
                candidate=candidate,
                final_url=final_safe.url,
                target_fields=target_fields,
                pack=pack,
                settings=settings,
            )
            await context.close()
        return {
            "status": "success",
            "network_executed": True,
            "http_status": response.status if response is not None else None,
            "final_hostname": normalize_hostname(urlsplit(extraction.final_url).hostname),
            "redirect_count": max(0, len(redirect_urls) - 1),
            "blocked_request_count": blocked_requests,
            "content_length": extraction.content_length,
            "snippet_count": len(extraction.snippets),
            "verified_fields": verified_fields,
            "requested_field_count": len(target_fields),
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    except PlaywrightTimeoutError:
        return {
            "status": "timeout",
            "network_executed": True,
            "blocked_request_count": blocked_requests,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    except (BrowserPoCRejected, URLSafetyError) as exc:
        return {
            "status": "rejected",
            "reason": exc.code if isinstance(exc, URLSafetyError) else str(exc),
            "network_executed": True,
            "blocked_request_count": blocked_requests,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    except Exception as exc:  # pragma: no cover - live browser diagnostics
        return {
            "status": "browser_error",
            "reason": type(exc).__name__,
            "network_executed": True,
            "blocked_request_count": blocked_requests,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    finally:
        if browser is not None and browser.is_connected():
            await browser.close()


async def bocha_search_once(
    *,
    api_key: str,
    request: Any,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    """Run one bounded Bocha discovery call and reapply the local validator."""
    local_request_id = uuid.uuid4().hex
    query = f"{request.query} official site:{request.allowed_domains[0]}"
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False) as client:
        response = await client.post(
            "https://api.bochaai.com/v1/web-search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "query": query,
                "freshness": request.freshness,
                "summary": False,
                "count": 10,
            },
        )
    latency_ms = (time.perf_counter() - started) * 1000
    if response.status_code in {401, 403}:
        return {
            "status": "auth_error",
            "http_status": response.status_code,
            "attempts": 1,
            "latency_ms": round(latency_ms, 3),
        }
    if response.status_code >= 400:
        return {
            "status": "provider_error",
            "http_status": response.status_code,
            "attempts": 1,
            "latency_ms": round(latency_ms, 3),
        }
    try:
        payload = response.json()
    except ValueError:
        return {
            "status": "provider_error",
            "http_status": response.status_code,
            "attempts": 1,
            "latency_ms": round(latency_ms, 3),
        }
    if payload.get("code") not in {None, 200}:
        return {
            "status": "provider_error",
            "http_status": response.status_code,
            "provider_code": payload.get("code"),
            "attempts": 1,
            "latency_ms": round(latency_ms, 3),
        }
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    web_pages = data.get("webPages", {}) if isinstance(data, dict) else {}
    values = web_pages.get("value", []) if isinstance(web_pages, dict) else []
    raw = [
        {
            "title": item.get("name"),
            "link": item.get("url"),
            "media": item.get("siteName"),
            "publish_date": item.get("datePublished"),
        }
        for item in values[:50]
        if isinstance(item, dict)
    ]
    queried_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    outcome = DeterministicSourceValidator(
        tuple(request.allowed_domains), raw_limit=50, usable_limit=10
    ).validate(
        raw,
        request,
        provider="bocha",
        engine="web-search",
        queried_at=queried_at,
        local_request_id=local_request_id,
        provider_request_id=(str(payload.get("log_id")) if payload.get("log_id") else None),
    )
    return {
        "status": "success",
        "http_status": response.status_code,
        "provider_code": payload.get("code"),
        "attempts": 1,
        "latency_ms": round(latency_ms, 3),
        "raw_result_count": len(values),
        "scanned_result_count": len(raw),
        "usable_candidate_count": len(outcome.usable_candidates),
        "navigation_candidate_count": len(outcome.navigation_candidates),
        "rejected_candidate_count": len(outcome.rejected_candidates),
        "provider_request_id_present": bool(payload.get("log_id")),
        "usable_candidates": outcome.usable_candidates,
        "estimated_cost_cny": 0.0,
        "cost_basis": "provider_response_has_no_usage_field; public individual pricing listed as free",
    }
