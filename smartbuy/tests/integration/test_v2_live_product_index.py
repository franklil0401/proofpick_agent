"""Offline transactional Chroma index tests for V2 Product Packs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smartbuy.config import BailianSettings
from smartbuy.product_packs import (
    ProductIndexManager,
    ProductPackManager,
    ProductPackRuntimeSettings,
    ProductPackValidationError,
    resolve_product_snapshot,
)
from smartbuy.providers.bailian import ProviderResult
from smartbuy.tools import KBSearchTool


EXAMPLE = (
    Path(__file__).resolve().parents[2]
    / "product_packs/examples/monitor-u2725qe-us/pack.json"
)
DATA_VERSION = "monitor-multi-region-2026-08-31-v2"


def _vector(text: str) -> list[float]:
    value = text.casefold()
    vector = [0.0] * 1024
    if "u2725qe" in value or "210-bqhr" in value:
        vector[0] = 1.0
    elif "u2723qe" in value:
        vector[1] = 1.0
    else:
        vector[2 + sum(value.encode("utf-8")) % 100] = 1.0
    return vector


class FakeLiveProvider:
    def __init__(self, *, dimensions: int = 1024) -> None:
        self.dimensions = dimensions
        self.embedding_calls = 0

    async def embed(self, texts):
        self.embedding_calls += 1
        vectors = [_vector(text)[: self.dimensions] for text in texts]
        return ProviderResult(
            data=vectors,
            attempts=1,
            latency_ms=1.0,
            usage={
                "input_tokens": sum(max(1, len(text) // 4) for text in texts),
                "output_tokens": 0,
                "total_tokens": sum(max(1, len(text) // 4) for text in texts),
            },
        )

    async def rerank_or_fallback(
        self, _query, documents, *, top_n, vector_scores=None
    ):
        scores = list(vector_scores or [0.0] * len(documents))
        ranked = sorted(range(len(documents)), key=lambda item: scores[item], reverse=True)
        return ProviderResult(
            data=[
                {"index": index, "relevance_score": scores[index]}
                for index in ranked[:top_n]
            ],
            attempts=0,
            latency_ms=0.0,
            usage={},
        )


class CountMismatchProvider(FakeLiveProvider):
    async def embed(self, texts):
        result = await super().embed(texts)
        return ProviderResult(
            data=result.data[:-1],
            attempts=result.attempts,
            latency_ms=result.latency_ms,
            usage=result.usage,
        )


class FailedEmbeddingProvider(FakeLiveProvider):
    async def embed(self, texts):
        raise RuntimeError("controlled embedding outage")


def _published_data(tmp_path: Path):
    manager = ProductPackManager(tmp_path / "runtime")
    staged = manager.stage(EXAMPLE)
    return manager, manager.publish(staged.data_version)


@pytest.mark.asyncio
async def test_live_index_build_activate_query_and_runtime_resolution(tmp_path):
    manager, data = _published_data(tmp_path)
    index_manager = ProductIndexManager(tmp_path / "runtime")
    provider = FakeLiveProvider()
    index = await index_manager.build(
        DATA_VERSION,
        "monitor-live-index-r1",
        provider,
        batch_size=10,
    )
    assert provider.embedding_calls == 7
    assert index.manifest["document_count"] == 65
    assert index.manifest["chunk_count"] == 65
    assert index.manifest["embedding_dimensions"] == 1024
    assert index.manifest["status"] == "completed"
    index_manager.activate(index.index_version)
    resolved = resolve_product_snapshot(
        ProductPackRuntimeSettings(enabled=True, runtime_root=tmp_path / "runtime")
    )
    assert resolved is not None
    assert resolved.data_version == data.data_version
    assert resolved.index.index_version == index.index_version

    result = await KBSearchTool(
        BailianSettings(api_key="test-only", workspace_id="ws-test"),
        provider,
        index_dir=resolved.index_dir,
        evidence_path=resolved.evidence_path,
        sources_path=resolved.sources_path,
        collection_name=resolved.collection_name,
    ).invoke(
        {
            "query": "210-BQHR U2725QE 140W",
            "model_ids": ["dell-u2725qe-us"],
            "required_fields": ["usb_c_power_delivery_w"],
            "reason": "离线真实 Chroma 契约验证",
        }
    )
    assert result.status == "success"
    assert result.data["hits"]
    assert {item["model_id"] for item in result.data["hits"]} == {
        "dell-u2725qe-us"
    }
    assert {item["region"] for item in result.data["hits"]} == {"US"}
    assert {item["variant_key"] for item in result.data["hits"]} == {
        "u2725qe-us-210-bqhr"
    }
    assert any(item["evidence_bindings"] for item in result.data["hits"])
    assert manager.current().data_version == DATA_VERSION


@pytest.mark.asyncio
async def test_index_failure_preserves_pointer_and_rollback_restores_trusted_version(
    tmp_path,
):
    _manager, _data = _published_data(tmp_path)
    index_manager = ProductIndexManager(tmp_path / "runtime")
    provider = FakeLiveProvider()
    first = await index_manager.build(DATA_VERSION, "monitor-live-index-r1", provider)
    second = await index_manager.build(DATA_VERSION, "monitor-live-index-r2", provider)
    index_manager.activate(first.index_version)
    index_manager.activate(second.index_version)
    restored = index_manager.rollback(first.index_version)
    assert restored.index_version == first.index_version
    assert index_manager.current().manifest_hash == first.manifest_hash

    with pytest.raises(ProductPackValidationError, match="dimension"):
        await index_manager.build(
            DATA_VERSION,
            "monitor-live-index-bad-dimension",
            FakeLiveProvider(dimensions=8),
        )
    assert index_manager.current().index_version == first.index_version
    assert not (index_manager.indices_root / "monitor-live-index-bad-dimension").exists()

    with pytest.raises(ProductPackValidationError, match="count"):
        await index_manager.build(
            DATA_VERSION,
            "monitor-live-index-bad-count",
            CountMismatchProvider(),
        )
    assert index_manager.current().index_version == first.index_version

    with pytest.raises(RuntimeError, match="controlled embedding outage"):
        await index_manager.build(
            DATA_VERSION,
            "monitor-live-index-provider-failure",
            FailedEmbeddingProvider(),
        )
    assert index_manager.current().index_version == first.index_version

    second_manifest = second.root / "index_manifest.json"
    payload = json.loads(second_manifest.read_text(encoding="utf-8"))
    payload["document_count"] -= 1
    second_manifest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ProductPackValidationError, match="data manifest"):
        index_manager.activate(second.index_version)
    assert index_manager.current().index_version == first.index_version


def test_enabled_documents_ready_data_without_live_index_fails_closed(tmp_path):
    _manager, _data = _published_data(tmp_path)
    with pytest.raises(ProductPackValidationError, match="index pointer"):
        resolve_product_snapshot(
            ProductPackRuntimeSettings(enabled=True, runtime_root=tmp_path / "runtime")
        )
