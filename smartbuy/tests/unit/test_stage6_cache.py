"""Safety and invalidation contract for the opt-in Stage 6 cache."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from smartbuy.cache import (
    CacheKeyMaterial,
    CacheNamespace,
    CachedBailianProvider,
    SafeCache,
    SafeCachePolicy,
)


def material(**changes):
    values = {
        "operation": "vector_recall",
        "model": "text-embedding-v4",
        "model_version": "stage6",
        "embedding_dimensions": 1024,
        "data_version": "monitor-cn-2026-08-26-v1",
        "index_version": "monitor-fact-card-h2-v1",
        "normalized_query": "public fixture",
        "top_k": 5,
        "reranker_instruct": "rank relevant facts",
        "constraint_semantic_fingerprint": "constraint-v1",
        "region": "CN",
        "as_of": "2026-08-27T00:00:00Z",
    }
    values.update(changes)
    return CacheKeyMaterial(**values)


def test_cache_is_opt_in_and_bypasses_sensitive_dynamic_or_failed_results(tmp_path):
    cache = SafeCache(tmp_path / "cache.sqlite")
    key = material()
    assert cache.put(key, {"value": 1}) is False
    assert cache.put(key, {"value": 1}, public_evaluation=True, sensitive=True) is False
    assert cache.put(key, {"value": 1}, public_evaluation=True, dynamic=True) is False
    assert cache.put(key, {"value": 1}, public_evaluation=True, success=False) is False
    assert cache.get(key, public_evaluation=True) is None
    assert cache.stats()["bypasses"] == 4


def test_cache_key_hashes_text_and_invalidates_on_every_semantic_namespace_change(tmp_path):
    cache = SafeCache(tmp_path / "cache.sqlite")
    base = material()
    assert "public fixture" not in base.digest()
    assert cache.put(base, {"value": 1}, public_evaluation=True)
    assert cache.get(base, public_evaluation=True) == {"value": 1}
    changes = {
        "model": "another-model",
        "model_version": "stage7",
        "embedding_dimensions": 768,
        "data_version": "data-v2",
        "index_version": "index-v2",
        "normalized_query": "another query",
        "top_k": 10,
        "reranker_instruct": "different instruct",
        "constraint_semantic_fingerprint": "constraint-v2",
        "region": "US",
        "as_of": "2026-08-28T00:00:00Z",
    }
    for field, value in changes.items():
        assert cache.get(material(**{field: value}), public_evaluation=True) is None


def test_ttl_capacity_corruption_and_manual_clear(tmp_path):
    cache = SafeCache(
        tmp_path / "cache.sqlite",
        policy=SafeCachePolicy(ttl_seconds=60, max_entries=2),
    )
    first = material(normalized_query="one")
    second = material(normalized_query="two")
    third = material(normalized_query="three")
    for key in (first, second, third):
        assert cache.put(key, {"key": key.digest()}, public_evaluation=True)
    assert cache.get(first, public_evaluation=True) is None
    assert cache.get(third, public_evaluation=True) is not None

    with sqlite3.connect(cache.path) as connection:
        connection.execute(
            "UPDATE cache_entries SET payload_json=? WHERE cache_key=?",
            ('{"tampered":true}', third.digest()),
        )
    assert cache.get(third, public_evaluation=True) is None
    assert cache.stats()["corruptions"] == 1

    assert cache.put(second, {"value": 2}, public_evaluation=True)
    with sqlite3.connect(cache.path) as connection:
        connection.execute(
            "UPDATE cache_entries SET expires_at=0 WHERE cache_key=?", (second.digest(),)
        )
    assert cache.get(second, public_evaluation=True) is None
    assert cache.clear() >= 0


class _ChatProvider:
    def __init__(self):
        self.settings = SimpleNamespace(
            embedding_model="text-embedding-v4", reranker_model="qwen3-rerank"
        )
        self.ledger = SimpleNamespace()
        self.chat_calls = 0

    async def chat(self, *args, **kwargs):
        self.chat_calls += 1
        return SimpleNamespace(data={"ok": True})

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_free_text_chat_is_never_cached(tmp_path):
    provider = _ChatProvider()
    cached = CachedBailianProvider(
        provider,
        SafeCache(tmp_path / "cache.sqlite"),
        CacheNamespace("data", "index", "model", 1024, "CN", "2026-08-27"),
    )
    await cached.chat([{"role": "user", "content": "private text"}])
    await cached.chat([{"role": "user", "content": "private text"}])
    assert provider.chat_calls == 2
    assert cached.cache.stats()["writes"] == 0
