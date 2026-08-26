"""Verify the persisted Chroma collection without making model API calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import chromadb

from smartbuy.retrieval.knowledge_base import DEFAULT_INDEX_DIR, INDEX_CONTRACT, REQUIRED_CHUNK_METADATA


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    args = parser.parse_args()
    client = chromadb.PersistentClient(path=str(args.index_dir.resolve()))
    collection = client.get_collection(INDEX_CONTRACT["collection_name"])
    result = collection.get(include=["metadatas"])
    metadatas = result.get("metadatas") or []
    missing = {
        metadata.get("doc_id", "unknown"): sorted(REQUIRED_CHUNK_METADATA - set(metadata))
        for metadata in metadatas
        if REQUIRED_CHUNK_METADATA - set(metadata)
    }
    payload = {
        "status": "completed" if len(result["ids"]) > 0 and not missing else "failed",
        "chunk_count": len(result["ids"]),
        "unique_document_count": len({metadata["doc_id"] for metadata in metadatas}),
        "unique_model_count": len({metadata["model_id"] for metadata in metadatas}),
        "region_versions": sorted({metadata["region_version"] for metadata in metadatas}),
        "embedding_models": sorted({metadata["embedding_model"] for metadata in metadatas}),
        "embedding_dimensions": sorted({metadata["embedding_dimensions"] for metadata in metadatas}),
        "collection_metadata": collection.metadata,
        "metadata_contract_errors": missing,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
