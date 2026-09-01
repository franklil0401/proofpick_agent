"""In-process TTL cache for complete, public source metadata only."""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Callable

from smartbuy.source_search.models import SourceEngineOutcome, SourceSearchRequest


@dataclass(frozen=True)
class SourceSearchCachePolicy:
    ttl_seconds: int = 900
    max_entries: int = 256

    def __post_init__(self) -> None:
        if self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if not 1 <= self.max_entries <= 10_000:
            raise ValueError("max_entries must be between 1 and 10000")


class TTLSourceSearchCache:
    def __init__(
        self,
        policy: SourceSearchCachePolicy | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.policy = policy or SourceSearchCachePolicy()
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, dict[str, object]]] = OrderedDict()
        self._lock = Lock()
        self._stats = {"hits": 0, "misses": 0, "writes": 0, "bypasses": 0}

    @staticmethod
    def key(
        request: SourceSearchRequest,
        *,
        provider: str,
        provider_version: str,
        engine: str,
    ) -> str:
        payload = {
            "provider": provider,
            "provider_version": provider_version,
            "engine": engine,
            "query": request.query.strip().casefold(),
            "product_category": request.product_category,
            "target_model": request.target_model.casefold(),
            "target_fields": sorted(request.target_fields),
            "region": request.region,
            "freshness": request.freshness,
            "allowed_domains": sorted(request.allowed_domains),
            "max_results": request.max_results,
        }
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def get(self, cache_key: str) -> SourceEngineOutcome | None:
        now = self._clock()
        with self._lock:
            entry = self._entries.get(cache_key)
            if entry is None:
                self._stats["misses"] += 1
                return None
            expires_at, payload = entry
            if expires_at <= now:
                self._entries.pop(cache_key, None)
                self._stats["misses"] += 1
                return None
            self._entries.move_to_end(cache_key)
            self._stats["hits"] += 1
            return SourceEngineOutcome.model_validate(payload)

    def put(self, cache_key: str, outcome: SourceEngineOutcome) -> bool:
        if not outcome.complete_and_cacheable:
            self._stats["bypasses"] += 1
            return False
        payload = outcome.model_dump(mode="json")
        with self._lock:
            self._entries[cache_key] = (self._clock() + self.policy.ttl_seconds, payload)
            self._entries.move_to_end(cache_key)
            while len(self._entries) > self.policy.max_entries:
                self._entries.popitem(last=False)
            self._stats["writes"] += 1
        return True

    def clear(self) -> int:
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
        return count

    def stats(self) -> dict[str, int | float]:
        with self._lock:
            snapshot = dict(self._stats)
        total = snapshot["hits"] + snapshot["misses"]
        snapshot["hit_rate"] = round(snapshot["hits"] / total, 6) if total else 0.0
        return snapshot
