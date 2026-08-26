from __future__ import annotations

import json

import httpx
import pytest

from smartbuy.config import BailianSettings
from smartbuy.observability import UsageLedger
from smartbuy.providers import (
    BailianAuthError,
    BailianError,
    BailianProvider,
    BailianResponseError,
    RetryPolicy,
)


@pytest.fixture
def settings() -> BailianSettings:
    return BailianSettings(api_key="placeholder-credential", workspace_id="ws-placeholder123")


def make_provider(
    settings: BailianSettings,
    handler,
    *,
    retries: int = 2,
) -> tuple[BailianProvider, UsageLedger]:
    ledger = UsageLedger()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def no_sleep(_: float) -> None:
        return None

    provider = BailianProvider(
        settings,
        client=client,
        retry_policy=RetryPolicy(max_retries=retries, jitter_seconds=0),
        ledger=ledger,
        sleep=no_sleep,
    )
    return provider, ledger


@pytest.mark.asyncio
async def test_chat_and_tool_call_contract(settings: BailianSettings) -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "lookup", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            },
        )

    provider, ledger = make_provider(settings, handler)
    result = await provider.chat(
        [{"role": "user", "content": "test"}],
        tools=[{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}],
    )
    await provider._client.aclose()

    assert result.data["tool_calls"][0]["function"]["name"] == "lookup"
    assert requests[0]["model"] == "qwen-plus"
    assert requests[0]["enable_thinking"] is False
    assert ledger.summary()["input_tokens"] == 7


@pytest.mark.asyncio
async def test_streaming_collects_final_usage(settings: BailianSettings) -> None:
    stream = "\n".join(
        [
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":1,"total_tokens":5}}',
            "data: [DONE]",
        ]
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})

    provider, ledger = make_provider(settings, handler)
    chunks = [chunk async for chunk in provider.chat_stream([{"role": "user", "content": "test"}])]
    await provider._client.aclose()

    assert len(chunks) == 2
    assert ledger.summary()["output_tokens"] == 1


@pytest.mark.asyncio
async def test_embedding_enforces_count_order_and_dimensions(settings: BailianSettings) -> None:
    vector = [0.0] * 1024

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["dimensions"] == 1024
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": vector},
                    {"index": 0, "embedding": vector},
                ],
                "usage": {"prompt_tokens": 5, "total_tokens": 5},
            },
        )

    provider, _ = make_provider(settings, handler)
    result = await provider.embed(["a", "b"])
    await provider._client.aclose()

    assert len(result.data) == 2
    assert all(len(item) == 1024 for item in result.data)


@pytest.mark.asyncio
async def test_embedding_rejects_wrong_dimensions(settings: BailianSettings) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0] * 3}]})

    provider, _ = make_provider(settings, handler)
    with pytest.raises(BailianResponseError, match="dimension"):
        await provider.embed(["a"])
    await provider._client.aclose()


@pytest.mark.asyncio
async def test_401_is_not_retried(settings: BailianSettings) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401)

    provider, _ = make_provider(settings, handler)
    with pytest.raises(BailianAuthError):
        await provider.chat([{"role": "user", "content": "test"}])
    await provider._client.aclose()

    assert attempts == 1


@pytest.mark.asyncio
async def test_429_retries_are_bounded(settings: BailianSettings) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(429)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )

    provider, _ = make_provider(settings, handler)
    result = await provider.chat([{"role": "user", "content": "test"}])
    await provider._client.aclose()

    assert result.attempts == 3
    assert attempts == 3


@pytest.mark.asyncio
async def test_timeout_retries_are_bounded(settings: BailianSettings) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("simulated", request=request)

    provider, _ = make_provider(settings, handler, retries=1)
    with pytest.raises(BailianError, match="2 attempt"):
        await provider.chat([{"role": "user", "content": "test"}])
    await provider._client.aclose()

    assert attempts == 2


@pytest.mark.asyncio
async def test_rerank_uses_exact_endpoint_and_falls_back(settings: BailianSettings) -> None:
    urls: list[str] = []

    def success_handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.2},
                ],
                "usage": {"input_tokens": 6, "total_tokens": 6},
            },
        )

    provider, _ = make_provider(settings, success_handler)
    result = await provider.rerank("query", ["first", "second"], top_n=2)
    await provider._client.aclose()
    assert urls == [settings.rerank_url]
    assert result.data[0]["index"] == 1

    def failure_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    fallback_provider, ledger = make_provider(settings, failure_handler, retries=0)
    fallback = await fallback_provider.rerank_or_fallback(
        "query", ["first", "second"], top_n=2, vector_scores=[0.8, 0.7]
    )
    await fallback_provider._client.aclose()

    assert fallback.degraded is True
    assert [item["index"] for item in fallback.data] == [0, 1]
    assert ledger.summary()["degraded_calls"] == 1
