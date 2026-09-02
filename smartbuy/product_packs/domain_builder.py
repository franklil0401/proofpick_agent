"""Domain-neutral Product Pack artifacts for non-V1 data domains.

The EAV schema and all validation rules are driven by Domain Pack data. No
product-category field names are embedded in this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from smartbuy.data.loader import stable_json_hash
from smartbuy.product_packs.ledger import governed_ledger_rows
from smartbuy.product_packs.loader import (
    LoadedProductPack,
    ProductPackLoader,
    ProductPackValidationError,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOMAIN_MANIFEST_VERSION = "proofpick-domain-data-manifest-v1"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(_canonical(row) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def _safe(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise ProductPackValidationError("version is not filesystem-safe")
    return value


def _outside_workspace(path: Path) -> bool:
    try:
        path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return True
    return False


@dataclass(frozen=True)
class DomainProductSnapshot:
    root: Path
    data_version: str
    manifest_hash: str
    manifest: dict[str, Any]

    @property
    def database_path(self) -> Path:
        return self.root / "products.sqlite"


class DomainProductPackManager:
    """Transactional staging/publish/rollback for a configured Domain Pack."""

    def __init__(self, runtime_root: Path | str, *, domain_pack_path: Path | str) -> None:
        self.runtime_root = Path(runtime_root).resolve()
        if not _outside_workspace(self.runtime_root):
            raise ValueError("Product Pack runtime root must stay outside the Git workspace")
        self.domain_pack_path = Path(domain_pack_path).resolve()
        self.staging_root = self.runtime_root / "staging"
        self.versions_root = self.runtime_root / "versions"
        self.current_pointer = self.runtime_root / "current.json"

    def stage(self, pack_path: Path | str) -> DomainProductSnapshot:
        loaded = ProductPackLoader(domain_pack_path=self.domain_pack_path).load(pack_path)
        version = _safe(loaded.document.data_version)
        self.staging_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".build-", dir=self.staging_root))
        try:
            self._build(temporary, loaded)
            snapshot = self.validate_path(temporary)
            target = self.staging_root / version
            if target.exists():
                existing = self.validate_path(target)
                if existing.manifest_hash != snapshot.manifest_hash:
                    raise ProductPackValidationError("staged data version has different content")
                return existing
            os.replace(temporary, target)
            return self.validate_path(target)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def publish(self, data_version: str) -> DomainProductSnapshot:
        staged = self.validate(data_version)
        self.versions_root.mkdir(parents=True, exist_ok=True)
        target = self.versions_root / _safe(data_version)
        if target.exists():
            published = self.validate_path(target)
            if published.manifest_hash != staged.manifest_hash:
                raise ProductPackValidationError("published version has different content")
        else:
            os.replace(staged.root, target)
            published = self.validate_path(target)
        self._write_pointer(published, action="publish")
        return published

    def rollback(self, data_version: str) -> DomainProductSnapshot:
        snapshot = self.validate(data_version, published=True)
        self._write_pointer(snapshot, action="rollback")
        return snapshot

    def current(self) -> DomainProductSnapshot:
        try:
            pointer = json.loads(self.current_pointer.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductPackValidationError("current pointer is unavailable") from exc
        snapshot = self.validate(str(pointer.get("data_version", "")), published=True)
        if snapshot.manifest_hash != pointer.get("manifest_hash"):
            raise ProductPackValidationError("current pointer hash differs")
        return snapshot

    def list_versions(self) -> list[dict[str, Any]]:
        current = self.current().data_version if self.current_pointer.exists() else None
        if not self.versions_root.exists():
            return []
        snapshots = [
            self.validate_path(path)
            for path in sorted(item for item in self.versions_root.iterdir() if item.is_dir())
        ]
        return [
            {
                "data_version": snapshot.data_version,
                "manifest_hash": snapshot.manifest_hash,
                "current": snapshot.data_version == current,
            }
            for snapshot in snapshots
        ]

    def validate(self, data_version: str, *, published: bool = False) -> DomainProductSnapshot:
        root = (self.versions_root if published else self.staging_root) / _safe(data_version)
        return self.validate_path(root)

    def validate_path(self, root: Path | str) -> DomainProductSnapshot:
        root = Path(root).resolve()
        try:
            manifest = json.loads((root / "data_manifest.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductPackValidationError("data manifest is unavailable") from exc
        if manifest.get("manifest_schema_version") != DOMAIN_MANIFEST_VERSION:
            raise ProductPackValidationError("domain data manifest is incompatible")
        data_version = _safe(str(manifest.get("data_version", "")))
        artifacts = manifest.get("artifact_sha256")
        required_artifacts = {
            "products.jsonl", "source_records.jsonl", "evidence_records.jsonl",
            "price_observations.jsonl", "evidence_ledger.jsonl", "products.sqlite",
            "vector_documents.jsonl", "index_manifest.json",
        }
        if not isinstance(artifacts, dict) or not required_artifacts <= set(artifacts):
            raise ProductPackValidationError("required artifact hashes are incomplete")
        fact_cards = [name for name in artifacts if name.startswith("fact_cards/")]
        if len(fact_cards) != manifest.get("fact_card_count"):
            raise ProductPackValidationError("fact card artifact count differs")
        for relative, expected in artifacts.items():
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise ProductPackValidationError("artifact path escaped data version") from exc
            if not candidate.is_file() or _sha(candidate) != expected:
                raise ProductPackValidationError("artifact hash validation failed")
        connection = sqlite3.connect(root / "products.sqlite")
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "products", "product_attributes", "source_records",
                    "evidence_records", "price_observations",
                )
            }
            brand_count = connection.execute(
                "SELECT COUNT(DISTINCT brand) FROM products"
            ).fetchone()[0]
        finally:
            connection.close()
        if integrity != "ok" or foreign_keys or counts != manifest.get("counts"):
            raise ProductPackValidationError("SQLite integrity, foreign keys, or counts differ")
        index = manifest.get("index", {})
        if (
            index.get("status") != "documents_ready"
            or index.get("embedding_model") != "text-embedding-v4"
            or index.get("embedding_dimensions") != 1024
            or index.get("data_version") != data_version
            or index.get("document_count") != counts["products"]
            or manifest.get("configuration_count") != counts["products"]
            or manifest.get("brand_count") != brand_count
        ):
            raise ProductPackValidationError("unfinished index contract is invalid")
        try:
            index_artifact = json.loads(
                (root / "index_manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductPackValidationError("index manifest is unavailable") from exc
        if index_artifact != index:
            raise ProductPackValidationError("index manifest differs from data manifest")
        return DomainProductSnapshot(root, data_version, stable_json_hash(manifest), manifest)

    @staticmethod
    def require_completed_index(snapshot: DomainProductSnapshot) -> None:
        if snapshot.manifest["index"]["status"] != "completed":
            raise ProductPackValidationError("unfinished index cannot be queried")

    def _write_pointer(self, snapshot: DomainProductSnapshot, *, action: str) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        temporary = self.runtime_root / ".current.tmp"
        _write_json(
            temporary,
            {
                "data_version": snapshot.data_version,
                "manifest_hash": snapshot.manifest_hash,
                "action": action,
            },
        )
        os.replace(temporary, self.current_pointer)

    def _build(self, root: Path, loaded: LoadedProductPack) -> None:
        field_ids = loaded.domain_pack.pack.policies["product_pack"]["attribute_fields"]
        products = []
        for item in sorted(loaded.normalized_products, key=lambda row: row["product_id"]):
            products.append(
                {
                    "product_id": item["product_id"],
                    "domain_id": item["domain_id"],
                    "brand": item["brand"],
                    "model_name": item["model_name"],
                    "region": item["region"],
                    "variant_key": item["variant_key"],
                    "aliases": item["aliases"],
                    "status": item["status"],
                    "attributes": {field_id: item[field_id] for field_id in field_ids},
                }
            )
        sources = sorted(
            (
                {**source.model_dump(mode="json"), "uri": str(source.uri)}
                for source in loaded.document.sources
            ),
            key=lambda item: item["source_id"],
        )
        evidence = sorted(loaded.normalized_evidence, key=lambda item: item["evidence_id"])
        observations = sorted(
            (item.model_dump(mode="json") for item in loaded.document.observations),
            key=lambda item: item["observation_id"],
        )
        source_models = {
            item.source_id: item.model_dump(mode="json") for item in loaded.document.sources
        }
        ledger = governed_ledger_rows(
            base_evidence=[], base_sources={}, base_products={},
            pack_evidence=evidence, pack_sources=source_models,
            data_version=loaded.document.data_version,
        )
        _write_jsonl(root / "products.jsonl", products)
        _write_jsonl(root / "source_records.jsonl", sources)
        _write_jsonl(root / "evidence_records.jsonl", evidence)
        _write_jsonl(root / "price_observations.jsonl", observations)
        _write_jsonl(root / "evidence_ledger.jsonl", ledger)
        self._build_database(root / "products.sqlite", products, sources, evidence, observations)
        fact_cards = self._build_fact_cards(root / "fact_cards", products, sources, loaded)
        vector_documents = self._build_vector_documents(root, products, evidence, loaded)
        suffix = hashlib.sha256(loaded.document.data_version.encode()).hexdigest()[:12]
        index = {
            "status": "documents_ready",
            "data_version": loaded.document.data_version,
            "index_version": f"{loaded.document.domain_id}-{suffix}-embedding1024-pending",
            "collection_name": f"proofpick_{loaded.document.domain_id}_{suffix}",
            "embedding_model": loaded.document.compatibility.embedding_model,
            "embedding_dimensions": loaded.document.compatibility.embedding_dimensions,
            "chunk_config_version": loaded.document.compatibility.chunk_config_version,
            "document_count": len(vector_documents),
            "vector_document_sha256": _sha(root / "vector_documents.jsonl"),
            "paid_index_build_performed": False,
        }
        _write_json(root / "index_manifest.json", index)
        artifact_names = [
            "products.jsonl", "source_records.jsonl", "evidence_records.jsonl",
            "price_observations.jsonl", "evidence_ledger.jsonl", "products.sqlite",
            "vector_documents.jsonl", "index_manifest.json",
            *[f"fact_cards/{path.name}" for path in fact_cards],
        ]
        artifact_hashes = {name: _sha(root / name) for name in artifact_names}
        counts = {
            "products": len(products),
            "product_attributes": sum(len(item["attributes"]) for item in products),
            "source_records": len(sources),
            "evidence_records": len(evidence),
            "price_observations": len(observations),
        }
        manifest = {
            "manifest_schema_version": DOMAIN_MANIFEST_VERSION,
            "schema_version": loaded.document.schema_version,
            "domain_id": loaded.document.domain_id,
            "domain_pack_version": loaded.domain_pack.version,
            "domain_pack_fingerprint": loaded.domain_pack.fingerprint,
            "product_pack_id": loaded.document.pack_id,
            "product_pack_version": loaded.document.pack_version,
            "product_pack_fingerprint": loaded.fingerprint,
            "base_data_version": loaded.document.base_data_version,
            "data_version": loaded.document.data_version,
            "created_at": loaded.document.created_at,
            "logical_data_sha256": stable_json_hash(
                {"products": products, "sources": sources, "evidence": evidence, "observations": observations}
            ),
            "counts": counts,
            "brand_count": len({item["brand"] for item in products}),
            "configuration_count": len(products),
            "fact_card_count": len(fact_cards),
            "ledger_count": len(ledger),
            "artifact_sha256": artifact_hashes,
            "index": index,
            "license": loaded.document.license.model_dump(mode="json"),
        }
        _write_json(root / "data_manifest.json", manifest)

    @staticmethod
    def _build_database(
        path: Path,
        products: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        observations: list[dict[str, Any]],
    ) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE products(product_id TEXT PRIMARY KEY, domain_id TEXT NOT NULL,
                  brand TEXT NOT NULL, model_name TEXT NOT NULL, region TEXT NOT NULL,
                  variant_key TEXT NOT NULL, aliases_json TEXT NOT NULL, status TEXT NOT NULL);
                CREATE TABLE product_attributes(product_id TEXT NOT NULL, field_id TEXT NOT NULL,
                  value_json TEXT, PRIMARY KEY(product_id, field_id),
                  FOREIGN KEY(product_id) REFERENCES products(product_id));
                CREATE TABLE source_records(source_id TEXT PRIMARY KEY, product_id TEXT NOT NULL,
                  source_type TEXT NOT NULL, title TEXT NOT NULL, uri TEXT NOT NULL,
                  publisher TEXT NOT NULL, is_official INTEGER NOT NULL, market TEXT NOT NULL,
                  variant_key TEXT NOT NULL, source_version TEXT NOT NULL, accessed_at TEXT NOT NULL,
                  redistribution_status TEXT NOT NULL,
                  FOREIGN KEY(product_id) REFERENCES products(product_id));
                CREATE TABLE evidence_records(evidence_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                  product_id TEXT NOT NULL, field_id TEXT NOT NULL, normalized_value_json TEXT,
                  unit TEXT, snippet TEXT NOT NULL, market TEXT NOT NULL, variant_key TEXT NOT NULL,
                  observed_at TEXT NOT NULL, conflict_group TEXT,
                  FOREIGN KEY(source_id) REFERENCES source_records(source_id),
                  FOREIGN KEY(product_id) REFERENCES products(product_id));
                CREATE TABLE price_observations(observation_id TEXT PRIMARY KEY,
                  product_id TEXT NOT NULL, source_id TEXT NOT NULL, price_cny REAL NOT NULL,
                  seller TEXT NOT NULL, market TEXT NOT NULL, observed_at TEXT NOT NULL,
                  FOREIGN KEY(source_id) REFERENCES source_records(source_id),
                  FOREIGN KEY(product_id) REFERENCES products(product_id));
                """
            )
            for product in products:
                connection.execute(
                    "INSERT INTO products VALUES (?,?,?,?,?,?,?,?)",
                    (
                        product["product_id"], product["domain_id"], product["brand"],
                        product["model_name"], product["region"], product["variant_key"],
                        _canonical(product["aliases"]), product["status"],
                    ),
                )
                connection.executemany(
                    "INSERT INTO product_attributes VALUES (?,?,?)",
                    [(product["product_id"], key, _canonical(value)) for key, value in sorted(product["attributes"].items())],
                )
            connection.executemany(
                "INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        item["source_id"], item["product_id"], item["source_type"], item["title"],
                        item["uri"], item["publisher"], int(item["is_official"]), item["market"],
                        item["variant_key"], item["source_version"], item["accessed_at"],
                        item["redistribution_status"],
                    )
                    for item in sources
                ],
            )
            connection.executemany(
                "INSERT INTO evidence_records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        item["evidence_id"], item["source_id"], item["product_id"], item["field_id"],
                        _canonical(item["normalized_value"]), item["unit"], item["snippet"],
                        item["market"], item["variant_key"], item["observed_at"], item["conflict_group"],
                    )
                    for item in evidence
                ],
            )
            connection.executemany(
                "INSERT INTO price_observations VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        item["observation_id"], item["product_id"], item["source_id"],
                        item["price_cny"], item["seller"], item["market"], item["observed_at"],
                    )
                    for item in observations
                ],
            )
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _build_fact_cards(
        root: Path,
        products: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        loaded: LoadedProductPack,
    ) -> list[Path]:
        root.mkdir(parents=True, exist_ok=True)
        labels = {item.field_id: item.label for item in loaded.domain_pack.pack.fields}
        source_by_product: dict[str, list[dict[str, Any]]] = {}
        for source in sources:
            source_by_product.setdefault(source["product_id"], []).append(source)
        paths = []
        for product in products:
            lines = [
                f"# {product['model_name']}", "", f"- product_id: `{product['product_id']}`",
                f"- region: `{product['region']}`", f"- configuration: `{product['variant_key']}`",
                "", "## 治理字段", "",
            ]
            for field_id, value in product["attributes"].items():
                lines.append(f"- {labels.get(field_id, field_id)}: {value if value is not None else 'unknown'}")
            lines.extend(["", "## 来源", ""])
            for source in source_by_product[product["product_id"]]:
                lines.append(f"- [{source['title']}]({source['uri']})（{source['source_type']}）")
            path = root / f"{product['product_id']}.md"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
            paths.append(path)
        return paths

    @staticmethod
    def _build_vector_documents(
        root: Path,
        products: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        loaded: LoadedProductPack,
    ) -> list[dict[str, Any]]:
        evidence_by_product: dict[str, list[dict[str, Any]]] = {}
        for item in evidence:
            evidence_by_product.setdefault(item["product_id"], []).append(item)
        documents = []
        for product in products:
            rows = evidence_by_product[product["product_id"]]
            documents.append(
                {
                    "doc_id": f"{product['product_id']}-facts",
                    "content": "\n".join(
                        f"{item['field_id']}: {item['normalized_value']} (evidence={item['evidence_id']})"
                        for item in rows
                    ),
                    "metadata": {
                        "domain_id": loaded.document.domain_id,
                        "product_id": product["product_id"], "brand": product["brand"],
                        "region": product["region"], "variant_key": product["variant_key"],
                        "data_version": loaded.document.data_version,
                        "domain_pack_version": loaded.domain_pack.version,
                        "evidence_ids": [item["evidence_id"] for item in rows],
                        "embedding_model": loaded.document.compatibility.embedding_model,
                        "embedding_dimensions": loaded.document.compatibility.embedding_dimensions,
                    },
                }
            )
        _write_jsonl(root / "vector_documents.jsonl", documents)
        return documents
