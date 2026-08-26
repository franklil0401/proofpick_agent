"""Bounded, sanitized Model Studio provider for Stage 2 verification and reuse."""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Sequence

import httpx

from smartbuy.config import BailianSettings
from smartbuy.observability import UsageLedger, UsageRecord


class BailianError(RuntimeError):
    """Base provider error that never includes response bodies or credentials."""


class BailianHTTPError(BailianError):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"Model Studio request failed with HTTP {status_code}")


class BailianAuthError(BailianHTTPError):
    """Non-retryable authentication or authorization failure."""


class BailianResponseError(BailianError):
    """Raised when a successful response violates the expected contract."""


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 2
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 2.0
    jitter_seconds: float = 0.05

    def __post_init__(self) -> None:
        if not 0 <= self.max_retries <= 4:
            raise ValueError("max_retries must be between 0 and 4")


@dataclass(frozen=True)
class ProviderResult:
    data: Any
    attempts: int
    latency_ms: float
    usage: dict[str, int]
    degraded: bool = False


class BailianProvider:
    """Call qwen-plus, text-embedding-v4 and qwen3-rerank through one safe boundary."""

    _RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        settings: BailianSettings,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
        retry_policy: RetryPolicy | None = None,
        ledger: UsageLedger | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.retry_policy = retry_policy or RetryPolicy()
        self.ledger = ledger or UsageLedger()
        self._client_owned = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._sleep = sleep

    async def __aenter__(self) -> "BailianProvider":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client_owned:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

    async def _delay(self, attempt: int) -> None:
        delay = min(
            self.retry_policy.base_delay_seconds * (2 ** max(0, attempt - 1)),
            self.retry_policy.max_delay_seconds,
        )
        delay += random.uniform(0.0, self.retry_policy.jitter_seconds)
        await self._sleep(delay)

    async def _post_json(self, url: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int, float]:
        started = time.perf_counter()
        total_attempts = self.retry_policy.max_retries + 1
        for attempt in range(1, total_attempts + 1):
            try:
                response = await self._client.post(url, json=payload, headers=self._headers())
                if response.status_code in (401, 403):
                    raise BailianAuthError(response.status_code)
                if response.status_code >= 400:
                    error = BailianHTTPError(response.status_code)
                    if response.status_code not in self._RETRYABLE_STATUS or attempt == total_attempts:
                        raise error
                else:
                    try:
                        body = response.json()
                    except (ValueError, json.JSONDecodeError) as exc:
                        raise BailianResponseError("Model Studio returned invalid JSON") from exc
                    return body, attempt, (time.perf_counter() - started) * 1000
            except BailianAuthError:
                raise
            except BailianHTTPError:
                if attempt == total_attempts:
                    raise
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt == total_attempts:
                    raise BailianError(f"Model Studio transport failed after {attempt} attempt(s)") from exc
            if attempt < total_attempts:
                await self._delay(attempt)
        raise AssertionError("bounded retry loop exited unexpectedly")

    @staticmethod
    def _usage(body: dict[str, Any]) -> dict[str, int]:
        usage = body.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens) or 0),
        }

    def _record(
        self,
        *,
        operation: str,
        model: str,
        success: bool,
        attempts: int,
        latency_ms: float,
        usage: dict[str, int] | None = None,
        item_count: int = 0,
        degraded: bool = False,
        status_code: int | None = None,
    ) -> None:
        usage = usage or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        self.ledger.add(
            UsageRecord(
                operation=operation,
                model=model,
                success=success,
                attempts=attempts,
                latency_ms=round(latency_ms, 3),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                item_count=item_count,
                estimated_cost_cny=UsageLedger.estimate_cost(model, input_tokens, output_tokens),
                degraded=degraded,
                status_code=status_code,
            )
        )

    async def chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> ProviderResult:
        payload: dict[str, Any] = {
            "model": self.settings.chat_model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "enable_thinking": False,
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = tool_choice or "auto"
        started = time.perf_counter()
        try:
            body, attempts, latency_ms = await self._post_json(self.settings.chat_url, payload)
            choices = body.get("choices") or []
            if not choices or not isinstance(choices[0].get("message"), dict):
                raise BailianResponseError("Chat response contains no message")
            usage = self._usage(body)
            self._record(
                operation="chat_tool" if tools else "chat",
                model=self.settings.chat_model,
                success=True,
                attempts=attempts,
                latency_ms=latency_ms,
                usage=usage,
            )
            return ProviderResult(choices[0]["message"], attempts, latency_ms, usage)
        except BailianError as exc:
            self._record(
                operation="chat_tool" if tools else "chat",
                model=self.settings.chat_model,
                success=False,
                attempts=1,
                latency_ms=(time.perf_counter() - started) * 1000,
                status_code=getattr(exc, "status_code", None),
            )
            raise

    async def chat_stream(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> AsyncIterator[dict[str, Any]]:
        payload = {
            "model": self.settings.chat_model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "enable_thinking": False,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        started = time.perf_counter()
        attempts = 1
        usage: dict[str, int] = {}
        try:
            async with self._client.stream(
                "POST", self.settings.chat_url, json=payload, headers=self._headers()
            ) as response:
                if response.status_code in (401, 403):
                    raise BailianAuthError(response.status_code)
                if response.status_code >= 400:
                    raise BailianHTTPError(response.status_code)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise BailianResponseError("Streaming response contains invalid JSON") from exc
                    if chunk.get("usage"):
                        usage = self._usage(chunk)
                    yield chunk
            self._record(
                operation="chat_stream",
                model=self.settings.chat_model,
                success=True,
                attempts=attempts,
                latency_ms=(time.perf_counter() - started) * 1000,
                usage=usage,
            )
        except BailianError as exc:
            self._record(
                operation="chat_stream",
                model=self.settings.chat_model,
                success=False,
                attempts=attempts,
                latency_ms=(time.perf_counter() - started) * 1000,
                status_code=getattr(exc, "status_code", None),
            )
            raise

    async def embed(self, texts: Sequence[str]) -> ProviderResult:
        if not texts:
            return ProviderResult([], 0, 0.0, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
        payload = {
            "model": self.settings.embedding_model,
            "input": list(texts),
            "dimensions": self.settings.embedding_dimensions,
            "encoding_format": "float",
        }
        body, attempts, latency_ms = await self._post_json(self.settings.embedding_url, payload)
        items = body.get("data")
        if not isinstance(items, list) or len(items) != len(texts):
            raise BailianResponseError("Embedding count does not match input count")
        try:
            ordered = sorted(items, key=lambda item: int(item["index"]))
            vectors = [item["embedding"] for item in ordered]
        except (KeyError, TypeError, ValueError) as exc:
            raise BailianResponseError("Embedding response has invalid indices or vectors") from exc
        if [int(item["index"]) for item in ordered] != list(range(len(texts))):
            raise BailianResponseError("Embedding response indices are incomplete")
        if any(len(vector) != self.settings.embedding_dimensions for vector in vectors):
            raise BailianResponseError("Embedding response dimension is not 1024")
        usage = self._usage(body)
        self._record(
            operation="embedding",
            model=self.settings.embedding_model,
            success=True,
            attempts=attempts,
            latency_ms=latency_ms,
            usage=usage,
            item_count=len(vectors),
        )
        return ProviderResult(vectors, attempts, latency_ms, usage)

    async def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int,
        instruct: str | None = None,
    ) -> ProviderResult:
        if not documents:
            return ProviderResult([], 0, 0.0, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
        if top_n < 1:
            raise ValueError("top_n must be positive")
        payload: dict[str, Any] = {
            "model": self.settings.reranker_model,
            "query": query,
            "documents": list(documents),
            "top_n": min(top_n, len(documents)),
        }
        if instruct:
            payload["instruct"] = instruct
        body, attempts, latency_ms = await self._post_json(self.settings.rerank_url, payload)
        items = body.get("results")
        if not isinstance(items, list):
            raise BailianResponseError("Rerank response contains no top-level results")
        normalized = []
        seen = set()
        for item in items:
            try:
                index = int(item["index"])
                score = float(item["relevance_score"])
            except (KeyError, TypeError, ValueError) as exc:
                raise BailianResponseError("Rerank response item is invalid") from exc
            if index < 0 or index >= len(documents) or index in seen:
                raise BailianResponseError("Rerank response index is invalid or duplicated")
            seen.add(index)
            normalized.append({"index": index, "relevance_score": score})
        usage = self._usage(body)
        if not usage["input_tokens"] and not usage["output_tokens"] and usage["total_tokens"]:
            # Reranking is input-only; the compatible endpoint may expose only total_tokens.
            usage["input_tokens"] = usage["total_tokens"]
        self._record(
            operation="rerank",
            model=self.settings.reranker_model,
            success=True,
            attempts=attempts,
            latency_ms=latency_ms,
            usage=usage,
            item_count=len(documents),
        )
        return ProviderResult(normalized, attempts, latency_ms, usage)

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
        except BailianError as exc:
            limit = min(top_n, len(documents))
            scores = list(vector_scores or [0.0] * len(documents))
            fallback = [
                {"index": index, "relevance_score": float(scores[index])}
                for index in range(limit)
            ]
            self._record(
                operation="rerank_fallback",
                model=self.settings.reranker_model,
                success=True,
                attempts=0,
                latency_ms=0.0,
                item_count=len(documents),
                degraded=True,
                status_code=getattr(exc, "status_code", None),
            )
            return ProviderResult(fallback, 0, 0.0, {}, degraded=True)
