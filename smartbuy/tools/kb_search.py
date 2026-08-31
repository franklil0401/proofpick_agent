"""Stage 4 knowledge-base tool: vector recall followed by bounded reranking."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from smartbuy.config import BailianSettings
from smartbuy.providers import BailianProvider
from smartbuy.retrieval.knowledge_base import DEFAULT_INDEX_DIR, INDEX_CONTRACT, youtu_environment
from smartbuy.tools.base import ToolResult


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = PROJECT_ROOT / "smartbuy/data/processed/evidence_records.jsonl"
DEFAULT_SOURCES_PATH = PROJECT_ROOT / "smartbuy/data/processed/source_records.jsonl"


class KBSearchTool:
    name = "kb_search"
    description = "检索官方资料与自制事实卡，返回带型号、地区、字段和 URL 的证据片段。"

    def __init__(
        self,
        settings: BailianSettings,
        provider: BailianProvider,
        *,
        index_dir: Path | str = DEFAULT_INDEX_DIR,
        store: Any | None = None,
        vector_top_k: int = 30,
        result_top_k: int = 8,
        evidence_path: Path | str = DEFAULT_EVIDENCE_PATH,
        sources_path: Path | str = DEFAULT_SOURCES_PATH,
        collection_name: str = INDEX_CONTRACT["collection_name"],
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.index_dir = Path(index_dir)
        self._store = store
        self.vector_top_k = vector_top_k
        self.result_top_k = result_top_k
        self.evidence_path = Path(evidence_path)
        self.sources_path = Path(sources_path)
        self.collection_name = collection_name
        self._evidence_index: dict[tuple[str, str], list[dict[str, Any]]] | None = None

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "maxLength": 500},
                        "model_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
                        "required_fields": {"type": "array", "items": {"type": "string"}, "maxItems": 15},
                        "reason": {"type": "string", "maxLength": 200},
                        "parent_step": {"type": ["integer", "null"]},
                    },
                    "required": ["query", "model_ids", "required_fields", "reason"],
                    "additionalProperties": False,
                },
            },
        }

    def _open_store(self) -> Any:
        with youtu_environment(self.settings):
            from utu.rag.config import VectorStoreConfig
            from utu.rag.storage.implementations.chroma_store import ChromaVectorStore

            return ChromaVectorStore(
                VectorStoreConfig(
                    collection_name=self.collection_name,
                    persist_directory=str(self.index_dir.resolve()),
                    distance_metric="cosine",
                )
            )

    async def _get_store(self) -> Any:
        if self._store is None:
            self._store = self._open_store()
        return self._store

    def _load_evidence_index(self) -> dict[tuple[str, str], list[dict[str, Any]]]:
        if self._evidence_index is not None:
            return self._evidence_index
        source_urls: dict[str, str] = {}
        if self.sources_path.exists():
            for line in self.sources_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    source_urls[str(row["source_id"])] = str(row["url"])
        index: dict[tuple[str, str], list[dict[str, Any]]] = {}
        if self.evidence_path.exists():
            for line in self.evidence_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                key = (str(row["model_id"]), str(row["normalized_field"]))
                index.setdefault(key, []).append(
                    {
                        "evidence_id": row["evidence_id"],
                        "source_id": row["source_id"],
                        "source_url": source_urls.get(str(row["source_id"])),
                        "field": row["normalized_field"],
                    }
                )
        self._evidence_index = index
        return index

    async def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query", "")).strip()
        model_ids = {str(item) for item in arguments.get("model_ids", []) if str(item)}
        required_fields = [str(item) for item in arguments.get("required_fields", []) if str(item)]
        if not query:
            return ToolResult(
                tool=self.name, status="failed", error_code="EMPTY_QUERY",
                summary="KB Search 缺少查询文本。", data={"hits": []},
            )
        try:
            store = await self._get_store()
            count = await store.count()
            if count <= 0:
                raise RuntimeError("knowledge-base collection is empty")
            embedding = await self.provider.embed([query])
            vector_results = await store.search(embedding.data[0], top_k=min(self.vector_top_k, count))
            candidates: list[dict[str, Any]] = []
            for document, score in vector_results:
                metadata = document.metadata or {}
                stable_model_id = str(metadata.get("model_id", ""))
                if model_ids and not any(
                    token.lower() == stable_model_id.lower() or token.lower() in stable_model_id.lower()
                    for token in model_ids
                ):
                    continue
                candidates.append(
                    {
                        "chunk_id": document.id,
                        "snippet": str(document.content)[:600],
                        "vector_score": float(score),
                        "metadata": metadata,
                    }
                )
            if not candidates:
                return ToolResult(
                    tool=self.name, status="success", summary="知识库没有命中指定型号或版本。",
                    data={"hits": [], "hit_count": 0, "reranker_degraded": False},
                )
            reranked = await self.provider.rerank_or_fallback(
                query,
                [item["snippet"] for item in candidates],
                top_n=min(self.result_top_k, len(candidates)),
                vector_scores=[item["vector_score"] for item in candidates],
            )
            hits = []
            evidence_index = self._load_evidence_index()
            for rank, item in enumerate(reranked.data, start=1):
                candidate = candidates[int(item["index"])]
                metadata = candidate["metadata"]
                bindings = [
                    binding
                    for field in required_fields
                    for binding in evidence_index.get((str(metadata.get("model_id", "")), field), [])
                ]
                hits.append(
                    {
                        "rank": rank,
                        "chunk_id": candidate["chunk_id"],
                        "snippet": candidate["snippet"],
                        "vector_score": candidate["vector_score"],
                        "rerank_score": float(item["relevance_score"]),
                        "model_id": metadata.get("model_id"),
                        "brand": metadata.get("brand"),
                        "region": metadata.get("region_version"),
                        "source_id": metadata.get("source_id"),
                        "source_type": metadata.get("source_type"),
                        "source_url": metadata.get("source_url"),
                        "section": metadata.get("section_page"),
                        "accessed_at": metadata.get("accessed_at"),
                        "evidence_bindings": bindings,
                    }
                )
            degraded = bool(reranked.degraded)
            return ToolResult(
                tool=self.name,
                status="degraded" if degraded else "success",
                degraded=degraded,
                summary=f"KB 命中 {len(hits)} 个证据片段；Reranker {'已降级' if degraded else '成功'}。",
                data={"hits": hits, "hit_count": len(hits), "reranker_degraded": degraded},
            )
        except Exception as exc:
            # The public result intentionally excludes provider bodies, prompts and credential-bearing details.
            return ToolResult(
                tool=self.name, status="failed", error_code=type(exc).__name__.upper(),
                summary="KB Search 未完成；未暴露底层敏感错误。", data={"hits": []},
            )
