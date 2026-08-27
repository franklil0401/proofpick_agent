"""KB Search reranker fallback contract."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from smartbuy.config import BailianSettings
from smartbuy.tools import KBSearchTool


class FakeStore:
    async def count(self):
        return 2

    async def search(self, _vector, top_k):
        assert top_k == 2
        metadata = {
            "model_id": "dell-u2723qe-cn", "brand": "Dell", "region_version": "CN",
            "source_id": "src-1", "source_type": "official", "source_url": "https://example.com",
            "section_page": "接口", "accessed_at": "2026-08-26",
        }
        return [
            (SimpleNamespace(id="c1", content="90W USB-C", metadata=metadata), 0.9),
            (SimpleNamespace(id="c2", content="4K", metadata=metadata), 0.8),
        ]


class FakeProvider:
    async def embed(self, _texts):
        return SimpleNamespace(data=[[0.0] * 1024])

    async def rerank_or_fallback(self, _query, _documents, *, top_n, vector_scores):
        assert top_n == 2
        return SimpleNamespace(
            data=[{"index": 0, "relevance_score": vector_scores[0]}, {"index": 1, "relevance_score": vector_scores[1]}],
            degraded=True,
        )


@pytest.mark.asyncio
async def test_reranker_failure_preserves_vector_results():
    settings = BailianSettings(api_key="test-only", workspace_id="ws-test")
    tool = KBSearchTool(settings, FakeProvider(), store=FakeStore())
    result = await tool.invoke(
        {"query": "90W", "model_ids": ["dell-u2723qe-cn"], "required_fields": ["usb_c_power_delivery_w"]}
    )
    assert result.status == "degraded"
    assert result.data["reranker_degraded"] is True
    assert [hit["chunk_id"] for hit in result.data["hits"]] == ["c1", "c2"]
