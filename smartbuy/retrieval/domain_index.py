"""Domain-neutral immutable Chroma index for governed Product Pack snapshots."""

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
from smartbuy.product_packs.domain_builder import DomainProductPackManager, DomainProductSnapshot
from smartbuy.product_packs.loader import ProductPackValidationError


DOMAIN_INDEX_MANIFEST_VERSION = "proofpick-domain-index-manifest-v1"
REQUIRED_METADATA = {
    "domain_id", "product_id", "configuration_id", "variant_key", "region",
    "source_ids", "evidence_ids", "data_version", "domain_pack_version",
    "embedding_model", "embedding_dimensions", "index_version",
}


class EmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> Any: ...


def _safe(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise ProductPackValidationError("index version is not filesystem-safe")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProductPackValidationError("domain index source is unavailable") from exc


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_domain_documents(
    snapshot: DomainProductSnapshot,
    *,
    domain_pack_version: str,
) -> list[dict[str, Any]]:
    """Make one non-duplicated fact document per product from governed evidence."""

    products = _read_jsonl(snapshot.root / "products.jsonl")
    evidence = _read_jsonl(snapshot.root / "evidence_records.jsonl")
    sources = {row["source_id"]: row for row in _read_jsonl(snapshot.root / "source_records.jsonl")}
    evidence_by_product: dict[str, list[dict[str, Any]]] = {}
    for row in evidence:
        evidence_by_product.setdefault(str(row["product_id"]), []).append(row)
    documents: list[dict[str, Any]] = []
    for product in sorted(products, key=lambda item: item["product_id"]):
        rows = sorted(evidence_by_product.get(product["product_id"], []), key=lambda item: item["evidence_id"])
        if not rows:
            raise ProductPackValidationError("product has no governed evidence")
        evidence_ids = [str(row["evidence_id"]) for row in rows]
        source_ids = sorted({str(row["source_id"]) for row in rows})
        if any(source_id not in sources for source_id in source_ids):
            raise ProductPackValidationError("domain document references an unknown source")
        configuration_id = product["attributes"].get("configuration_id")
        if not configuration_id:
            raise ProductPackValidationError("product has no configuration identity")
        facts = "\n".join(
            f"{row['field_id']}: {row['normalized_value']}"
            + (f" {row['unit']}" if row.get("unit") else "")
            + f" [evidence={row['evidence_id']}]"
            for row in rows
        )
        documents.append(
            {
                "doc_id": f"{product['domain_id']}:{product['product_id']}:governed-facts",
                "content": (
                    f"{product['brand']} {product['model_name']}，product_id={product['product_id']}，"
                    f"configuration_id={configuration_id}，region={product['region']}。\n{facts}"
                ),
                "metadata": {
                    "domain_id": product["domain_id"],
                    "product_id": product["product_id"],
                    "configuration_id": str(configuration_id),
                    "variant_key": product["variant_key"],
                    "brand": product["brand"],
                    "region": product["region"],
                    "source_ids": json.dumps(source_ids, ensure_ascii=False),
                    "evidence_ids": json.dumps(evidence_ids, ensure_ascii=False),
                    "data_version": snapshot.data_version,
                    "domain_pack_version": domain_pack_version,
                    "embedding_model": "text-embedding-v4",
                    "embedding_dimensions": 1024,
                },
            }
        )
    return documents


@dataclass(frozen=True)
class DomainIndexSnapshot:
    root: Path
    index_version: str
    data_version: str
    collection_name: str
    manifest_hash: str
    manifest: dict[str, Any]


class DomainIndexManager:
    """Build, validate and atomically activate a domain-scoped index."""

    def __init__(
        self,
        runtime_root: Path | str,
        *,
        data_manager: DomainProductPackManager,
        domain_id: str,
        domain_pack_version: str,
    ) -> None:
        self.runtime_root = Path(runtime_root).resolve()
        self.data_manager = data_manager
        self.domain_id = domain_id
        self.domain_pack_version = domain_pack_version
        self.indices_root = self.runtime_root / "domain_indices" / domain_id
        self.current_pointer = self.runtime_root / f"current_{domain_id}_index.json"

    async def build(
        self,
        data_version: str,
        index_version: str,
        provider: EmbeddingProvider,
        *,
        batch_size: int = 10,
        cost_limit_cny: float = 1.0,
    ) -> DomainIndexSnapshot:
        data = self.data_manager.validate(data_version, published=True)
        if data.manifest.get("domain_id") != self.domain_id:
            raise ProductPackValidationError("domain and data version differ")
        if data.manifest.get("domain_pack_version") != self.domain_pack_version:
            raise ProductPackValidationError("domain pack and data version differ")
        version = _safe(index_version)
        if not 1 <= batch_size <= 10:
            raise ValueError("embedding batch size must be between 1 and 10")
        target = self.indices_root / version
        self.indices_root.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return self.validate(version)
        documents = build_domain_documents(data, domain_pack_version=self.domain_pack_version)
        projected = UsageLedger.estimate_cost(
            "text-embedding-v4", sum(len(item["content"]) for item in documents)
        )
        if projected > cost_limit_cny:
            raise ProductPackValidationError("projected embedding cost exceeds limit")
        temporary = Path(tempfile.mkdtemp(prefix=".build-", dir=self.indices_root))
        usage: list[dict[str, Any]] = []
        try:
            vectors: list[list[float]] = []
            for start in range(0, len(documents), batch_size):
                batch = documents[start : start + batch_size]
                result = await provider.embed([item["content"] for item in batch])
                batch_vectors = list(result.data)
                if len(batch_vectors) != len(batch) or any(len(vector) != 1024 for vector in batch_vectors):
                    raise ProductPackValidationError("Embedding result violates count or dimension")
                tokens = int(result.usage.get("input_tokens", 0))
                usage.append({
                    "model": "text-embedding-v4", "attempts": result.attempts,
                    "latency_ms": round(float(result.latency_ms), 3),
                    "input_tokens": tokens, "item_count": len(batch),
                    "estimated_cost_cny": UsageLedger.estimate_cost("text-embedding-v4", tokens),
                })
                vectors.extend(batch_vectors)
            if sum(row["estimated_cost_cny"] for row in usage) > cost_limit_cny:
                raise ProductPackValidationError("embedding cost exceeds limit")
            collection_name = self._collection_name(data_version, version)
            self._write_collection(temporary / "chroma", collection_name, documents, vectors, version)
            logical_hash = self._logical_hash(temporary / "chroma", collection_name)
            manifest = {
                "manifest_schema_version": DOMAIN_INDEX_MANIFEST_VERSION,
                "status": "completed", "domain_id": self.domain_id,
                "domain_pack_version": self.domain_pack_version,
                "data_version": data.data_version, "data_manifest_hash": data.manifest_hash,
                "index_version": version, "collection_name": collection_name,
                "embedding_model": "text-embedding-v4", "embedding_dimensions": 1024,
                "document_count": len(documents), "chunk_count": len(documents),
                "document_contract_sha256": stable_json_hash(documents),
                "logical_index_sha256": logical_hash,
                "embedding_call_count": len(usage),
                "embedding_input_tokens": sum(row["input_tokens"] for row in usage),
                "embedding_estimated_cost_cny": round(sum(row["estimated_cost_cny"] for row in usage), 8),
                "embedding_usage": usage, "created_at": datetime.now(UTC).isoformat(),
            }
            _write_json(temporary / "index_manifest.json", manifest)
            self.validate_path(temporary)
            os.replace(temporary, target)
            return self.validate(version)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def activate(self, index_version: str) -> DomainIndexSnapshot:
        snapshot = self.validate(index_version)
        data = self.data_manager.current()
        if snapshot.data_version != data.data_version:
            raise ProductPackValidationError("index does not belong to current data version")
        payload = {
            "domain_id": self.domain_id, "data_version": snapshot.data_version,
            "index_version": snapshot.index_version, "manifest_hash": snapshot.manifest_hash,
        }
        temporary = self.current_pointer.with_suffix(".tmp")
        _write_json(temporary, payload)
        os.replace(temporary, self.current_pointer)
        return snapshot

    def rollback(self, index_version: str) -> DomainIndexSnapshot:
        """Select an already validated index; no index files are mutated."""

        return self.activate(index_version)

    def current(self) -> DomainIndexSnapshot:
        try:
            pointer = json.loads(self.current_pointer.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductPackValidationError("domain index pointer is unavailable") from exc
        if pointer.get("domain_id") != self.domain_id:
            raise ProductPackValidationError("domain index pointer is cross-domain")
        snapshot = self.validate(str(pointer.get("index_version", "")))
        if snapshot.manifest_hash != pointer.get("manifest_hash") or snapshot.data_version != pointer.get("data_version"):
            raise ProductPackValidationError("domain index pointer is stale")
        return snapshot

    def validate(self, index_version: str) -> DomainIndexSnapshot:
        return self.validate_path(self.indices_root / _safe(index_version))

    def validate_path(self, root: Path | str) -> DomainIndexSnapshot:
        path = Path(root).resolve()
        try:
            manifest = json.loads((path / "index_manifest.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductPackValidationError("domain index manifest is unavailable") from exc
        if manifest.get("manifest_schema_version") != DOMAIN_INDEX_MANIFEST_VERSION or manifest.get("status") != "completed":
            raise ProductPackValidationError("domain index is incomplete")
        if manifest.get("domain_id") != self.domain_id or manifest.get("domain_pack_version") != self.domain_pack_version:
            raise ProductPackValidationError("domain index contract differs")
        data = self.data_manager.validate(str(manifest.get("data_version", "")), published=True)
        documents = build_domain_documents(data, domain_pack_version=self.domain_pack_version)
        if (
            manifest.get("data_manifest_hash") != data.manifest_hash
            or manifest.get("embedding_model") != "text-embedding-v4"
            or manifest.get("embedding_dimensions") != 1024
            or manifest.get("document_count") != len(documents)
            or manifest.get("chunk_count") != len(documents)
            or manifest.get("document_contract_sha256") != stable_json_hash(documents)
        ):
            raise ProductPackValidationError("domain index and data manifest differ")
        payload = self.read_collection(path / "chroma", str(manifest["collection_name"]))
        if len(payload) != len(documents) or stable_json_hash(payload) != manifest.get("logical_index_sha256"):
            raise ProductPackValidationError("domain Chroma payload differs")
        expected_ids = {item["doc_id"] for item in documents}
        if {item["doc_id"] for item in payload} != expected_ids:
            raise ProductPackValidationError("domain Chroma identities differ")
        for item in payload:
            metadata = item["metadata"]
            if REQUIRED_METADATA - set(metadata) or len(item["embedding"]) != 1024:
                raise ProductPackValidationError("domain Chroma metadata or dimension differs")
            if metadata["domain_id"] != self.domain_id or metadata["data_version"] != data.data_version:
                raise ProductPackValidationError("cross-domain data found in index")
        return DomainIndexSnapshot(
            path, str(manifest["index_version"]), data.data_version,
            str(manifest["collection_name"]), stable_json_hash(manifest), manifest,
        )

    def _collection_name(self, data_version: str, index_version: str) -> str:
        suffix = hashlib.sha256(f"{self.domain_id}:{data_version}:{index_version}".encode()).hexdigest()[:16]
        return f"proofpick_{self.domain_id}_v2_{suffix}"

    def _write_collection(self, path: Path, name: str, documents: list[dict[str, Any]], vectors: list[list[float]], index_version: str) -> None:
        import chromadb
        from chromadb.config import Settings

        client = chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))
        try:
            collection = client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})
            collection.add(
                ids=[item["doc_id"] for item in documents], embeddings=vectors,
                documents=[item["content"] for item in documents],
                metadatas=[{**item["metadata"], "index_version": index_version} for item in documents],
            )
            if collection.count() != len(documents):
                raise ProductPackValidationError("domain Chroma count differs")
        finally:
            self._close(client)

    @classmethod
    def read_collection(cls, path: Path, name: str) -> list[dict[str, Any]]:
        import chromadb
        from chromadb.config import Settings

        client = chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))
        try:
            result = client.get_collection(name=name).get(include=["documents", "metadatas", "embeddings"])
            rows = []
            for index, doc_id in enumerate(result["ids"]):
                rows.append({
                    "doc_id": doc_id, "document": result["documents"][index],
                    "metadata": dict(result["metadatas"][index]),
                    "embedding": [float(value) for value in result["embeddings"][index]],
                })
            return sorted(rows, key=lambda row: row["doc_id"])
        except Exception as exc:
            raise ProductPackValidationError("domain Chroma collection is unavailable") from exc
        finally:
            cls._close(client)

    @classmethod
    def _logical_hash(cls, path: Path, name: str) -> str:
        return stable_json_hash(cls.read_collection(path, name))

    @staticmethod
    def _close(client: Any) -> None:
        try:
            from chromadb.api.shared_system_client import SharedSystemClient

            system = getattr(client, "_system", None)
            identifier = getattr(client, "_identifier", None)
            if system is not None:
                system.stop()
            if identifier is not None:
                SharedSystemClient._identifier_to_system.pop(identifier, None)
        finally:
            del client
            gc.collect()
