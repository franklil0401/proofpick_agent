"""Transactional Product Pack staging, validation, publication, and rollback."""

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

from smartbuy.data.derive import display_value, evidence_rows, source_rows
from smartbuy.data.loader import CATALOG_PATH, load_catalog, stable_json_hash
from smartbuy.db.build_database import database_summary
from smartbuy.product_packs.ledger import governed_ledger_rows
from smartbuy.product_packs.loader import (
    DEFAULT_DOMAIN_PACK,
    LoadedProductPack,
    ProductPackLoader,
    ProductPackValidationError,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "smartbuy" / "db" / "schema_v1.sql"
PRODUCT_COLUMNS = (
    "model_id",
    "brand",
    "model_name",
    "region",
    "display_size_inch",
    "resolution",
    "refresh_rate_hz",
    "panel_type",
    "is_oled",
    "has_usb_c",
    "usb_c_video",
    "usb_c_power_delivery_w",
    "stand_adjustment",
    "width_mm",
    "weight_kg",
    "warranty",
    "release_date",
    "official_source_id",
    "source_updated_at",
)
MANIFEST_SCHEMA_VERSION = "proofpick-data-manifest-v1"
DEFAULT_INDEX_VERSION = "monitor-multi-region-h2-v2-embedding1024-r1"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _file_sha256(path: Path) -> str:
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
    text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def _inside_project(path: Path) -> bool:
    try:
        path.resolve().relative_to(PROJECT_ROOT.resolve())
        return True
    except ValueError:
        return False


def _safe_version(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise ProductPackValidationError("data version is not filesystem-safe")
    return value


def _insert_rows(
    connection: sqlite3.Connection,
    table: str,
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    columns = list(rows[0])
    placeholders = ",".join("?" for _ in columns)
    values = []
    for row in rows:
        values.append(
            tuple(
                _canonical(row[column])
                if table == "evidence_records" and column == "normalized_value"
                else row[column]
                for column in columns
            )
        )
    connection.executemany(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
        values,
    )


@dataclass(frozen=True)
class PublishedProductSnapshot:
    root: Path
    data_version: str
    manifest_hash: str
    manifest: dict[str, Any]

    @property
    def database_path(self) -> Path:
        return self.root / "smartbuy.sqlite"

    @property
    def evidence_path(self) -> Path:
        return self.root / "evidence_records.jsonl"

    @property
    def sources_path(self) -> Path:
        return self.root / "source_records.jsonl"

    @property
    def fact_card_dir(self) -> Path:
        return self.root / "fact_cards"

    @property
    def index_dir(self) -> Path:
        return self.root / "index"

    @property
    def collection_name(self) -> str:
        return str(self.manifest["index"]["collection_name"])


class ProductPackManager:
    def __init__(
        self,
        runtime_root: Path | str,
        *,
        domain_pack_path: Path = DEFAULT_DOMAIN_PACK,
        base_catalog_path: Path = CATALOG_PATH,
    ) -> None:
        self.runtime_root = Path(runtime_root).resolve()
        if _inside_project(self.runtime_root):
            raise ValueError("Product Pack runtime root must stay outside the Git workspace")
        self.domain_pack_path = Path(domain_pack_path)
        self.base_catalog_path = Path(base_catalog_path)
        self.staging_root = self.runtime_root / "staging"
        self.versions_root = self.runtime_root / "versions"
        self.current_pointer = self.runtime_root / "current.json"

    def stage(self, pack_path: Path | str) -> PublishedProductSnapshot:
        loaded = ProductPackLoader(
            domain_pack_path=self.domain_pack_path,
            base_catalog_path=self.base_catalog_path,
        ).load(pack_path)
        data_version = _safe_version(loaded.document.data_version)
        self.staging_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".build-", dir=self.staging_root)).resolve()
        try:
            self._build(temporary, loaded)
            snapshot = self.validate_path(temporary)
            target = (self.staging_root / data_version).resolve()
            if target.parent != self.staging_root.resolve():
                raise ProductPackValidationError("staging path escaped runtime root")
            if target.exists():
                existing = self.validate_path(target)
                if existing.manifest_hash != snapshot.manifest_hash:
                    raise ProductPackValidationError("staged data version already has different content")
                return existing
            os.replace(temporary, target)
            return self.validate_path(target)
        finally:
            if temporary.exists() and temporary.parent == self.staging_root.resolve():
                shutil.rmtree(temporary)

    def validate(self, data_version: str, *, published: bool = False) -> PublishedProductSnapshot:
        version = _safe_version(data_version)
        root = (self.versions_root if published else self.staging_root) / version
        return self.validate_path(root)

    def publish(self, data_version: str) -> PublishedProductSnapshot:
        version = _safe_version(data_version)
        staged = self.validate(version)
        self.versions_root.mkdir(parents=True, exist_ok=True)
        target = (self.versions_root / version).resolve()
        if target.parent != self.versions_root.resolve():
            raise ProductPackValidationError("published path escaped runtime root")
        if target.exists():
            published = self.validate_path(target)
            if published.manifest_hash != staged.manifest_hash:
                raise ProductPackValidationError("published data version already differs")
        else:
            os.replace(staged.root, target)
            published = self.validate_path(target)
        previous = self._read_pointer().get("data_version") if self.current_pointer.exists() else None
        self._write_pointer(published, previous=previous, action="publish")
        return published

    def rollback(self, data_version: str) -> PublishedProductSnapshot:
        target = self.validate(data_version, published=True)
        current = self._read_pointer()
        self._write_pointer(
            target,
            previous=current.get("data_version"),
            action="rollback",
        )
        return target

    def current(self) -> PublishedProductSnapshot:
        pointer = self._read_pointer()
        snapshot = self.validate(str(pointer["data_version"]), published=True)
        if snapshot.manifest_hash != pointer.get("manifest_hash"):
            raise ProductPackValidationError("published pointer hash differs from version")
        return snapshot

    def list_versions(self) -> list[dict[str, Any]]:
        current = self._read_pointer().get("data_version") if self.current_pointer.exists() else None
        if not self.versions_root.exists():
            return []
        output = []
        for path in sorted(item for item in self.versions_root.iterdir() if item.is_dir()):
            snapshot = self.validate_path(path)
            output.append(
                {
                    "data_version": snapshot.data_version,
                    "manifest_hash": snapshot.manifest_hash,
                    "current": snapshot.data_version == current,
                }
            )
        return output

    def validate_path(self, root: Path | str) -> PublishedProductSnapshot:
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            raise ProductPackValidationError("data version directory is missing")
        manifest_path = root_path / "data_manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductPackValidationError("data manifest is missing or damaged") from exc
        if manifest.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION:
            raise ProductPackValidationError("data manifest schema is incompatible")
        data_version = _safe_version(str(manifest.get("data_version", "")))
        if root_path.name.startswith(".build-") is False and root_path.name != data_version:
            raise ProductPackValidationError("directory and data versions differ")
        artifact_hashes = manifest.get("artifact_sha256", {})
        if not isinstance(artifact_hashes, dict) or not artifact_hashes:
            raise ProductPackValidationError("artifact hash map is missing")
        for relative, expected in artifact_hashes.items():
            candidate = (root_path / relative).resolve()
            try:
                candidate.relative_to(root_path)
            except ValueError as exc:
                raise ProductPackValidationError("artifact path escaped data version") from exc
            if not candidate.is_file() or _file_sha256(candidate) != expected:
                raise ProductPackValidationError("artifact hash validation failed")
        database = root_path / "smartbuy.sqlite"
        summary = database_summary(database)
        if summary["integrity"] != "ok" or summary["foreign_key_violations"] != 0:
            raise ProductPackValidationError("SQLite integrity or foreign key validation failed")
        if summary["logical_sha256"] != manifest.get("sqlite_logical_sha256"):
            raise ProductPackValidationError("SQLite logical hash differs")
        if summary["counts"] != manifest.get("counts"):
            raise ProductPackValidationError("SQLite counts differ from manifest")
        index = manifest.get("index", {})
        if (
            index.get("embedding_model") != "text-embedding-v4"
            or index.get("embedding_dimensions") != 1024
            or index.get("data_version") != data_version
            or index.get("index_version") != DEFAULT_INDEX_VERSION
            or index.get("status") not in {"documents_ready", "completed"}
        ):
            raise ProductPackValidationError("index contract differs from data version")
        try:
            index_metadata = json.loads(
                (root_path / "index" / "metadata.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductPackValidationError("index metadata is unavailable") from exc
        if any(
            index_metadata.get(key) != index.get(key)
            for key in (
                "status",
                "data_version",
                "index_version",
                "collection_name",
                "embedding_model",
                "embedding_dimensions",
                "vector_document_sha256",
            )
        ):
            raise ProductPackValidationError("index metadata and manifest differ")
        manifest_hash = stable_json_hash(manifest)
        return PublishedProductSnapshot(
            root=root_path,
            data_version=data_version,
            manifest_hash=manifest_hash,
            manifest=manifest,
        )

    def _build(self, root: Path, loaded: LoadedProductPack) -> None:
        catalog = load_catalog(self.base_catalog_path)
        products = [dict(item) for item in catalog.products]
        products.extend(
            {key: item[key] for key in PRODUCT_COLUMNS}
            for item in loaded.normalized_products
        )
        products = sorted(products, key=lambda item: item["model_id"])
        base_source_rows = source_rows(catalog)
        pack_source_models = {
            item.source_id: item.model_dump(mode="json")
            for item in loaded.document.sources
        }
        pack_source_rows = [self._source_row(item) for item in pack_source_models.values()]
        sources = sorted([*base_source_rows, *pack_source_rows], key=lambda item: item["source_id"])
        base_evidence = evidence_rows(catalog)
        pack_evidence = [self._evidence_row(item) for item in loaded.normalized_evidence]
        evidence = sorted([*base_evidence, *pack_evidence], key=lambda item: item["evidence_id"])
        observations = [dict(item) for item in catalog.price_observations]
        observations.extend(
            {
                "observation_id": item.observation_id,
                "model_id": item.product_id,
                "price_cny": item.price_cny,
                "seller": item.seller,
                "region": item.market,
                "stock_status": item.stock_status,
                "url": str(item.uri),
                "observed_at": item.observed_at,
                "price_type": item.price_type,
            }
            for item in loaded.document.observations
        )
        observations = sorted(observations, key=lambda item: item["observation_id"])
        base_sources = {item["source_id"]: item for item in catalog.source_records}
        base_products = {item["model_id"]: item for item in catalog.products}
        ledger = governed_ledger_rows(
            base_evidence=base_evidence,
            base_sources=base_sources,
            base_products=base_products,
            pack_evidence=loaded.normalized_evidence,
            pack_sources=pack_source_models,
            data_version=loaded.document.data_version,
        )
        _write_jsonl(root / "products.jsonl", products)
        _write_jsonl(root / "source_records.jsonl", sources)
        _write_jsonl(root / "evidence_records.jsonl", evidence)
        _write_jsonl(root / "price_observations.jsonl", observations)
        _write_jsonl(root / "evidence_ledger.jsonl", ledger)
        self._build_database(
            root / "smartbuy.sqlite",
            products,
            sources,
            observations,
            evidence,
            loaded,
        )
        fact_cards = self._build_fact_cards(
            root / "fact_cards",
            products,
            sources,
            observations,
            loaded.document.data_version,
        )
        vector_documents = self._build_vector_documents(
            root,
            products,
            sources,
            fact_cards,
            loaded,
        )
        collection_suffix = hashlib.sha256(
            loaded.document.data_version.encode("utf-8")
        ).hexdigest()[:12]
        index_manifest = {
            "status": "documents_ready",
            "data_version": loaded.document.data_version,
            "index_version": DEFAULT_INDEX_VERSION,
            "domain_id": loaded.document.domain_id,
            "collection_name": f"proofpick_monitor_{collection_suffix}",
            "embedding_model": loaded.document.compatibility.embedding_model,
            "embedding_dimensions": loaded.document.compatibility.embedding_dimensions,
            "chunk_config_version": loaded.document.compatibility.chunk_config_version,
            "document_count": len(vector_documents),
            "vector_document_sha256": _file_sha256(root / "vector_documents.jsonl"),
            "requires_new_index": True,
            "paid_index_build_performed": False,
        }
        _write_json(root / "index_manifest.json", index_manifest)
        _write_json(
            root / "index" / "metadata.json",
            {
                "status": "documents_ready",
                "data_version": loaded.document.data_version,
                "index_version": index_manifest["index_version"],
                "collection_name": index_manifest["collection_name"],
                "embedding_model": index_manifest["embedding_model"],
                "embedding_dimensions": index_manifest["embedding_dimensions"],
                "vector_document_sha256": index_manifest["vector_document_sha256"],
            },
        )
        database = database_summary(root / "smartbuy.sqlite")
        artifacts = [
            "products.jsonl",
            "source_records.jsonl",
            "evidence_records.jsonl",
            "price_observations.jsonl",
            "evidence_ledger.jsonl",
            "smartbuy.sqlite",
            "vector_documents.jsonl",
            "index_manifest.json",
            "index/metadata.json",
            *[f"fact_cards/{path.name}" for path in sorted((root / "fact_cards").glob("*.md"))],
        ]
        artifact_hashes = {relative: _file_sha256(root / relative) for relative in artifacts}
        logical = {
            "products": products,
            "sources": sources,
            "evidence": evidence,
            "observations": observations,
            "ledger": ledger,
        }
        manifest = {
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "schema_version": loaded.document.schema_version,
            "domain_id": loaded.document.domain_id,
            "domain_pack_version": loaded.document.compatibility.domain_pack_version,
            "product_pack_id": loaded.document.pack_id,
            "product_pack_version": loaded.document.pack_version,
            "product_pack_fingerprint": loaded.fingerprint,
            "base_data_version": loaded.document.base_data_version,
            "data_version": loaded.document.data_version,
            "created_at": loaded.document.created_at,
            "logical_data_sha256": stable_json_hash(logical),
            "sqlite_logical_sha256": database["logical_sha256"],
            "counts": database["counts"],
            "brand_count": len({item["brand"] for item in products}),
            "fact_card_count": len(fact_cards),
            "ledger_count": len(ledger),
            "artifact_sha256": artifact_hashes,
            "index": index_manifest,
            "license": loaded.document.license.model_dump(mode="json"),
        }
        _write_json(root / "data_manifest.json", manifest)

    @staticmethod
    def _source_row(source: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_id": source["source_id"],
            "model_id": source["product_id"],
            "source_type": source["source_type"],
            "title": source["title"],
            "url": str(source["uri"]),
            "is_official": source["is_official"],
            "region": source["market"],
            "published_at": source["published_at"],
            "accessed_at": source["accessed_at"],
            "content_hash": source["content_hash"],
            "redistribution_status": source["redistribution_status"],
            "notes": (
                f"variant={source['variant_key']}; source_version={source['source_version']}; "
                f"治理摘要：{source['governed_summary']}"
            ),
        }

    @staticmethod
    def _evidence_row(evidence: dict[str, Any]) -> dict[str, Any]:
        return {
            "evidence_id": evidence["evidence_id"],
            "source_id": evidence["source_id"],
            "model_id": evidence["product_id"],
            "normalized_field": evidence["field_id"],
            "normalized_value": evidence["normalized_value"],
            "original_value": str(evidence["raw_value"]),
            "evidence_location": (
                f"{evidence['evidence_location']}；自制摘要：{evidence['snippet']}"
            ),
            "confidence_level": evidence["confidence"],
            "effective_time": evidence["effective_at"] or evidence["observed_at"],
            "conflict_group": evidence["conflict_group"],
        }

    @staticmethod
    def _build_database(
        output: Path,
        products: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        observations: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        loaded: LoadedProductPack,
    ) -> None:
        connection = sqlite3.connect(str(output))
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            with connection:
                _insert_rows(connection, "products", products)
                _insert_rows(connection, "source_records", sources)
                _insert_rows(connection, "price_observations", observations)
                _insert_rows(connection, "evidence_records", evidence)
                metadata = {
                    "schema_version": loaded.document.schema_version,
                    "data_version": loaded.document.data_version,
                    "domain_pack_version": loaded.document.compatibility.domain_pack_version,
                    "product_pack_version": loaded.document.pack_version,
                    "embedding_model": loaded.document.compatibility.embedding_model,
                    "embedding_dimensions": str(
                        loaded.document.compatibility.embedding_dimensions
                    ),
                }
                connection.executemany(
                    "INSERT INTO metadata(key,value) VALUES (?,?)",
                    sorted(metadata.items()),
                )
        finally:
            connection.close()

    @staticmethod
    def _build_fact_cards(
        output: Path,
        products: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        observations: list[dict[str, Any]],
        data_version: str,
    ) -> dict[str, str]:
        output.mkdir(parents=True, exist_ok=True)
        sources_by_product: dict[str, list[dict[str, Any]]] = {}
        for source in sources:
            sources_by_product.setdefault(source["model_id"], []).append(source)
        prices_by_product: dict[str, list[dict[str, Any]]] = {}
        for observation in observations:
            prices_by_product.setdefault(observation["model_id"], []).append(observation)
        cards: dict[str, str] = {}
        for product in products:
            model_id = product["model_id"]
            source_list = sorted(
                sources_by_product.get(model_id, []),
                key=lambda item: item["source_id"],
            )
            source_lines = "\n".join(
                f"- [{item['title']}]({item['url']})（{item['region']}，访问 {item['accessed_at']}）"
                for item in source_list
            )
            price_rows = sorted(
                prices_by_product.get(model_id, []),
                key=lambda item: (item["observed_at"], item["observation_id"]),
                reverse=True,
            )
            price = price_rows[0] if price_rows else None
            price_text = "未知（没有可核验的价格观察）"
            if price:
                price_text = (
                    f"CNY {price['price_cny']:.2f}；{price['seller']}；"
                    f"观察时间 {price['observed_at']}。该价格不是实时数据。"
                )
            unknowns = [
                field
                for field in (
                    "display_size_inch",
                    "resolution",
                    "refresh_rate_hz",
                    "panel_type",
                    "is_oled",
                    "has_usb_c",
                    "usb_c_video",
                    "usb_c_power_delivery_w",
                    "stand_adjustment",
                    "width_mm",
                    "weight_kg",
                    "warranty",
                    "release_date",
                )
                if product[field] is None
            ]
            card = f"""# {product['brand']} {product['model_name']}（{product['region']}）

> 自制事实卡；数据版本 `{data_version}`。仅含结构化概括和来源链接。

## 型号与显示

- 稳定型号 ID：`{model_id}`
- 地区/版本：{product['region']}
- 尺寸：{display_value('display_size_inch', product['display_size_inch'])}
- 分辨率：{display_value('resolution', product['resolution'])}
- 刷新率：{display_value('refresh_rate_hz', product['refresh_rate_hz'])}
- 面板：{display_value('panel_type', product['panel_type'])}；OLED：{display_value('is_oled', product['is_oled'])}

## USB-C 与接口判断

- 有 USB-C：{display_value('has_usb_c', product['has_usb_c'])}
- USB-C 视频输入：{display_value('usb_c_video', product['usb_c_video'])}
- USB-C 供电：{display_value('usb_c_power_delivery_w', product['usb_c_power_delivery_w'])}

## 支架与机身

- 支架：{display_value('stand_adjustment', product['stand_adjustment'])}
- 宽度：{display_value('width_mm', product['width_mm'])}
- 重量：{display_value('weight_kg', product['weight_kg'])}

## 价格与时间边界

{price_text}

## 来源与未知项

{source_lines}

- 当前未知字段：{'、'.join(unknowns) if unknowns else '无'}。
- 不同地区/配置版本不自动合并；null 不使用 0 替代。
"""
            cards[model_id] = card
            (output / f"{model_id}.md").write_text(
                card,
                encoding="utf-8",
                newline="\n",
            )
        return cards

    @staticmethod
    def _build_vector_documents(
        root: Path,
        products: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        cards: dict[str, str],
        loaded: LoadedProductPack,
    ) -> list[dict[str, Any]]:
        product_by_id = {item["model_id"]: item for item in products}
        source_by_id = {item["source_id"]: item for item in sources}
        pack_product_by_id = {
            item["model_id"]: item for item in loaded.normalized_products
        }
        pack_source_by_id = {
            item.source_id: item for item in loaded.document.sources
        }
        documents: list[dict[str, Any]] = []
        for model_id in sorted(cards):
            product = product_by_id[model_id]
            source = source_by_id[product["official_source_id"]]
            pack_product = pack_product_by_id.get(model_id)
            pack_source = pack_source_by_id.get(source["source_id"])
            variant_key = (
                str(pack_product["variant_key"])
                if pack_product is not None
                else f"{model_id}-v1"
            )
            source_version = (
                pack_source.source_version
                if pack_source is not None
                else "v1-governed-capture"
            )
            aliases = (
                [model_id, product["model_name"], *pack_product["aliases"]]
                if pack_product is not None
                else [model_id, product["model_name"]]
            )
            card = cards[model_id]
            matches = list(re.finditer(r"^##\s+(.+?)\s*$", card, flags=re.MULTILINE))
            for index, match in enumerate(matches, start=1):
                end = matches[index].start() if index < len(matches) else len(card)
                section = match.group(1).strip()
                body = card[match.end() : end].strip()
                doc_id = f"{model_id}--s{index:02d}"
                documents.append(
                    {
                        "doc_id": doc_id,
                        "content": (
                            f"型号：{product['brand']} {product['model_name']}"
                            f"（{product['region']}）\n"
                            f"稳定 ID：{model_id}\n配置版：{variant_key}\n"
                            f"来源版本：{source_version}\n别名：{'；'.join(aliases)}\n"
                            f"章节：{section}\n{body}"
                        ),
                        "metadata": {
                            "doc_id": doc_id,
                            "model_id": model_id,
                            "brand": product["brand"],
                            "region_version": product["region"],
                            "variant_key": variant_key,
                            "source_version": source_version,
                            "aliases": " | ".join(aliases),
                            "source_id": source["source_id"],
                            "source_type": source["source_type"],
                            "source_url": source["url"],
                            "section_page": section,
                            "accessed_at": source["accessed_at"],
                            "chunk_config_version": (
                                loaded.document.compatibility.chunk_config_version
                            ),
                            "embedding_model": (
                                loaded.document.compatibility.embedding_model
                            ),
                            "embedding_dimensions": (
                                loaded.document.compatibility.embedding_dimensions
                            ),
                            "data_version": loaded.document.data_version,
                            "schema_version": loaded.document.schema_version,
                        },
                    }
                )
        _write_jsonl(root / "vector_documents.jsonl", documents)
        return documents

    def _read_pointer(self) -> dict[str, Any]:
        try:
            pointer = json.loads(self.current_pointer.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductPackValidationError("published Product Pack pointer is unavailable") from exc
        if set(pointer) != {
            "action",
            "data_version",
            "manifest_hash",
            "previous_data_version",
        }:
            raise ProductPackValidationError("published pointer schema is invalid")
        return pointer

    def _write_pointer(
        self,
        snapshot: PublishedProductSnapshot,
        *,
        previous: str | None,
        action: str,
    ) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "action": action,
            "data_version": snapshot.data_version,
            "manifest_hash": snapshot.manifest_hash,
            "previous_data_version": previous,
        }
        temporary = self.runtime_root / ".current.json.tmp"
        _write_json(temporary, payload)
        os.replace(temporary, self.current_pointer)
