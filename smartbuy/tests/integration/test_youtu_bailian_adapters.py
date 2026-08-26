from __future__ import annotations

import logging
import os
from types import SimpleNamespace

import httpx
import pytest

# Youtu-RAG resolves this non-secret model selector during package import.
os.environ.setdefault("UTU_LLM_MODEL", "qwen-plus")
os.environ.setdefault("UTU_LLM_TYPE", "chat.completions")

from utu.agents import simple_agent as simple_agent_module
from utu.agents.simple_agent import SimpleAgent
from utu.config import ToolkitConfig
from utu.rag.base import Chunk, RetrievalResult
from utu.rag.embeddings.openai_embedder import OpenAIEmbedder
from utu.rag.rerankers.openai_reranker import OpenAIReranker


class _FakeEmbeddings:
    def __init__(self, dimensions: int = 1024) -> None:
        self.calls: list[dict] = []
        self.dimensions = dimensions

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        inputs = kwargs["input"] if isinstance(kwargs["input"], list) else [kwargs["input"]]
        return SimpleNamespace(
            data=[SimpleNamespace(index=index, embedding=[0.0] * self.dimensions) for index, _ in enumerate(inputs)]
        )


@pytest.mark.asyncio
async def test_youtu_embedder_passes_dimensions_without_model_id() -> None:
    embedder = OpenAIEmbedder(
        model="text-embedding-v4",
        api_key="placeholder",
        base_url="https://ws-placeholder.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        dimensions=1024,
        batch_delay=0,
    )
    fake = _FakeEmbeddings()
    embedder.client = SimpleNamespace(embeddings=fake)

    vectors = await embedder.embed_texts(["one", "two"])

    assert len(vectors) == 2
    assert fake.calls[0]["dimensions"] == 1024
    assert "model_id" not in fake.calls[0]


@pytest.mark.asyncio
async def test_youtu_embedder_rejects_wrong_dimensions() -> None:
    embedder = OpenAIEmbedder(model="text-embedding-v4", api_key="placeholder", dimensions=1024)
    embedder.client = SimpleNamespace(embeddings=_FakeEmbeddings(dimensions=3))

    with pytest.raises(ValueError, match="dimension mismatch"):
        await embedder.embed_query("one")


@pytest.mark.asyncio
async def test_youtu_reranker_preserves_exact_plural_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_urls: list[str] = []

    async def fake_post(self, url, **kwargs):
        requested_urls.append(url)
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"results": [{"index": 1, "relevance_score": 0.9}]},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    endpoint = "https://ws-placeholder.cn-beijing.maas.aliyuncs.com/compatible-api/v1/reranks"
    reranker = OpenAIReranker(api_key="placeholder", model="qwen3-rerank", base_url=endpoint)
    results = [
        RetrievalResult(Chunk("a", "d", "first", 0), 0.8, 1),
        RetrievalResult(Chunk("b", "d", "second", 1), 0.7, 2),
    ]

    reranked = await reranker.rerank("query", results, top_k=1)

    assert requested_urls == [endpoint]
    assert reranked[0].chunk.id == "b"
    assert reranker.last_degraded is False


@pytest.mark.asyncio
async def test_youtu_reranker_marks_vector_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(401, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    reranker = OpenAIReranker(
        api_key="placeholder",
        model="qwen3-rerank",
        base_url="https://example.invalid/reranks",
    )
    original = [RetrievalResult(Chunk("a", "d", "first", 0), 0.8, 1)]

    returned = await reranker.rerank("query", original, top_k=1)

    assert returned == original
    assert reranker.last_degraded is True


@pytest.mark.asyncio
async def test_toolkit_loading_log_does_not_contain_resolved_secret(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class DummyToolkit:
        def __init__(self, config) -> None:
            self.config = config

    monkeypatch.setitem(simple_agent_module.TOOLKIT_MAP, "safe_log_test", DummyToolkit)
    agent = SimpleAgent.__new__(SimpleAgent)
    agent._toolkits = {}
    config = ToolkitConfig(
        mode="builtin",
        name="safe_log_test",
        config={"api_key": "credential-that-must-not-be-logged", "model": "test-model"},
    )

    with caplog.at_level(logging.INFO):
        await agent._load_builtin_toolkit(config)

    assert "credential-that-must-not-be-logged" not in caplog.text
    assert "safe_log_test" in caplog.text
