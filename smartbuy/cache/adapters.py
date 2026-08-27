"""Opt-in cache adapters for public, versioned Stage 6 evaluation data."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Sequence

from smartbuy.cache.safe_cache import CacheKeyMaterial, SafeCache
from smartbuy.providers.bailian import ProviderResult
from smartbuy.tools import ToolResult


@dataclass(frozen=True)
class CacheNamespace:
    data_version: str
    index_version: str
    model_version: str
    embedding_dimensions: int
    region: str
    as_of: str
    reranker_instruct: str = ""


def _normalized(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class CachedBailianProvider:
    """Cache only embeddings and successful reranks; chat is never cached."""

    def __init__(self, provider: Any, cache: SafeCache, namespace: CacheNamespace) -> None:
        self.provider = provider
        self.cache = cache
        self.namespace = namespace
        self.settings = provider.settings
        self.ledger = provider.ledger
        self.cache_events: list[dict[str, Any]] = []

    async def aclose(self) -> None:
        await self.provider.aclose()

    async def chat(self, *args: Any, **kwargs: Any) -> ProviderResult:
        return await self.provider.chat(*args, **kwargs)

    def _material(
        self,
        *,
        operation: str,
        model: str,
        query: Any,
        top_k: int | None = None,
        instruct: str | None = None,
    ) -> CacheKeyMaterial:
        return CacheKeyMaterial(
            operation=operation,
            model=model,
            model_version=self.namespace.model_version,
            embedding_dimensions=self.namespace.embedding_dimensions,
            data_version=self.namespace.data_version,
            index_version=self.namespace.index_version,
            normalized_query=_normalized(query),
            top_k=top_k,
            reranker_instruct=instruct or self.namespace.reranker_instruct,
            constraint_semantic_fingerprint=None,
            region=self.namespace.region,
            as_of=self.namespace.as_of,
        )

    def _event(self, operation: str, hit: bool, latency_ms: float) -> None:
        self.cache_events.append(
            {"operation": operation, "cache_hit": hit, "latency_ms": round(latency_ms, 3)}
        )

    async def embed(self, texts: Sequence[str]) -> ProviderResult:
        material = self._material(
            operation="query_embedding",
            model=self.settings.embedding_model,
            query=list(texts),
        )
        started = time.perf_counter()
        cached = self.cache.get(material, public_evaluation=True)
        if cached is not None:
            latency = (time.perf_counter() - started) * 1000
            self._event("query_embedding", True, latency)
            return ProviderResult(cached, 0, latency, {}, degraded=False)
        result = await self.provider.embed(texts)
        self.cache.put(
            material,
            result.data,
            public_evaluation=True,
            complete=len(result.data) == len(texts),
            success=not result.degraded,
        )
        self._event("query_embedding", False, (time.perf_counter() - started) * 1000)
        return result

    async def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int,
        instruct: str | None = None,
    ) -> ProviderResult:
        material = self._material(
            operation="rerank",
            model=self.settings.reranker_model,
            query={"query": query, "documents": list(documents)},
            top_k=top_n,
            instruct=instruct,
        )
        started = time.perf_counter()
        cached = self.cache.get(material, public_evaluation=True)
        if cached is not None:
            latency = (time.perf_counter() - started) * 1000
            self._event("rerank", True, latency)
            return ProviderResult(cached, 0, latency, {}, degraded=False)
        result = await self.provider.rerank(query, documents, top_n=top_n, instruct=instruct)
        self.cache.put(
            material,
            result.data,
            public_evaluation=True,
            complete=True,
            success=not result.degraded,
        )
        self._event("rerank", False, (time.perf_counter() - started) * 1000)
        return result

    async def rerank_or_fallback(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int,
        vector_scores: Sequence[float] | None = None,
    ) -> ProviderResult:
        try:
            return await self.rerank(query, documents, top_n=top_n)
        except Exception:
            # Reuse the provider's established bounded, auditable fallback path.
            return await self.provider.rerank_or_fallback(
                query,
                documents,
                top_n=top_n,
                vector_scores=vector_scores,
            )


class CachedReadOnlyTool:
    """Cache successful public KB or stable read-only SQL tool results."""

    def __init__(
        self,
        tool: Any,
        cache: SafeCache,
        namespace: CacheNamespace,
        *,
        operation: str,
        model: str,
    ) -> None:
        if operation not in {"vector_recall", "product_fact", "readonly_sql"}:
            raise ValueError("unsupported cached tool operation")
        self.tool = tool
        self.cache = cache
        self.namespace = namespace
        self.operation = operation
        self.model = model
        self.name = tool.name
        self.description = tool.description
        self.cache_events: list[dict[str, Any]] = []

    @property
    def schema(self) -> dict[str, Any]:
        return self.tool.schema

    @property
    def database_path(self) -> Any:
        return getattr(self.tool, "database_path", None)

    def _dynamic(self, arguments: dict[str, Any]) -> bool:
        encoded = _normalized(arguments).lower()
        return any(token in encoded for token in ("price_cny", "stock_status", "observed_at", "current_price"))

    async def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        material = CacheKeyMaterial(
            operation=self.operation,
            model=self.model,
            model_version=self.namespace.model_version,
            embedding_dimensions=self.namespace.embedding_dimensions,
            data_version=self.namespace.data_version,
            index_version=self.namespace.index_version,
            normalized_query=_normalized(arguments),
            top_k=getattr(self.tool, "result_top_k", None),
            reranker_instruct=self.namespace.reranker_instruct,
            constraint_semantic_fingerprint=arguments.get("constraint_semantic_fingerprint"),
            region=self.namespace.region,
            as_of=self.namespace.as_of,
        )
        dynamic = self._dynamic(arguments)
        started = time.perf_counter()
        cached = self.cache.get(material, public_evaluation=True, dynamic=dynamic)
        if cached is not None:
            latency = (time.perf_counter() - started) * 1000
            self.cache_events.append(
                {"operation": self.operation, "cache_hit": True, "latency_ms": round(latency, 3)}
            )
            return ToolResult.model_validate(cached)
        result = await self.tool.invoke(arguments)
        self.cache.put(
            material,
            result.model_dump(mode="json"),
            public_evaluation=True,
            dynamic=dynamic,
            complete=result.status in {"success", "degraded"},
            success=result.status == "success" and not result.degraded,
        )
        self.cache_events.append(
            {
                "operation": self.operation,
                "cache_hit": False,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        )
        return result
