"""Static official-page extractor with redirect-by-redirect URL safety checks."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urljoin

import httpx

from smartbuy.open_research.html_parser import ParsedHTML, parse_html
from smartbuy.open_research.models import (
    AlternateLink,
    ExtractionStatus,
    WebExtractionResult,
)
from smartbuy.open_research.settings import OpenResearchSettings
from smartbuy.open_research.url_safety import URLSafetyError, URLSafetyPolicy
from smartbuy.source_search import SourceCandidate, SourceCandidateStatus
from smartbuy.source_search.validator import infer_region, model_matches_title, model_matches_url


class WebExtractor(Protocol):
    async def extract(
        self,
        candidate: SourceCandidate,
        *,
        target_fields: list[str],
        field_terms: set[str],
        allowed_domains: list[str],
    ) -> WebExtractionResult: ...


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _language_region(language: str | None) -> str:
    if not language:
        return "unknown"
    normalized = language.replace("_", "-").casefold()
    parts = normalized.split("-")
    if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isalpha():
        return parts[-1].upper()
    return "unknown"


def _detected_region(url: str, language: str | None) -> str:
    from_url = infer_region(url)
    return from_url if from_url != "unknown" else _language_region(language)


def _hreflang_region(value: str | None) -> str:
    return _language_region(value)


def _page_matches_model(parsed: ParsedHTML, target_model: str, final_url: str) -> bool:
    if model_matches_url(target_model, final_url) or model_matches_title(target_model, parsed.title):
        return True
    compact = "".join(character for character in target_model.casefold() if character.isalnum())
    return bool(
        compact
        and any(
            compact in "".join(character for character in item.text.casefold() if character.isalnum())
            for item in parsed.snippets
        )
    )


class StaticHTMLExtractor:
    def __init__(
        self,
        settings: OpenResearchSettings,
        *,
        safety_policy: URLSafetyPolicy | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.safety_policy = safety_policy or URLSafetyPolicy()
        self._owns_client = client is None
        timeout = httpx.Timeout(
            connect=settings.connect_timeout_seconds,
            read=settings.read_timeout_seconds,
            write=settings.connect_timeout_seconds,
            pool=settings.connect_timeout_seconds,
        )
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={
                "User-Agent": "ProofPick/2.0 (+https://github.com/franklil0401/proofpick_agent)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _result(
        requested_url: str,
        status: ExtractionStatus,
        *,
        redirect_chain: list[str] | None = None,
        final_url: str | None = None,
        fetched_at: str | None = None,
        error: str | None = None,
        http_status: int | None = None,
        content_type: str | None = None,
    ) -> WebExtractionResult:
        return WebExtractionResult(
            requested_url=requested_url,
            final_url=final_url,
            redirect_chain=redirect_chain or [],
            fetched_at=fetched_at or _now(),
            http_status=http_status,
            content_type=content_type,
            status=status,
            degraded=status != ExtractionStatus.SUCCESS,
            error=error,
        )

    async def _safe_links(
        self,
        parsed: ParsedHTML,
        *,
        allowed_domains: list[str],
        target_model: str,
        page_model_confirmed: bool,
    ) -> tuple[str | None, list[AlternateLink]]:
        canonical: str | None = None
        if parsed.canonical_url and (
            page_model_confirmed or model_matches_url(target_model, parsed.canonical_url)
        ):
            try:
                canonical = (await self.safety_policy.validate(
                    parsed.canonical_url, allowed_domains
                )).url
            except URLSafetyError:
                canonical = None
        alternates: list[AlternateLink] = []
        for item in parsed.alternate_links:
            if not page_model_confirmed and not model_matches_url(target_model, item.url):
                continue
            try:
                safe = await self.safety_policy.validate(item.url, allowed_domains)
            except URLSafetyError:
                continue
            alternate = AlternateLink(url=safe.url, hreflang=item.hreflang)
            if alternate not in alternates:
                alternates.append(alternate)
            if len(alternates) >= 30:
                break
        return canonical, alternates

    async def _fetch(
        self,
        candidate: SourceCandidate,
        *,
        target_fields: list[str],
        field_terms: set[str],
        allowed_domains: list[str],
        allow_navigation: bool,
    ) -> WebExtractionResult:
        requested_url = candidate.url
        accepted_statuses = {SourceCandidateStatus.REGION_MATCHED}
        if allow_navigation:
            accepted_statuses.update(
                {SourceCandidateStatus.REGION_MISMATCH, SourceCandidateStatus.REGION_UNKNOWN}
            )
        if candidate.status not in accepted_statuses:
            return self._result(
                requested_url,
                ExtractionStatus.INVALID_SOURCE_CANDIDATE,
                error="source_candidate_status_rejected",
            )
        try:
            safe = await self.safety_policy.validate(requested_url, allowed_domains)
        except URLSafetyError as exc:
            return self._result(
                requested_url, ExtractionStatus.UNSAFE_URL, error=exc.code
            )
        requested_url = safe.url
        current_url = safe.url
        redirects: list[str] = []
        fetched_at = _now()
        try:
            async with asyncio.timeout(self.settings.total_timeout_seconds):
                while True:
                    async with self._client.stream("GET", current_url) as response:
                        status_code = response.status_code
                        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
                        if status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                return self._result(
                                    requested_url,
                                    ExtractionStatus.HTTP_ERROR,
                                    redirect_chain=redirects,
                                    final_url=current_url,
                                    fetched_at=fetched_at,
                                    error="redirect_without_location",
                                    http_status=status_code,
                                    content_type=content_type or None,
                                )
                            if len(redirects) >= self.settings.max_redirects:
                                return self._result(
                                    requested_url,
                                    ExtractionStatus.REDIRECT_LIMIT,
                                    redirect_chain=redirects,
                                    final_url=current_url,
                                    fetched_at=fetched_at,
                                    error="redirect_limit_exceeded",
                                    http_status=status_code,
                                    content_type=content_type or None,
                                )
                            next_url = urljoin(current_url, location)
                            try:
                                next_safe = await self.safety_policy.validate(
                                    next_url, allowed_domains
                                )
                            except URLSafetyError as exc:
                                return self._result(
                                    requested_url,
                                    ExtractionStatus.UNSAFE_URL,
                                    redirect_chain=redirects,
                                    final_url=current_url,
                                    fetched_at=fetched_at,
                                    error=f"redirect_{exc.code}",
                                    http_status=status_code,
                                    content_type=content_type or None,
                                )
                            redirects.append(next_safe.url)
                            current_url = next_safe.url
                            continue
                        if status_code < 200 or status_code >= 300:
                            return self._result(
                                requested_url,
                                ExtractionStatus.HTTP_ERROR,
                                redirect_chain=redirects,
                                final_url=current_url,
                                fetched_at=fetched_at,
                                error=f"http_{status_code}",
                                http_status=status_code,
                                content_type=content_type or None,
                            )
                        if content_type not in {"text/html", "application/xhtml+xml"}:
                            return self._result(
                                requested_url,
                                ExtractionStatus.NON_HTML,
                                redirect_chain=redirects,
                                final_url=current_url,
                                fetched_at=fetched_at,
                                error="content_type_rejected",
                                http_status=status_code,
                                content_type=content_type or None,
                            )
                        header_length = response.headers.get("content-length")
                        if header_length and header_length.isdigit() and int(header_length) > self.settings.max_html_bytes:
                            return self._result(
                                requested_url,
                                ExtractionStatus.CONTENT_TOO_LARGE,
                                redirect_chain=redirects,
                                final_url=current_url,
                                fetched_at=fetched_at,
                                error="content_length_exceeds_limit",
                                http_status=status_code,
                                content_type=content_type,
                            )
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > self.settings.max_html_bytes:
                                return self._result(
                                    requested_url,
                                    ExtractionStatus.CONTENT_TOO_LARGE,
                                    redirect_chain=redirects,
                                    final_url=current_url,
                                    fetched_at=fetched_at,
                                    error="decompressed_body_exceeds_limit",
                                    http_status=status_code,
                                    content_type=content_type,
                                )
                        encoding = response.encoding or "utf-8"
                        text = bytes(body).decode(encoding, errors="replace")
                        parsed = parse_html(
                            text,
                            base_url=current_url,
                            target_terms=field_terms | set(target_fields),
                            target_model=candidate.target_model,
                            max_snippets=self.settings.max_snippets,
                        )
                        page_model_confirmed = _page_matches_model(
                            parsed, candidate.target_model, current_url
                        )
                        canonical, alternates = await self._safe_links(
                            parsed,
                            allowed_domains=allowed_domains,
                            target_model=candidate.target_model,
                            page_model_confirmed=page_model_confirmed,
                        )
                        detected_region = _detected_region(current_url, parsed.language)
                        if not page_model_confirmed:
                            status = ExtractionStatus.EXTRACTION_INCOMPLETE
                            error = "final_page_model_not_matched"
                        elif not allow_navigation and detected_region != candidate.target_region:
                            status = ExtractionStatus.EXTRACTION_INCOMPLETE
                            error = "final_page_region_not_matched"
                        elif not parsed.snippets:
                            dynamic = parsed.script_count > 5 and parsed.visible_text_length < 500
                            status = (
                                ExtractionStatus.DYNAMIC_RENDER_REQUIRED
                                if dynamic
                                else ExtractionStatus.EXTRACTION_INCOMPLETE
                            )
                            error = status.value
                        else:
                            status = ExtractionStatus.SUCCESS
                            error = None
                        return WebExtractionResult(
                            requested_url=requested_url,
                            final_url=current_url,
                            redirect_chain=redirects,
                            title=parsed.title,
                            canonical_url=canonical,
                            alternate_links=alternates,
                            detected_region=detected_region,
                            detected_language=parsed.language,
                            fetched_at=fetched_at,
                            http_status=status_code,
                            content_type=content_type,
                            content_length=len(body),
                            content_hash=hashlib.sha256(body).hexdigest(),
                            snippets=parsed.snippets,
                            status=status,
                            degraded=status != ExtractionStatus.SUCCESS,
                            error=error,
                        )
        except (TimeoutError, httpx.TimeoutException):
            return self._result(
                requested_url,
                ExtractionStatus.TIMEOUT,
                redirect_chain=redirects,
                final_url=current_url,
                fetched_at=fetched_at,
                error="request_timeout",
            )
        except (httpx.HTTPError, UnicodeError):
            return self._result(
                requested_url,
                ExtractionStatus.HTTP_ERROR,
                redirect_chain=redirects,
                final_url=current_url,
                fetched_at=fetched_at,
                error="http_transport_error",
            )

    async def extract(
        self,
        candidate: SourceCandidate,
        *,
        target_fields: list[str],
        field_terms: set[str],
        allowed_domains: list[str],
    ) -> WebExtractionResult:
        return await self._fetch(
            candidate,
            target_fields=target_fields,
            field_terms=field_terms,
            allowed_domains=allowed_domains,
            allow_navigation=False,
        )

    async def discover_target_candidate(
        self,
        candidate: SourceCandidate,
        *,
        target_fields: list[str],
        field_terms: set[str],
        allowed_domains: list[str],
    ) -> tuple[WebExtractionResult, SourceCandidate | None]:
        inspection = await self._fetch(
            candidate,
            target_fields=target_fields,
            field_terms=field_terms,
            allowed_domains=allowed_domains,
            allow_navigation=True,
        )
        if (
            inspection.status == ExtractionStatus.SUCCESS
            and inspection.detected_region == candidate.target_region
            and inspection.final_url
        ):
            try:
                safe = await self.safety_policy.validate(
                    inspection.final_url, allowed_domains
                )
            except URLSafetyError:
                safe = None
            if safe is not None:
                return inspection, SourceCandidate(
                    title=inspection.title or candidate.title,
                    url=safe.url,
                    hostname=safe.hostname,
                    site_name=candidate.site_name,
                    date_published=candidate.date_published,
                    queried_at=candidate.queried_at,
                    local_request_id=candidate.local_request_id,
                    provider_request_id=candidate.provider_request_id,
                    provider=candidate.provider,
                    engine="final_page_region_discovery",
                    target_model=candidate.target_model,
                    target_region=candidate.target_region,
                    observed_region=candidate.target_region,
                    status=SourceCandidateStatus.REGION_MATCHED,
                    model_match_source=candidate.model_match_source,
                )
        links: list[tuple[str, str]] = []
        if inspection.canonical_url:
            links.append((inspection.canonical_url, infer_region(inspection.canonical_url)))
        links.extend(
            (item.url, _hreflang_region(item.hreflang) or infer_region(item.url))
            for item in inspection.alternate_links
        )
        for url, region in links:
            observed_region = region if region != "unknown" else infer_region(url)
            if observed_region != candidate.target_region:
                continue
            if not model_matches_url(candidate.target_model, url):
                continue
            try:
                safe = await self.safety_policy.validate(url, allowed_domains)
            except URLSafetyError:
                continue
            return inspection, SourceCandidate(
                title=inspection.title or candidate.title,
                url=safe.url,
                hostname=safe.hostname,
                site_name=candidate.site_name,
                date_published=candidate.date_published,
                queried_at=candidate.queried_at,
                local_request_id=candidate.local_request_id,
                provider_request_id=candidate.provider_request_id,
                provider=candidate.provider,
                engine="canonical_hreflang_discovery",
                target_model=candidate.target_model,
                target_region=candidate.target_region,
                observed_region=observed_region,
                status=SourceCandidateStatus.REGION_MATCHED,
                model_match_source=(
                    "url" if model_matches_url(candidate.target_model, safe.url) else "title"
                ),
            )
        return inspection, None
