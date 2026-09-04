"""Deterministic URL, model and region validation for untrusted search metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit

from smartbuy.source_search.models import (
    SourceCandidate,
    SourceCandidateStatus,
    SourceSearchRequest,
    SourceValidationStats,
)


def normalize_hostname(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip().rstrip(".").lower()
    try:
        return value.encode("idna").decode("ascii")
    except UnicodeError:
        return None


def normalize_url(raw: Any) -> str | None:
    if not raw:
        return None
    try:
        parts = urlsplit(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if parts.scheme.lower() not in {"http", "https"}:
        return None
    hostname = normalize_hostname(parts.hostname)
    if not hostname:
        return None
    try:
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return None
    return urlunsplit((parts.scheme.lower(), hostname + port, parts.path or "/", parts.query, ""))


def hostname_allowed(hostname: str | None, allowed_domains: list[str] | tuple[str, ...]) -> bool:
    normalized = normalize_hostname(hostname)
    if not normalized:
        return False
    for candidate in allowed_domains:
        root = normalize_hostname(candidate)
        if root and (normalized == root or normalized.endswith("." + root)):
            return True
    return False


def infer_region(url: str) -> str:
    parts = urlsplit(url)
    hostname = normalize_hostname(parts.hostname) or ""
    segments = [item.casefold() for item in parts.path.split("/") if item]
    query = {
        key.casefold(): [item.casefold() for item in values]
        for key, values in parse_qs(parts.query).items()
    }
    if hostname == "asus.com.cn" or hostname.endswith(".asus.com.cn"):
        return "CN"
    if hostname == "benq.com.cn" or hostname.endswith(".benq.com.cn"):
        return "CN"
    locale_regions = {
        "cn": "CN", "zh-cn": "CN", "zh_cn": "CN",
        "us": "US", "en-us": "US", "en_us": "US",
        "ca": "CA", "en-ca": "CA", "en_ca": "CA",
        "ie": "IE",
        "en-ie": "IE",
        "en_ie": "IE",
        "tw": "TW",
        "zh-tw": "TW",
        "hk": "HK",
        "zh-hk": "HK",
        "de": "DE",
        "de-de": "DE",
        "cz": "CZ",
        "cs-cz": "CZ",
    }
    for key in ("country", "region", "market", "locale", "lang"):
        for value in query.get(key, []):
            if value in locale_regions:
                return locale_regions[value]
    for segment in segments[:4]:
        if segment in locale_regions:
            return locale_regions[segment]
    return "unknown"


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def model_matches_url(target_model: str, url: str) -> bool:
    """Match a complete model token while allowing punctuation inside the model."""
    compact_model = _compact(target_model)
    if not compact_model:
        return False
    decoded = unquote(unquote(url)).casefold()
    flexible = r"[^a-z0-9]*".join(re.escape(character) for character in compact_model)
    return re.search(rf"(?<![a-z0-9]){flexible}(?![a-z0-9])", decoded) is not None


def model_matches_title(target_model: str, title: str | None) -> bool:
    """Accept an exact normalized model phrase in provider title metadata.

    Search metadata remains discovery-only. The fetched page is independently
    checked again before any field can become Open Evidence.
    """
    return bool(title and _compact(target_model) in _compact(title))


def _url_has_conflicting_model_code(target_model: str, url: str) -> bool:
    """Reject title fallback when a code-like target conflicts with a URL code."""
    target_tokens = re.findall(r"[a-z0-9]+", target_model.casefold())
    code_like_target = bool(target_tokens) and all(
        any(character.isdigit() for character in token) or len(token) <= 2
        for token in target_tokens
    )
    if not code_like_target:
        return False
    compact_target = _compact(target_model)
    url_tokens = re.findall(r"[a-z0-9]+", unquote(unquote(url)).casefold())
    codes = [
        token
        for token in url_tokens
        if len(token) >= 5
        and any(character.isdigit() for character in token)
        and any(character.isalpha() for character in token)
    ]
    return any(token != compact_target for token in codes)


@dataclass(frozen=True)
class SourceValidationOutcome:
    usable_candidates: list[SourceCandidate]
    navigation_candidates: list[SourceCandidate]
    rejected_candidates: list[SourceCandidate]
    stats: SourceValidationStats


class DeterministicSourceValidator:
    """Treat provider filters as hints and independently enforce every boundary."""

    def __init__(
        self,
        configured_domains: tuple[str, ...],
        *,
        raw_limit: int = 50,
        usable_limit: int = 10,
        navigation_limit: int = 10,
        rejected_limit: int = 10,
    ) -> None:
        self.configured_domains = tuple(
            item for item in (normalize_hostname(value) for value in configured_domains) if item
        )
        self.raw_limit = raw_limit
        self.usable_limit = usable_limit
        self.navigation_limit = navigation_limit
        self.rejected_limit = rejected_limit

    def validate_request(self, request: SourceSearchRequest) -> None:
        for requested in request.allowed_domains:
            normalized = normalize_hostname(requested)
            if not normalized or normalized not in self.configured_domains:
                raise ValueError(f"domain is not in the configured official allowlist: {requested}")

    def validate(
        self,
        raw_results: list[Any],
        request: SourceSearchRequest,
        *,
        provider: str,
        engine: str,
        queried_at: str,
        local_request_id: str,
        provider_request_id: str | None,
    ) -> SourceValidationOutcome:
        self.validate_request(request)
        usable: list[SourceCandidate] = []
        navigation: list[SourceCandidate] = []
        rejected: list[SourceCandidate] = []
        counters = {
            "valid_url_count": 0,
            "domain_matched_count": 0,
            "model_matched_count": 0,
            "region_matched_count": 0,
            "required_metadata_count": 0,
            "site_name_missing_count": 0,
            "date_published_missing_count": 0,
            "metadata_incomplete_count": 0,
        }
        scanned = raw_results[: self.raw_limit]
        for item in scanned:
            item = item if isinstance(item, dict) else {}
            raw_url = str(item.get("link") or "")[:2_048]
            title = str(item.get("title") or "").strip()[:500] or None
            site_name = str(item.get("media") or item.get("site_name") or "").strip()[:300] or None
            date_published = str(item.get("publish_date") or item.get("date_published") or "").strip()[:100] or None
            normalized_url = normalize_url(raw_url)
            hostname = normalize_hostname(urlsplit(normalized_url).hostname) if normalized_url else None
            status: SourceCandidateStatus
            observed_region = "unknown"
            model_match_source: str | None = None
            if normalized_url is None:
                status = SourceCandidateStatus.INVALID_URL
            elif not hostname_allowed(hostname, request.allowed_domains):
                counters["valid_url_count"] += 1
                status = SourceCandidateStatus.DOMAIN_REJECTED
            else:
                counters["valid_url_count"] += 1
                counters["domain_matched_count"] += 1
                if model_matches_url(request.target_model, normalized_url):
                    model_match_source = "url"
                elif model_matches_title(request.target_model, title) and not _url_has_conflicting_model_code(
                    request.target_model, normalized_url
                ):
                    model_match_source = "title"
                else:
                    model_match_source = None
                if model_match_source is None:
                    status = SourceCandidateStatus.MODEL_MISMATCH
                else:
                    counters["model_matched_count"] += 1
                    observed_region = infer_region(normalized_url)
                    if observed_region == "unknown":
                        status = SourceCandidateStatus.REGION_UNKNOWN
                    elif observed_region != request.region:
                        status = SourceCandidateStatus.REGION_MISMATCH
                    else:
                        status = SourceCandidateStatus.REGION_MATCHED
                        counters["region_matched_count"] += 1
            candidate = SourceCandidate(
                title=title,
                url=normalized_url or raw_url,
                hostname=hostname,
                site_name=site_name,
                date_published=date_published,
                queried_at=queried_at,
                local_request_id=local_request_id,
                provider_request_id=provider_request_id,
                provider=provider,
                engine=engine,
                target_model=request.target_model,
                target_region=request.region,
                observed_region=observed_region,
                status=status,
                model_match_source=model_match_source if normalized_url else None,
            )
            if not site_name:
                counters["site_name_missing_count"] += 1
            if not date_published:
                counters["date_published_missing_count"] += 1
            if status == SourceCandidateStatus.REGION_MATCHED:
                if not title:
                    counters["metadata_incomplete_count"] += 1
                    continue
                counters["required_metadata_count"] += 1
                if len(usable) < min(request.max_results, self.usable_limit):
                    usable.append(candidate)
            elif status in {
                SourceCandidateStatus.REGION_MISMATCH,
                SourceCandidateStatus.REGION_UNKNOWN,
            }:
                if title and len(navigation) < self.navigation_limit:
                    navigation.append(candidate)
                elif not title:
                    counters["metadata_incomplete_count"] += 1
            elif len(rejected) < self.rejected_limit:
                rejected.append(candidate)
        return SourceValidationOutcome(
            usable_candidates=usable,
            navigation_candidates=navigation,
            rejected_candidates=rejected,
            stats=SourceValidationStats(
                raw_result_count=len(raw_results),
                scanned_result_count=len(scanned),
                **counters,
            ),
        )
