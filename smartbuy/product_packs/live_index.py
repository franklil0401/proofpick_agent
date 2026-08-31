"""Transactional live Chroma indexes for published Product Pack snapshots."""

from __future__ import annotations

import gc
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, Sequence

from smartbuy.data.loader import stable_json_hash
from smartbuy.observability import UsageLedger
from smartbuy.product_packs.builder import ProductPackManager, PublishedProductSnapshot
from smartbuy.product_packs.loader import ProductPackValidationError


INDEX_MANIFEST_SCHEMA_VERSION = "proofpick-product-index-manifest-v1"
REQUIRED_DOCUMENT_METADATA = {
    "doc_id",
    "model_id",
    "brand",
    "region_version",
    "variant_key",
    "source_version",
    "source_id",
    "source_type",
    "source_url",
    "section_page",
    "accessed_at",
    "chunk_config_version",
    "embedding_model",
    "embedding_dimensions",
    "data_version",
    "schema_version",
}


class EmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> Any: ...


def _safe_version(value: str, *, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise ProductPackValidationError(f"{label} is not filesystem-safe")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProductPackValidationError("vector documents are unavailable") from exc


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        return list(value.tolist())
    return list(value)


def _logical_collection_payload(collection: Any) -> list[dict[str, Any]]:
    result = collection.get(include=["documents", "metadatas", "embeddings"])
    ids = list(result.get("ids") or [])
    documents = list(result.get("documents") or [])
    metadatas = list(result.get("metadatas") or [])
    embeddings = _as_list(result.get("embeddings"))
    if not (len(ids) == len(documents) == len(metadatas) == len(embeddings)):
        raise ProductPackValidationError("Chroma collection arrays have different lengths")
    rows = []
    for index, chunk_id in enumerate(ids):
        rows.append(
            {
                "chunk_id": str(chunk_id),
                "document": str(documents[index]),
                "metadata": dict(metadatas[index] or {}),
                "embedding": [float(item) for item in _as_list(embeddings[index])],
            }
        )
    return sorted(rows, key=lambda item: item["chunk_id"])


@dataclass(frozen=True)
class PublishedIndexSnapshot:
    root: Path
    index_version: str
    data_version: str
    manifest_hash: str
    manifest: dict[str, Any]

    @property
    def chroma_path(self) -> Path:
        return self.root / "chroma"

    @property
    def collection_name(self) -> str:
        return str(self.manifest["collection_name"])


class ProductIndexManager:
    """Build and atomically select immutable indexes outside the repository."""

    def __init__(self, runtime_root: Path | str) -> None:
        self.runtime_root = Path(runtime_root).resolve()
        self.data_manager = ProductPackManager(self.runtime_root)
        self.indices_root = self.runtime_root / "indices"
        self.current_pointer = self.runtime_root / "current_index.json"

    async def build(
        self,
        data_version: str,
        index_version: str,
        provider: EmbeddingProvider,
        *,
        batch_size: int = 10,
        cost_limit_cny: float = 1.0,
    ) -> PublishedIndexSnapshot:
        data = self.data_manager.validate(data_version, published=True)
        version = _safe_version(index_version, label="index version")
        if batch_size < 1 or batch_size > 10:
            raise ValueError("embedding batch size must be between 1 and 10")
        if not 0 < cost_limit_cny <= 1.0:
            raise ValueError("live index cost limit must be between 0 and 1 CNY")
        target = (self.indices_root / version).resolve()
        self.indices_root.mkdir(parents=True, exist_ok=True)
        if target.parent != self.indices_root.resolve():
            raise ProductPackValidationError("index path escaped runtime root")
        if target.exists():
            existing = self.validate_path(target)
            if existing.data_version != data.data_version:
                raise ProductPackValidationError("index version already belongs to other data")
            return existing

        documents = self._validated_documents(data)
        projected_cost = UsageLedger.estimate_cost(
            "text-embedding-v4",
            sum(len(item["content"]) for item in documents),
        )
        if projected_cost > cost_limit_cny:
            raise ProductPackValidationError("projected embedding cost exceeds limit")

        temporary = Path(
            tempfile.mkdtemp(prefix=".build-index-", dir=self.indices_root)
        ).resolve()
        try:
            collection_name = self._collection_name(data.data_version, version)
            usage: list[dict[str, Any]] = []
            all_vectors: list[list[float]] = []
            for start in range(0, len(documents), batch_size):
                batch = documents[start : start + batch_size]
                result = await provider.embed([item["content"] for item in batch])
                vectors = list(result.data)
                if len(vectors) != len(batch):
                    raise ProductPackValidationError("Embedding count differs from documents")
                if any(len(vector) != 1024 for vector in vectors):
                    raise ProductPackValidationError("Embedding dimension differs from 1024")
                input_tokens = int(result.usage.get("input_tokens", 0))
                usage.append(
                    {
                        "operation": "embedding",
                        "model": "text-embedding-v4",
                        "attempts": int(result.attempts),
                        "latency_ms": round(float(result.latency_ms), 3),
                        "input_tokens": input_tokens,
                        "item_count": len(vectors),
                        "estimated_cost_cny": UsageLedger.estimate_cost(
                            "text-embedding-v4", input_tokens
                        ),
                    }
                )
                all_vectors.extend(vectors)
            actual_cost = sum(float(item["estimated_cost_cny"]) for item in usage)
            if actual_cost > cost_limit_cny:
                raise ProductPackValidationError("embedding cost exceeds configured limit")
            await self._write_chroma_async(
                temporary / "chroma",
                collection_name,
                documents,
                all_vectors,
                data,
                version,
            )
            manifest = self._build_manifest(
                temporary,
                data,
                version,
                collection_name,
                usage,
            )
            _write_json(temporary / "index_manifest.json", manifest)
            self.validate_path(temporary)
            os.replace(temporary, target)
            return self.validate_path(target)
        finally:
            if temporary.exists() and temporary.parent == self.indices_root.resolve():
                shutil.rmtree(temporary)

    def validate(self, index_version: str) -> PublishedIndexSnapshot:
        version = _safe_version(index_version, label="index version")
        return self.validate_path(self.indices_root / version)

    def validate_path(self, root: Path | str) -> PublishedIndexSnapshot:
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            raise ProductPackValidationError("index version directory is missing")
        try:
            manifest = json.loads(
                (root_path / "index_manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductPackValidationError("live index manifest is unavailable") from exc
        if manifest.get("manifest_schema_version") != INDEX_MANIFEST_SCHEMA_VERSION:
            raise ProductPackValidationError("live index manifest schema is incompatible")
        index_version = _safe_version(
            str(manifest.get("index_version", "")), label="index version"
        )
        data_version = _safe_version(
            str(manifest.get("data_version", "")), label="data version"
        )
        if not root_path.name.startswith(".build-index-") and root_path.name != index_version:
            raise ProductPackValidationError("directory and index versions differ")
        data = self.data_manager.validate(data_version, published=True)
        data_index = data.manifest["index"]
        if (
            manifest.get("status") != "completed"
            or manifest.get("data_manifest_hash") != data.manifest_hash
            or manifest.get("embedding_model") != "text-embedding-v4"
            or manifest.get("embedding_dimensions") != 1024
            or manifest.get("chunk_config_version")
            != data_index["chunk_config_version"]
            or manifest.get("vector_document_sha256")
            != data_index["vector_document_sha256"]
            or manifest.get("document_count") != data_index["document_count"]
            or manifest.get("chunk_count") != data_index["document_count"]
        ):
            raise ProductPackValidationError("live index and data manifest differ")
        payload, collection_metadata = self._read_collection(
            root_path / "chroma", str(manifest.get("collection_name", ""))
        )
        if len(payload) != int(manifest["chunk_count"]):
            raise ProductPackValidationError("Chroma chunk count differs from manifest")
        documents = self._validated_documents(data)
        expected_ids = {item["doc_id"] for item in documents}
        if {item["chunk_id"] for item in payload} != expected_ids:
            raise ProductPackValidationError("Chroma document identities differ")
        for item in payload:
            metadata = item["metadata"]
            if len(item["embedding"]) != 1024:
                raise ProductPackValidationError("stored vector dimension differs from 1024")
            if REQUIRED_DOCUMENT_METADATA - set(metadata):
                raise ProductPackValidationError("stored chunk metadata is incomplete")
            if (
                metadata.get("data_version") != data_version
                or metadata.get("embedding_model") != "text-embedding-v4"
                or metadata.get("embedding_dimensions") != 1024
                or metadata.get("index_version") != index_version
            ):
                raise ProductPackValidationError("stored chunk metadata version differs")
        if stable_json_hash(payload) != manifest.get("logical_index_sha256"):
            raise ProductPackValidationError("live index logical hash differs")
        for key in (
            "data_version",
            "index_version",
            "embedding_model",
            "embedding_dimensions",
            "chunk_config_version",
            "vector_document_sha256",
        ):
            if collection_metadata.get(key) != manifest.get(key):
                raise ProductPackValidationError("Chroma collection metadata differs")
        return PublishedIndexSnapshot(
            root=root_path,
            index_version=index_version,
            data_version=data_version,
            manifest_hash=stable_json_hash(manifest),
            manifest=manifest,
        )

    def activate(self, index_version: str) -> PublishedIndexSnapshot:
        return self._select(index_version, action="activate")

    def rollback(self, index_version: str) -> PublishedIndexSnapshot:
        return self._select(index_version, action="rollback")

    def current(self) -> PublishedIndexSnapshot:
        pointer = self._read_pointer()
        snapshot = self.validate(str(pointer["index_version"]))
        if (
            snapshot.manifest_hash != pointer.get("manifest_hash")
            or snapshot.data_version != pointer.get("data_version")
        ):
            raise ProductPackValidationError("current index pointer differs from version")
        return snapshot

    def list_versions(self) -> list[dict[str, Any]]:
        current = self._read_pointer().get("index_version") if self.current_pointer.exists() else None
        if not self.indices_root.exists():
            return []
        output = []
        for path in sorted(item for item in self.indices_root.iterdir() if item.is_dir()):
            if path.name.startswith(".build-index-"):
                continue
            snapshot = self.validate_path(path)
            output.append(
                {
                    "index_version": snapshot.index_version,
                    "data_version": snapshot.data_version,
                    "manifest_hash": snapshot.manifest_hash,
                    "current": snapshot.index_version == current,
                }
            )
        return output

    def _select(self, index_version: str, *, action: str) -> PublishedIndexSnapshot:
        target = self.validate(index_version)
        data = self.data_manager.current()
        if target.data_version != data.data_version:
            raise ProductPackValidationError("index does not belong to current data version")
        previous = self._read_pointer().get("index_version") if self.current_pointer.exists() else None
        payload = {
            "action": action,
            "data_version": target.data_version,
            "index_version": target.index_version,
            "manifest_hash": target.manifest_hash,
            "previous_index_version": previous,
        }
        temporary = self.runtime_root / ".current_index.json.tmp"
        _write_json(temporary, payload)
        os.replace(temporary, self.current_pointer)
        return target

    def _read_pointer(self) -> dict[str, Any]:
        try:
            pointer = json.loads(self.current_pointer.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductPackValidationError("current live index pointer is unavailable") from exc
        if set(pointer) != {
            "action",
            "data_version",
            "index_version",
            "manifest_hash",
            "previous_index_version",
        }:
            raise ProductPackValidationError("current live index pointer schema is invalid")
        return pointer

    @staticmethod
    def _collection_name(data_version: str, index_version: str) -> str:
        suffix = hashlib.sha256(
            f"{data_version}:{index_version}".encode("utf-8")
        ).hexdigest()[:16]
        return f"proofpick_monitor_v2_{suffix}"

    @staticmethod
    def _validated_documents(data: PublishedProductSnapshot) -> list[dict[str, Any]]:
        path = data.root / "vector_documents.jsonl"
        documents = _read_jsonl(path)
        index = data.manifest["index"]
        if (
            len(documents) != index["document_count"]
            or hashlib.sha256(path.read_bytes()).hexdigest()
            != index["vector_document_sha256"]
        ):
            raise ProductPackValidationError("vector documents differ from data manifest")
        ids: set[str] = set()
        for document in documents:
            doc_id = str(document.get("doc_id", ""))
            metadata = document.get("metadata") or {}
            if not doc_id or doc_id in ids:
                raise ProductPackValidationError("vector document ids are invalid")
            ids.add(doc_id)
            if REQUIRED_DOCUMENT_METADATA - set(metadata):
                raise ProductPackValidationError("vector document metadata is incomplete")
            if (
                metadata.get("doc_id") != doc_id
                or metadata.get("data_version") != data.data_version
                or metadata.get("embedding_model") != "text-embedding-v4"
                or metadata.get("embedding_dimensions") != 1024
            ):
                raise ProductPackValidationError("vector document contract differs")
        return documents

    async def _write_chroma_async(
        self,
        path: Path,
        collection_name: str,
        documents: list[dict[str, Any]],
        vectors: list[list[float]],
        data: PublishedProductSnapshot,
        index_version: str,
    ) -> None:
        import chromadb
        from chromadb.config import Settings

        client = chromadb.PersistentClient(
            path=str(path), settings=Settings(anonymized_telemetry=False)
        )
        try:
            collection = client.get_or_create_collection(
                name=collection_name, metadata={"hnsw:space": "cosine"}
            )
            collection.add(
                ids=[item["doc_id"] for item in documents],
                embeddings=vectors,
                documents=[item["content"] for item in documents],
                metadatas=[
                    {
                        "document_id": item["doc_id"],
                        "chunk_index": 0,
                        **item["metadata"],
                        "index_version": index_version,
                    }
                    for item in documents
                ],
            )
            collection_metadata = {
                "data_version": data.data_version,
                "index_version": index_version,
                "embedding_model": "text-embedding-v4",
                "embedding_dimensions": 1024,
                "chunk_config_version": data.manifest["index"]["chunk_config_version"],
                "vector_document_sha256": data.manifest["index"]["vector_document_sha256"],
            }
            collection.modify(metadata=collection_metadata)
            if collection.count() != len(documents):
                raise ProductPackValidationError("Chroma count differs after build")
            del collection
        finally:
            self._close_chroma_client(client)

    def _build_manifest(
        self,
        root: Path,
        data: PublishedProductSnapshot,
        index_version: str,
        collection_name: str,
        usage: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload, _ = self._read_collection(root / "chroma", collection_name)
        return {
            "manifest_schema_version": INDEX_MANIFEST_SCHEMA_VERSION,
            "status": "completed",
            "data_version": data.data_version,
            "data_manifest_hash": data.manifest_hash,
            "index_version": index_version,
            "collection_name": collection_name,
            "created_at": datetime.now(UTC).isoformat(),
            "embedding_model": "text-embedding-v4",
            "embedding_dimensions": 1024,
            "chunk_config_version": data.manifest["index"]["chunk_config_version"],
            "vector_document_sha256": data.manifest["index"]["vector_document_sha256"],
            "document_count": data.manifest["index"]["document_count"],
            "chunk_count": len(payload),
            "logical_index_sha256": stable_json_hash(payload),
            "embedding_call_count": len(usage),
            "embedding_input_tokens": sum(int(item["input_tokens"]) for item in usage),
            "embedding_estimated_cost_cny": round(
                sum(float(item["estimated_cost_cny"]) for item in usage), 8
            ),
            "embedding_usage": usage,
        }

    @classmethod
    def _read_collection(
        cls, path: Path, collection_name: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        client: Any | None = None
        try:
            import chromadb
            from chromadb.config import Settings

            client = chromadb.PersistentClient(
                path=str(path), settings=Settings(anonymized_telemetry=False)
            )
            collection = client.get_collection(name=collection_name)
            payload = _logical_collection_payload(collection)
            metadata = dict(collection.metadata or {})
            del collection
            return payload, metadata
        except Exception as exc:
            raise ProductPackValidationError("Chroma collection is unavailable") from exc
        finally:
            if client is not None:
                cls._close_chroma_client(client)

    @staticmethod
    def _close_chroma_client(client: Any) -> None:
        """Stop Chroma's shared system so Windows releases HNSW file handles."""

        try:
            from chromadb.api.shared_system_client import SharedSystemClient

            identifier = getattr(client, "_identifier", None)
            system = getattr(client, "_system", None)
            if system is not None:
                system.stop()
            if identifier is not None:
                SharedSystemClient._identifier_to_system.pop(identifier, None)
        finally:
            del client
            gc.collect()
