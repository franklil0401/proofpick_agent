"""Build the governed monitor knowledge base with the pinned Youtu-RAG runtime."""

from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterator

from smartbuy.config import BailianSettings
from smartbuy.data.loader import load_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FACT_CARD_DIR = PROJECT_ROOT / "smartbuy" / "data" / "demo" / "fact_cards"
DEFAULT_INDEX_DIR = Path("C:/ai/smartbuy-stage3/vector_store_text_embedding_v4_1024")
INDEX_MANIFEST_PATH = PROJECT_ROOT / "smartbuy" / "data" / "processed" / "index_manifest.json"
INDEX_CONTRACT = {
    "collection_name": "smartbuy_monitors_v1",
    "embedding_model": "text-embedding-v4",
    "embedding_dimensions": 1024,
    "chunk_config_version": "monitor-fact-card-h2-v1",
    "chunk_size": 700,
    "chunk_overlap": 80,
}
REQUIRED_CHUNK_METADATA = {
    "doc_id",
    "model_id",
    "brand",
    "region_version",
    "source_id",
    "source_type",
    "source_url",
    "section_page",
    "accessed_at",
    "chunk_config_version",
    "embedding_model",
    "embedding_dimensions",
}


@contextlib.contextmanager
def youtu_environment(settings: BailianSettings) -> Iterator[None]:
    """Temporarily map inherited settings to Youtu variables, without logging values."""
    mapping = settings.youtu_environment()
    previous = {name: os.environ.get(name) for name in mapping}
    os.environ.update(mapping)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _sections(markdown: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", markdown, flags=re.MULTILINE))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[match.end() : end].strip()
        sections.append((match.group(1).strip(), body))
    return sections


def load_fact_card_documents(model_ids: set[str] | None = None) -> list[Any]:
    """Create one Youtu Document per H2 section with the full index contract."""
    from utu.rag.base import Document

    catalog = load_catalog()
    products = {item["model_id"]: item for item in catalog.products}
    sources = {item["source_id"]: item for item in catalog.source_records}
    documents = []
    for model_id in sorted(products):
        if model_ids is not None and model_id not in model_ids:
            continue
        product = products[model_id]
        source = sources[product["official_source_id"]]
        path = FACT_CARD_DIR / f"{model_id}.md"
        for section_index, (section, body) in enumerate(_sections(path.read_text(encoding="utf-8")), start=1):
            doc_id = f"{model_id}--s{section_index:02d}"
            metadata = {
                "doc_id": doc_id,
                "model_id": model_id,
                "brand": product["brand"],
                "region_version": product["region"],
                "source_id": source["source_id"],
                "source_type": source["source_type"],
                "source_url": source["url"],
                "section_page": section,
                "accessed_at": source["accessed_at"],
                "chunk_config_version": INDEX_CONTRACT["chunk_config_version"],
                "embedding_model": INDEX_CONTRACT["embedding_model"],
                "embedding_dimensions": INDEX_CONTRACT["embedding_dimensions"],
                "data_version": catalog.data_version,
                "schema_version": catalog.schema_version,
            }
            content = f"型号：{product['brand']} {product['model_name']}（{product['region']}）\n章节：{section}\n{body}"
            documents.append(Document(id=doc_id, content=content, metadata=metadata))
    return documents


async def build_knowledge_base(
    settings: BailianSettings,
    *,
    index_dir: Path | str = DEFAULT_INDEX_DIR,
    collection_name: str = INDEX_CONTRACT["collection_name"],
    model_ids: set[str] | None = None,
    rebuild: bool = True,
) -> tuple[dict[str, Any], Any]:
    """Build and verify a collection; return a sanitized manifest and live store."""
    with youtu_environment(settings):
        from utu.rag.config import ChunkingConfig, EmbeddingConfig, KnowledgeBuilderConfig, VectorStoreConfig
        from utu.rag.knowledge_builder.base_builder import KnowledgeBuilder
        from utu.rag.storage.implementations.chroma_store import ChromaVectorStore

        index_path = Path(index_dir).resolve()
        index_path.mkdir(parents=True, exist_ok=True)
        vector_store = ChromaVectorStore(
            VectorStoreConfig(
                collection_name=collection_name,
                persist_directory=str(index_path),
                distance_metric="cosine",
            )
        )
        builder = KnowledgeBuilder(
            vector_store,
            KnowledgeBuilderConfig(
                chunking=ChunkingConfig(
                    chunk_size=INDEX_CONTRACT["chunk_size"],
                    chunk_overlap=INDEX_CONTRACT["chunk_overlap"],
                ),
                embedding=EmbeddingConfig(
                    provider="openai",
                    model=settings.embedding_model,
                    api_key=settings.api_key,
                    base_url=settings.compatible_base_url,
                    batch_size=32,
                    dimensions=settings.embedding_dimensions,
                ),
                batch_delay=0,
            ),
        )
        documents = load_fact_card_documents(model_ids)
        status = await builder.build_from_documents(documents, rebuild=rebuild)
        # Chroma fixes hnsw:space at collection creation and rejects it in modify(),
        # even when the submitted value is unchanged. Update only mutable contract fields.
        collection_metadata = {
            "embedding_model": settings.embedding_model,
            "embedding_dimensions": settings.embedding_dimensions,
            "data_version": load_catalog().data_version,
            "chunk_config_version": INDEX_CONTRACT["chunk_config_version"],
        }
        vector_store.collection.modify(metadata=collection_metadata)
        actual_chunks = await vector_store.count()
        sample = vector_store.collection.get(limit=1, include=["metadatas"])
        sample_metadata = sample["metadatas"][0] if sample.get("metadatas") else {}
        missing_metadata = sorted(REQUIRED_CHUNK_METADATA - set(sample_metadata))
        usage = list(getattr(builder.embedder, "usage_records", []))
        manifest = {
            "status": status.status,
            "collection_name": collection_name,
            "data_version": load_catalog().data_version,
            "document_count": len(documents),
            "processed_documents": status.processed_documents,
            "builder_chunk_count": status.total_chunks,
            "chroma_chunk_count": actual_chunks,
            "counts_match": status.total_chunks == actual_chunks,
            "errors": status.errors,
            "collection_metadata": {**(vector_store.collection.metadata or {}), "distance_metric": "cosine"},
            "required_chunk_metadata_missing": missing_metadata,
            "embedding_usage": usage,
            "embedding_call_count": len(usage),
            "embedding_input_tokens": sum(int(item.get("input_tokens", 0)) for item in usage),
            "embedding_estimated_cost_cny": round(sum(float(item.get("estimated_cost_cny", 0)) for item in usage), 8),
        }
        if status.status != "completed" or status.errors or not manifest["counts_match"] or missing_metadata:
            raise RuntimeError("knowledge-base verification failed")
        return manifest, vector_store


def write_index_manifest(manifest: dict[str, Any], path: Path = INDEX_MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
