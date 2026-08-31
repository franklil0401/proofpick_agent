"""End-to-end offline Product Pack build, tools, publication, and rollback."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from smartbuy.config import BailianSettings
from smartbuy.constraints import CandidateConstraintVerifier, ConstraintNormalizer
from smartbuy.product_packs import (
    ProductPackManager,
    ProductPackRuntimeSettings,
    ProductPackValidationError,
    resolve_product_snapshot,
)
from smartbuy.product_packs.cli import main as product_pack_cli
from smartbuy.tools import EvidenceCheckTool, KBSearchTool, Text2SQLTool


EXAMPLE = (
    Path(__file__).resolve().parents[2]
    / "product_packs/examples/monitor-u2725qe-us/pack.json"
)
DATA_VERSION = "monitor-multi-region-2026-08-31-v2"


def _derived_pack(tmp_path: Path, *, suffix: str, pack_version: str = "1.0.1") -> Path:
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    payload["pack_version"] = pack_version
    payload["data_version"] = f"{DATA_VERSION}-{suffix}"
    path = tmp_path / suffix / "pack.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_two_builds_are_idempotent_and_sqlite_is_consistent(tmp_path):
    first = ProductPackManager(tmp_path / "runtime-a").stage(EXAMPLE)
    second = ProductPackManager(tmp_path / "runtime-b").stage(EXAMPLE)
    assert first.manifest_hash == second.manifest_hash
    assert first.manifest["logical_data_sha256"] == second.manifest["logical_data_sha256"]
    assert first.manifest["artifact_sha256"] == second.manifest["artifact_sha256"]
    assert first.manifest["counts"] == {
        "products": 13,
        "price_observations": 4,
        "source_records": 17,
        "evidence_records": 196,
    }
    assert first.manifest["brand_count"] == 4
    assert first.manifest["fact_card_count"] == 13
    assert first.manifest["ledger_count"] == 196
    assert first.manifest["index"]["document_count"] == 65
    assert first.manifest["index"]["embedding_dimensions"] == 1024
    ledger = _read_jsonl(first.root / "evidence_ledger.jsonl")
    assert len(ledger) == 196
    assert all(
        item["source_id"]
        and item["snippet"]
        and item["market"]
        and item["variant_key"]
        and item["source_version"]
        and item["observed_at"]
        and item["trust_state"] == "governed"
        for item in ledger
    )
    new_ledger = [item for item in ledger if item["product_id"] == "dell-u2725qe-us"]
    assert len(new_ledger) == 16
    assert {item["redistribution_status"] for item in new_ledger} == {
        "metadata_and_summary_only"
    }
    connection = sqlite3.connect(first.database_path)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT value FROM metadata WHERE key='data_version'"
        ).fetchone()[0] == DATA_VERSION
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_thirteenth_monitor_is_used_by_sql_evidence_kb_and_checker(tmp_path):
    snapshot = ProductPackManager(tmp_path / "runtime").stage(EXAMPLE)
    sql_result = await Text2SQLTool(snapshot.database_path).invoke(
        {
            "sql": "",
            "filters": [
                {"field": "model_id", "operator": "eq", "value": "U2725QE"},
                {"field": "usb_c_power_delivery_w", "operator": "gte", "value": 140},
            ],
            "reason": "验证第十三个型号",
            "_deterministic_filters": True,
        }
    )
    assert sql_result.status == "success"
    assert [row["model_id"] for row in sql_result.data["rows"]] == ["dell-u2725qe-us"]

    evidence_result = await EvidenceCheckTool(snapshot.database_path).invoke(
        {
            "model_ids": ["dell-u2725qe-us"],
            "required_fields": [
                "display_size_inch",
                "resolution",
                "usb_c_video",
                "usb_c_power_delivery_w",
            ],
            "constraints": [
                {"field": "usb_c_power_delivery_w", "operator": "gte", "value": 140}
            ],
            "reason": "核验字段级证据",
        }
    )
    assert evidence_result.status == "success"
    assert evidence_result.data["status_counts"]["matched"] == 4

    constraints = ConstraintNormalizer().build(
        "美国版 27 英寸 4K、非 OLED、USB-C 视频且供电至少 140W",
        source_turn=1,
    )
    verification = CandidateConstraintVerifier(
        snapshot.database_path,
        as_of=datetime(2026, 8, 31, tzinfo=UTC),
    ).verify_candidates(constraints, ["dell-u2725qe-us"])
    assert verification.eligible_model_ids == ["dell-u2725qe-us"]

    documents = [
        item
        for item in _read_jsonl(snapshot.root / "vector_documents.jsonl")
        if item["metadata"]["model_id"] == "dell-u2725qe-us"
    ]

    class FakeStore:
        async def count(self):
            return len(documents)

        async def search(self, _vector, top_k):
            return [
                (
                    SimpleNamespace(
                        id=item["doc_id"],
                        content=item["content"],
                        metadata=item["metadata"],
                    ),
                    1.0 - index * 0.01,
                )
                for index, item in enumerate(documents[:top_k])
            ]

    class FakeProvider:
        async def embed(self, _texts):
            return SimpleNamespace(data=[[0.0] * 1024])

        async def rerank_or_fallback(self, _query, docs, *, top_n, vector_scores):
            return SimpleNamespace(
                data=[
                    {"index": index, "relevance_score": vector_scores[index]}
                    for index in range(min(top_n, len(docs)))
                ],
                degraded=False,
            )

    kb_result = await KBSearchTool(
        BailianSettings(api_key="test-only", workspace_id="ws-test"),
        FakeProvider(),
        store=FakeStore(),
        evidence_path=snapshot.evidence_path,
        sources_path=snapshot.sources_path,
        collection_name=snapshot.collection_name,
    ).invoke(
        {
            "query": "U2725QE 是否支持 140W 供电",
            "model_ids": ["dell-u2725qe-us"],
            "required_fields": ["usb_c_power_delivery_w"],
            "reason": "验证生成的向量文档与证据绑定",
        }
    )
    assert kb_result.status == "success"
    assert kb_result.data["hits"]
    assert {item["model_id"] for item in kb_result.data["hits"]} == {
        "dell-u2725qe-us"
    }
    assert any(item["evidence_bindings"] for item in kb_result.data["hits"])


def test_failed_publish_preserves_current_version(tmp_path):
    manager = ProductPackManager(tmp_path / "runtime")
    first = manager.publish(manager.stage(EXAMPLE).data_version)
    damaged_pack = _derived_pack(tmp_path, suffix="damaged")
    damaged = manager.stage(damaged_pack)
    damaged.evidence_path.write_text("damaged", encoding="utf-8")
    with pytest.raises(ProductPackValidationError, match="artifact hash"):
        manager.publish(damaged.data_version)
    assert manager.current().data_version == first.data_version
    assert manager.current().manifest_hash == first.manifest_hash


def test_publish_second_version_and_rollback_keeps_all_artifacts_aligned(tmp_path):
    manager = ProductPackManager(tmp_path / "runtime")
    first = manager.publish(manager.stage(EXAMPLE).data_version)
    second_pack = _derived_pack(tmp_path, suffix="revision-2")
    second = manager.publish(manager.stage(second_pack).data_version)
    assert manager.current().data_version == second.data_version
    rolled_back = manager.rollback(first.data_version)
    assert manager.current().manifest_hash == first.manifest_hash
    assert rolled_back.manifest["index"]["data_version"] == first.data_version
    index_metadata = json.loads(
        (rolled_back.index_dir / "metadata.json").read_text(encoding="utf-8")
    )
    assert index_metadata["data_version"] == first.data_version
    assert first.data_version in (
        rolled_back.fact_card_dir / "dell-u2725qe-us.md"
    ).read_text(encoding="utf-8")
    connection = sqlite3.connect(rolled_back.database_path)
    try:
        assert connection.execute(
            "SELECT value FROM metadata WHERE key='data_version'"
        ).fetchone()[0] == first.data_version
        assert connection.execute(
            "SELECT COUNT(*) FROM products WHERE model_id='dell-u2725qe-us'"
        ).fetchone()[0] == 1
    finally:
        connection.close()

    with pytest.raises(ProductPackValidationError, match="index is not completed"):
        resolve_product_snapshot(
            ProductPackRuntimeSettings(enabled=True, runtime_root=tmp_path / "runtime")
        )


def test_frozen_v1_catalog_and_evaluation_files_are_unchanged():
    expected = {
        "smartbuy/data/catalog/monitors_v1.json": (
            "b50fd4818575747dab00ffe922ea9720b3a7196e1a5162c0494cd6454a04210a"
        ),
        "smartbuy/eval/stage4_cases.jsonl": (
            "a25c8852887096d91da6758f64d69bd1e69bb30a413425a77883de03cea77a0f"
        ),
        "smartbuy/eval/stage6_natural_cases.jsonl": (
            "6082ac83d72441fedf7ac3083a3c53f31d538ca54216f2cf99d3a9de5068e0ef"
        ),
        "smartbuy/data/processed/stage6_four_group_results.json": (
            "b8546a19afa83efa3edfb009c99feacb48a613f7127dd6da59a951a4ae9b62ad"
        ),
        "smartbuy/data/processed/stage7_demo_results.json": (
            "ac476d5ab47c9f67e737b9cef9a8f11cb72b1130b2f5b8c19b356e139b598d9c"
        ),
    }
    import hashlib

    for relative, digest in expected.items():
        assert hashlib.sha256(Path(relative).read_bytes()).hexdigest() == digest
    demo = json.loads(Path("smartbuy/data/processed/stage7_demo_results.json").read_text(encoding="utf-8"))
    assert demo["demo_count"] == 4
    assert demo["passed"] == 4
    assert demo["all_passed"] is True


def test_cli_import_validate_publish_view_and_rollback(tmp_path, capsys):
    root = tmp_path / "cli-runtime"
    common = ["--runtime-root", str(root)]
    assert product_pack_cli([*common, "import", "--pack", str(EXAMPLE)]) == 0
    assert product_pack_cli([*common, "validate", "--data-version", DATA_VERSION]) == 0
    assert product_pack_cli([*common, "publish", "--data-version", DATA_VERSION]) == 0
    assert product_pack_cli([*common, "versions"]) == 0
    assert product_pack_cli([*common, "current"]) == 0
    assert product_pack_cli([*common, "rollback", "--data-version", DATA_VERSION]) == 0
    output = capsys.readouterr().out
    assert '"status": "completed"' in output
    assert DATA_VERSION in output
