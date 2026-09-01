"""Auditable Zhipu official-source discovery with deterministic safety filtering."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

import httpx

from smartbuy.observability import UsageLedger, UsageRecord
from smartbuy.source_search.cache import SourceSearchCachePolicy, TTLSourceSearchCache
from smartbuy.source_search.models import (
    SourceEngineOutcome,
    SourceSearchAttempt,
    SourceSearchCacheStatus,
    SourceSearchRequest,
    SourceSearchResult,
    SourceSearchStatus,
)
from smartbuy.source_search.provider import SourceSearchProvider
from smartbuy.source_search.settings import SourceSearchSettings
from smartbuy.source_search.validator import DeterministicSourceValidator


class ZhipuSourceSearchError(RuntimeError):
    """Sanitized provider error that never contains request or response content."""


class ZhipuSourceSearchHTTPError(ZhipuSourceSearchError):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"Zhipu Web Search failed with HTTP {status_code}")


class ZhipuSourceSearchAuthError(ZhipuSourceSearchHTTPError):
    """Non-retryable authentication or authorization failure."""


class ZhipuSourceSearchResponseError(ZhipuSourceSearchError):
    """Provider response violated the documented metadata contract."""


@dataclass
class _SearchBudget:
    calls: int = 0
    estimated_cost_cny: float = 0.0


class ZhipuSourceSearchProvider(SourceSearchProvider):
    """Search official pages; never extract or promote their contents to evidence."""

    name = "zhipu"
    version = "v2-3.1"
    _RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        settings: SourceSearchSettings,
        *,
        client: httpx.AsyncClient | None = None,
        validator: DeterministicSourceValidator | None = None,
        cache: TTLSourceSearchCache | None = None,
        ledger: UsageLedger | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not settings.enabled or not settings.api_key:
            raise ValueError("Zhipu Source Search requires an enabled, configured settings object")
        self.settings = settings
        self.validator = validator or DeterministicSourceValidator(
            settings.configured_domains,
            raw_limit=settings.raw_result_limit,
            usable_limit=settings.usable_result_limit,
            navigation_limit=settings.navigation_result_limit,
        )
        self.cache = cache or TTLSourceSearchCache(
            SourceSearchCachePolicy(
                ttl_seconds=settings.cache_ttl_seconds,
                max_entries=settings.cache_max_entries,
            )
        )
        self.ledger = ledger or UsageLedger()
        self._client_owned = client is None
        self._client = client or httpx.AsyncClient(timeout=settings.timeout_seconds)
        self._sleep = sleep
        self._rate_lock = asyncio.Lock()
        self._last_call_started = 0.0

    async def aclose(self) -> None:
        if self._client_owned:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

    async def _throttle(self) -> None:
        async with self._rate_lock:
            now = time.monotonic()
            wait_seconds = max(
                0.0,
                (1.0 / self.settings.max_rps) - (now - self._last_call_started),
            )
            if wait_seconds:
                await self._sleep(wait_seconds)
            self._last_call_started = time.monotonic()

    @staticmethod
    def _engine_cost(engine: str) -> float:
        if engine == "search_pro_sogou":
            return 0.05
        return 0.03

    def _check_budget(self, budget: _SearchBudget, engine: str) -> None:
        next_cost = self._engine_cost(engine)
        if budget.calls >= self.settings.max_search_calls:
            raise ZhipuSourceSearchError("source search call budget exhausted")
        if budget.estimated_cost_cny + next_cost > self.settings.max_cost_cny:
            raise ZhipuSourceSearchError("source search cost budget exhausted")

    def _record_call(
        self,
        *,
        engine: str,
        success: bool,
        latency_ms: float,
        status_code: int | None,
        item_count: int,
    ) -> None:
        self.ledger.add(
            UsageRecord(
                operation="source_search",
                model=engine,
                success=success,
                attempts=1,
                latency_ms=round(latency_ms, 3),
                item_count=item_count,
                estimated_cost_cny=self._engine_cost(engine),
                degraded=not success,
                status_code=status_code,
            )
        )

    async def _post(
        self,
        *,
        request: SourceSearchRequest,
        engine: str,
        budget: _SearchBudget,
        local_request_id: str,
    ) -> tuple[dict[str, Any], int, int, float]:
        payload = {
            "search_query": request.query,
            "search_engine": engine,
            "search_intent": False,
            "count": min(request.max_results, self.settings.requested_count),
            "search_domain_filter": request.allowed_domains[0],
            "search_recency_filter": request.freshness,
            "content_size": "small",
            "request_id": local_request_id,
        }
        started = time.perf_counter()
        total_attempts = self.settings.max_retries + 1
        last_status: int | None = None
        for attempt in range(1, total_attempts + 1):
            self._check_budget(budget, engine)
            await self._throttle()
            call_started = time.perf_counter()
            budget.calls += 1
            budget.estimated_cost_cny += self._engine_cost(engine)
            try:
                response = await self._client.post(
                    self.settings.endpoint,
                    json=payload,
                    headers=self._headers(),
                )
                last_status = response.status_code
                if response.status_code in (401, 403):
                    self._record_call(
                        engine=engine,
                        success=False,
                        latency_ms=(time.perf_counter() - call_started) * 1000,
                        status_code=response.status_code,
                        item_count=0,
                    )
                    raise ZhipuSourceSearchAuthError(response.status_code)
                if response.status_code >= 400:
                    self._record_call(
                        engine=engine,
                        success=False,
                        latency_ms=(time.perf_counter() - call_started) * 1000,
                        status_code=response.status_code,
                        item_count=0,
                    )
                    if response.status_code not in self._RETRYABLE_STATUS:
                        raise ZhipuSourceSearchHTTPError(response.status_code)
                    if attempt == total_attempts:
                        raise ZhipuSourceSearchHTTPError(response.status_code)
                else:
                    try:
                        body = response.json()
                    except (ValueError, json.JSONDecodeError) as exc:
                        self._record_call(
                            engine=engine,
                            success=False,
                            latency_ms=(time.perf_counter() - call_started) * 1000,
                            status_code=response.status_code,
                            item_count=0,
                        )
                        raise ZhipuSourceSearchResponseError(
                            "Zhipu Web Search returned invalid JSON"
                        ) from exc
                    results = body.get("search_result")
                    if not isinstance(results, list):
                        self._record_call(
                            engine=engine,
                            success=False,
                            latency_ms=(time.perf_counter() - call_started) * 1000,
                            status_code=response.status_code,
                            item_count=0,
                        )
                        raise ZhipuSourceSearchResponseError(
                            "Zhipu Web Search response contains no search_result list"
                        )
                    self._record_call(
                        engine=engine,
                        success=True,
                        latency_ms=(time.perf_counter() - call_started) * 1000,
                        status_code=response.status_code,
                        item_count=len(results),
                    )
                    return body, response.status_code, attempt, (
                        time.perf_counter() - started
                    ) * 1000
            except ZhipuSourceSearchAuthError:
                raise
            except ZhipuSourceSearchHTTPError:
                if attempt == total_attempts or last_status not in self._RETRYABLE_STATUS:
                    raise
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                self._record_call(
                    engine=engine,
                    success=False,
                    latency_ms=(time.perf_counter() - call_started) * 1000,
                    status_code=None,
                    item_count=0,
                )
                if attempt == total_attempts:
                    raise ZhipuSourceSearchError(
                        f"Zhipu Web Search transport failed after {attempt} attempt(s)"
                    ) from exc
            except asyncio.CancelledError:
                self._record_call(
                    engine=engine,
                    success=False,
                    latency_ms=(time.perf_counter() - call_started) * 1000,
                    status_code=None,
                    item_count=0,
                )
                raise
            if attempt < total_attempts:
                await self._sleep(self.settings.retry_delay_seconds * attempt)
        raise AssertionError("bounded retry loop exited unexpectedly")

    async def _search_engine(
        self,
        request: SourceSearchRequest,
        engine: str,
        budget: _SearchBudget,
    ) -> SourceEngineOutcome:
        cache_key = self.cache.key(
            request,
            provider=self.name,
            provider_version=self.version,
            engine=engine,
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            cached.network_executed = False
            cached.cache_status = SourceSearchCacheStatus.HIT
            cached.estimated_cost_cny = 0.0
            cached.attempts = 0
            cached.retries = 0
            return cached

        local_request_id = uuid.uuid4().hex
        requested_at = datetime.now(UTC).isoformat()
        started = time.perf_counter()
        calls_before = budget.calls
        cost_before = budget.estimated_cost_cny
        try:
            body, http_status, attempts, latency_ms = await self._post(
                request=request,
                engine=engine,
                budget=budget,
                local_request_id=local_request_id,
            )
            provider_request_id = body.get("request_id")
            if not isinstance(provider_request_id, str):
                provider_request_id = None
            validation = self.validator.validate(
                body["search_result"],
                request,
                provider=self.name,
                engine=engine,
                queried_at=requested_at,
                local_request_id=local_request_id,
                provider_request_id=provider_request_id,
            )
            outcome = SourceEngineOutcome(
                provider=self.name,
                provider_version=self.version,
                engine=engine,
                requested_count=min(request.max_results, self.settings.requested_count),
                requested_at=requested_at,
                local_request_id=local_request_id,
                provider_request_id=provider_request_id,
                http_status=http_status,
                attempts=attempts,
                retries=max(0, attempts - 1),
                latency_ms=latency_ms,
                network_executed=True,
                cache_status=SourceSearchCacheStatus.MISS,
                estimated_cost_cny=round(budget.estimated_cost_cny - cost_before, 8),
                usable_candidates=validation.usable_candidates,
                navigation_candidates=validation.navigation_candidates,
                rejected_candidates=validation.rejected_candidates,
                stats=validation.stats,
            )
            if outcome.complete_and_cacheable:
                self.cache.put(cache_key, outcome)
            return outcome
        except ZhipuSourceSearchError as exc:
            return SourceEngineOutcome(
                provider=self.name,
                provider_version=self.version,
                engine=engine,
                requested_count=min(request.max_results, self.settings.requested_count),
                requested_at=requested_at,
                local_request_id=local_request_id,
                latency_ms=(time.perf_counter() - started) * 1000,
                attempts=budget.calls - calls_before,
                retries=max(0, budget.calls - calls_before - 1),
                network_executed=budget.calls > calls_before,
                cache_status=SourceSearchCacheStatus.MISS,
                error=type(exc).__name__,
                estimated_cost_cny=round(
                    budget.estimated_cost_cny - cost_before,
                    8,
                ),
                http_status=getattr(exc, "status_code", None),
                stats={
                    "raw_result_count": 0,
                    "scanned_result_count": 0,
                    "valid_url_count": 0,
                    "domain_matched_count": 0,
                    "model_matched_count": 0,
                    "region_matched_count": 0,
                    "required_metadata_count": 0,
                    "site_name_missing_count": 0,
                    "date_published_missing_count": 0,
                    "metadata_incomplete_count": 0,
                },
            )

    async def search(self, request: SourceSearchRequest) -> SourceSearchResult:
        started = time.perf_counter()
        ledger_start = len(self.ledger.snapshot())
        try:
            self.validator.validate_request(request)
        except ValueError:
            return SourceSearchResult(
                provider=self.name,
                provider_version=self.version,
                engine=self.settings.primary_engine,
                status=SourceSearchStatus.PROVIDER_ERROR,
                search_executed=False,
                network_executed=False,
                requested_count=request.max_results,
                raw_result_count=0,
                scanned_result_count=0,
                usable_result_count=0,
                requested_at=datetime.now(UTC).isoformat(),
                latency_ms=(time.perf_counter() - started) * 1000,
                request_id=uuid.uuid4().hex,
                retries=0,
                cache_status=SourceSearchCacheStatus.BYPASS,
                degraded=True,
                error="InvalidSourceSearchRequest",
                estimated_cost_cny=0.0,
                trigger_reason=request.trigger_reason,
            )
        try:
            async with asyncio.timeout(self.settings.total_timeout_seconds):
                return await self._search_bounded(request)
        except TimeoutError:
            records = self.ledger.snapshot()[ledger_start:]
            return SourceSearchResult(
                provider=self.name,
                provider_version=self.version,
                engine=self.settings.primary_engine,
                status=SourceSearchStatus.PROVIDER_ERROR,
                search_executed=True,
                network_executed=bool(records),
                requested_count=request.max_results,
                raw_result_count=0,
                scanned_result_count=0,
                usable_result_count=0,
                requested_at=datetime.now(UTC).isoformat(),
                latency_ms=(time.perf_counter() - started) * 1000,
                request_id=uuid.uuid4().hex,
                retries=max(0, len(records) - 1),
                cache_status=SourceSearchCacheStatus.MISS,
                degraded=True,
                error="SourceSearchTotalTimeout",
                estimated_cost_cny=round(
                    sum(float(item["estimated_cost_cny"]) for item in records),
                    8,
                ),
                trigger_reason=request.trigger_reason,
            )

    async def _search_bounded(self, request: SourceSearchRequest) -> SourceSearchResult:
        started = time.perf_counter()
        requested_at = datetime.now(UTC).isoformat()
        request_id = uuid.uuid4().hex
        budget = _SearchBudget()
        outcomes = []

        primary = await self._search_engine(request, self.settings.primary_engine, budget)
        outcomes.append(primary)
        auth_failed = primary.error == "ZhipuSourceSearchAuthError"
        if (
            not primary.usable_candidates
            and not auth_failed
            and budget.calls < self.settings.max_search_calls
        ):
            fallback = await self._search_engine(request, self.settings.fallback_engine, budget)
            outcomes.append(fallback)

        usable = []
        navigation = []
        rejected = []
        for outcome in outcomes:
            for candidate in outcome.usable_candidates:
                if candidate.url not in {item.url for item in usable}:
                    usable.append(candidate)
            for candidate in outcome.navigation_candidates:
                if candidate.url not in {item.url for item in navigation}:
                    navigation.append(candidate)
            for candidate in outcome.rejected_candidates:
                if candidate.url not in {item.url for item in rejected}:
                    rejected.append(candidate)

        usable = usable[: self.settings.usable_result_limit]
        navigation = navigation[: self.settings.navigation_result_limit]
        rejected = rejected[: self.settings.navigation_result_limit]
        errors = [outcome.error for outcome in outcomes if outcome.error]
        if usable:
            status = SourceSearchStatus.SUCCESS
        elif navigation:
            status = SourceSearchStatus.NO_REGION_MATCHED_SOURCE
        elif len(errors) == len(outcomes):
            status = SourceSearchStatus.PROVIDER_ERROR
        else:
            status = SourceSearchStatus.NO_OFFICIAL_SOURCE

        attempts = [
            SourceSearchAttempt(
                engine=item.engine,
                requested_count=item.requested_count,
                raw_result_count=item.stats.raw_result_count,
                scanned_result_count=item.stats.scanned_result_count,
                usable_result_count=len(item.usable_candidates),
                navigation_result_count=len(item.navigation_candidates),
                rejected_result_count=len(item.rejected_candidates),
                requested_at=item.requested_at,
                latency_ms=item.latency_ms,
                local_request_id=item.local_request_id,
                provider_request_id=item.provider_request_id,
                attempts=item.attempts,
                retries=item.retries,
                network_executed=item.network_executed,
                cache_status=item.cache_status,
                estimated_cost_cny=item.estimated_cost_cny,
                http_status=item.http_status,
                error=item.error,
            )
            for item in outcomes
        ]
        cache_hits = sum(item.cache_status == SourceSearchCacheStatus.HIT for item in outcomes)
        if cache_hits == len(outcomes):
            cache_status = SourceSearchCacheStatus.HIT
        elif cache_hits:
            cache_status = SourceSearchCacheStatus.MIXED
        else:
            cache_status = SourceSearchCacheStatus.MISS
        return SourceSearchResult(
            provider=self.name,
            provider_version=self.version,
            engine=" -> ".join(item.engine for item in outcomes),
            status=status,
            search_executed=bool(outcomes),
            network_executed=any(item.network_executed for item in outcomes),
            requested_count=request.max_results,
            raw_result_count=sum(item.stats.raw_result_count for item in outcomes),
            scanned_result_count=sum(item.stats.scanned_result_count for item in outcomes),
            usable_result_count=len(usable),
            usable_candidates=usable,
            navigation_candidates=navigation,
            rejected_candidates=rejected,
            attempts=attempts,
            requested_at=requested_at,
            latency_ms=(time.perf_counter() - started) * 1000,
            request_id=request_id,
            retries=sum(item.retries for item in outcomes),
            cache_status=cache_status,
            degraded=status != SourceSearchStatus.SUCCESS or len(outcomes) > 1,
            error=(";".join(errors) if errors and not usable else None),
            estimated_cost_cny=round(sum(item.estimated_cost_cny for item in outcomes), 8),
            trigger_reason=request.trigger_reason,
        )
