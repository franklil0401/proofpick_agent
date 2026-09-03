"""V2-6B domain-neutral Laptop toolchain acceptance tests (offline)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from smartbuy.domain_packs import DomainPackLoader
from smartbuy.domain_packs.scope import DomainExecutionScope
from smartbuy.identity import ProductIdentityResolver
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.providers.bailian import BailianError, ProviderResult
from smartbuy.retrieval.domain_index import DomainIndexManager
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainKBSearchTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)


ROOT = Path(__file__).resolve().parents[3]
LAPTOP_DOMAIN = ROOT / "smartbuy" / "domain_packs" / "laptop"
LAPTOP_PACK = ROOT / "smartbuy" / "product_packs" / "examples" / "laptop-v1" / "pack.json"
LAPTOP_CASES = ROOT / "smartbuy" / "eval" / "v2_6a_laptop_cases.jsonl"
FROZEN_SHA = "3dfcc0f442bda2b6b4d2e96814a8973b415b3d8c8b9b33235924982fa1758d34"
RETRIEVAL_CASES = ROOT / "smartbuy" / "eval" / "v2_6b_laptop_retrieval_cases.jsonl"
RETRIEVAL_CASES_SHA256 = "7c70e4da196c17d3d09f6ee5c42162d16995963c2ee18c0c4254af55d6903e8c"
RETRIEVAL_FIRST = ROOT / "smartbuy" / "eval" / "results" / "v2_6b_laptop_retrieval_first.json"
RETRIEVAL_FIRST_SHA256 = "beb3a2c3801d8bdedf319d98374fc020513653175888a0476c0189b495788c39"


class FakeProvider:
    def __init__(self, *, fail_rerank: bool = False) -> None:
        self.fail_rerank = fail_rerank

    @staticmethod
    def _vector(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        return [float(digest[index % len(digest)]) / 255.0 for index in range(1024)]

    async def embed(self, texts):
        return ProviderResult([self._vector(text) for text in texts], 1, 1.0, {"input_tokens": len(texts)})

    async def rerank(self, _query, documents, *, top_n, instruct=None):
        del instruct
        if self.fail_rerank:
            raise BailianError("injected")
        return ProviderResult(
            [{"index": index, "relevance_score": 1.0 - index / 100} for index in range(min(top_n, len(documents)))],
            1, 1.0, {"input_tokens": len(documents)},
        )


def _runtime(tmp_path: Path):
    pack = DomainPackLoader().load(LAPTOP_DOMAIN)
    manager = DomainProductPackManager(tmp_path / "data", domain_pack_path=LAPTOP_DOMAIN)
    snapshot = manager.publish(manager.stage(LAPTOP_PACK).data_version)
    repository = DomainReadonlyRepository(snapshot, pack)
    return pack, manager, snapshot, repository


def test_product_query_is_read_only_pack_driven_and_keeps_unknown(tmp_path: Path) -> None:
    _, _, snapshot, repository = _runtime(tmp_path)
    tool = DomainProductQueryTool(repository)
    result = tool.run([
        {"field": "内存", "operator": "gte", "value": 32, "unit": "GB"},
        {"field": "硬盘", "operator": "gte", "value": 1, "unit": "TB"},
        {"field": "重量", "operator": "lte", "value": 1.6, "unit": "kg"},
    ])
    assert result.status == "success"
    assert result.data["candidate_pool_size"] == 12
    assert result.data["statement_count"] == 1 and result.data["read_only"] is True
    assert all(row["domain_id"] == "laptop" and row["data_version"] == snapshot.data_version for row in result.data["rows"])
    budget = tool.run([{"field": "价格", "operator": "lte", "value": 8000, "unit": "CNY"}])
    assert {row["status"] for row in budget.data["rows"]} == {"unknown"}
    assert tool.run([{"field": "usb_c_power_delivery_w", "operator": "gte", "value": 90}]).status == "failed"


def test_evidence_and_checker_preserve_four_state_fail_closed(tmp_path: Path) -> None:
    _, _, _, repository = _runtime(tmp_path)
    products = repository.load()
    product_id = next(key for key, value in products.items() if value["attributes"]["configuration_id"] == "H7606WX")
    constraints = [
        {"field": "memory_gb", "operator": "gte", "value": 32, "unit": "GB"},
        {"field": "usb4", "operator": "eq", "value": True},
    ]
    evidence = DomainEvidenceCheckTool(repository).run(product_id, constraints)
    assert evidence.status == "success"
    assert {row["state"] for row in evidence.data["field_results"]} == {"matched"}
    checker = DomainConstraintCheckerTool(repository).run(constraints)
    assert checker.status == "success" and checker.data["candidate_pool_size"] == 12
    assert all(row["evidence_ids"] for row in checker.data["results"] if row["eligible"])
    budget = DomainConstraintCheckerTool(repository).run(
        [{"field": "price_cny", "operator": "lte", "value": 8000, "unit": "CNY"}]
    )
    assert not any(row["eligible"] for row in budget.data["results"])
    assert all(row["unknown_fields"] == ["price_cny"] for row in budget.data["results"])
    invalid = DomainConstraintCheckerTool(repository).run(
        [{"field": "usb_c_power_delivery_w", "operator": "gte", "value": 90}]
    )
    assert invalid.status == "failed" and invalid.data["fail_closed"] is True


@pytest.mark.asyncio
async def test_domain_index_is_atomic_scoped_and_reranker_degrades(tmp_path: Path) -> None:
    pack, data_manager, snapshot, _ = _runtime(tmp_path)
    index = DomainIndexManager(
        tmp_path / "index", data_manager=data_manager, domain_id="laptop",
        domain_pack_version=pack.version,
    )
    built = await index.build(snapshot.data_version, "laptop-test-embedding1024", FakeProvider())
    assert built.manifest["document_count"] == built.manifest["chunk_count"] == 12
    assert built.manifest["embedding_dimensions"] == 1024
    index.activate(built.index_version)
    products = DomainReadonlyRepository(snapshot, pack).load()
    product_id = next(key for key, value in products.items() if value["attributes"]["configuration_id"] == "H7606WX")
    scope = ProductIdentityResolver(
        domain_id="laptop",
        data_version=snapshot.data_version,
        index_version=built.index_version,
    ).resolve("核验 H7606WX 接口", products)
    normal = await DomainKBSearchTool(index, FakeProvider()).run(
        "H7606WX 接口", product_id=product_id, configuration_id="H7606WX", scope=scope, top_k=5
    )
    assert normal.status == "success" and len(normal.data["hits"]) == 1
    assert normal.data["scope_fingerprint"] == scope.fingerprint
    hit = normal.data["hits"][0]
    assert hit["domain_id"] == "laptop" and hit["configuration_id"] == "H7606WX"
    degraded = await DomainKBSearchTool(index, FakeProvider(fail_rerank=True)).run(
        "H7606WX 接口", product_id=product_id, configuration_id="H7606WX", scope=scope, top_k=5
    )
    assert degraded.status == "degraded" and degraded.data["reranker_degraded"] is True
    assert degraded.data["hits"][0]["product_id"] == product_id
    outside = next(item for item in products if item not in scope.product_ids)
    rejected = await DomainKBSearchTool(index, FakeProvider()).run(
        "范围外配置", product_id=outside, scope=scope, top_k=5
    )
    assert rejected.status == "failed" and rejected.error_code == "kb_scope_mismatch"
    wrong_region = await DomainKBSearchTool(index, FakeProvider()).run(
        "H7606WX 接口", product_id=product_id, region="ZZ", top_k=5
    )
    assert wrong_region.status == "success" and wrong_region.data["hits"] == []
    pointer = index.current_pointer.read_text(encoding="utf-8")
    index.current_pointer.write_text(
        json.dumps({"domain_id": "monitor", "data_version": snapshot.data_version,
                    "index_version": built.index_version, "manifest_hash": built.manifest_hash}),
        encoding="utf-8",
    )
    failed = await DomainKBSearchTool(index, FakeProvider()).run("must fail closed")
    assert failed.status == "failed" and failed.error_code == "index_fail_closed"
    index.current_pointer.write_text(pointer, encoding="utf-8")
    assert index.rollback(built.index_version).manifest_hash == built.manifest_hash


def test_v2_6b_generic_modules_have_no_laptop_field_constants_and_holdout_unchanged() -> None:
    forbidden = {"cpu_model", "gpu_model", "memory_gb", "storage_gb", "battery_wh", "thunderbolt", "usb_c_charging"}
    for relative in ("smartbuy/tools/domain.py", "smartbuy/retrieval/domain_index.py"):
        words = set((ROOT / relative).read_text(encoding="utf-8").replace('"', " ").replace("'", " ").split())
        assert not (forbidden & words)
    assert hashlib.sha256(LAPTOP_CASES.read_bytes()).hexdigest() == FROZEN_SHA
    assert hashlib.sha256(RETRIEVAL_CASES.read_bytes()).hexdigest() == RETRIEVAL_CASES_SHA256
    assert hashlib.sha256(RETRIEVAL_FIRST.read_bytes()).hexdigest() == RETRIEVAL_FIRST_SHA256
    first = json.loads(RETRIEVAL_FIRST.read_text(encoding="utf-8"))
    assert first["case_count"] == 30 and first["frozen_agent_holdout_run"] is False
    assert first["metrics"]["cross_domain_hits"] == 0


def test_ten_tool_level_combinations_keep_complete_pool_and_checker_authority(tmp_path: Path) -> None:
    _, _, _, repository = _runtime(tmp_path)
    cases = [
        [{"field": "memory_gb", "operator": "gte", "value": 32, "unit": "GB"}, {"field": "storage_gb", "operator": "gte", "value": 1, "unit": "TB"}, {"field": "weight_kg", "operator": "lte", "value": 1.6, "unit": "kg"}],
        [{"field": "gpu_type", "operator": "eq", "value": "discrete"}, {"field": "storage_gb", "operator": "gte", "value": 2048, "unit": "GB"}],
        [{"field": "display_size_inch", "operator": "gte", "value": 15, "unit": "inch"}, {"field": "refresh_rate_hz", "operator": "gte", "value": 60, "unit": "Hz"}],
        [{"field": "usb_c", "operator": "eq", "value": True}, {"field": "usb4", "operator": "eq", "value": True}, {"field": "hdmi", "operator": "eq", "value": True}],
        [{"field": "thunderbolt", "operator": "eq", "value": True}, {"field": "usb_c_charging", "operator": "eq", "value": True}],
        [{"field": "upgradeability", "operator": "contains_all", "value": ["memory"]}],
        [{"field": "region", "operator": "eq", "value": "US"}, {"field": "memory_gb", "operator": "gte", "value": 24, "unit": "GB"}],
        [{"field": "configuration_id", "operator": "eq", "value": "H7606WX"}],
        [{"field": "weight_kg", "operator": "lte", "value": 1.1, "unit": "kg"}],
        [{"field": "price_cny", "operator": "lte", "value": 8000, "unit": "CNY"}],
    ]
    for constraints in cases:
        query = DomainProductQueryTool(repository).run(constraints)
        checker = DomainConstraintCheckerTool(repository).run(constraints)
        assert query.status == checker.status == "success"
        assert query.data["candidate_pool_size"] == checker.data["candidate_pool_size"] == 12
        for row in checker.data["results"]:
            if row["eligible"]:
                assert not row["violations"] and not row["unknown_fields"] and not row["conflicts"]
    assert not any(
        row["eligible"]
        for row in DomainConstraintCheckerTool(repository).run(cases[-1]).data["results"]
    )


def test_conflict_database_and_identity_faults_fail_closed(tmp_path: Path) -> None:
    _, _, snapshot, repository = _runtime(tmp_path)
    products = repository.load()
    product_id, product = next(iter(products.items()))
    source = product["evidence"][0]
    connection = sqlite3.connect(snapshot.database_path)
    try:
        connection.execute(
            "INSERT INTO evidence_records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "ev-injected-conflict", source["source_id"], product_id, "memory_gb",
                json.dumps(999), "GB", "fault injection", product["region"],
                product["variant_key"], "2026-09-02T00:00:00Z", "fault-conflict",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    conflict = DomainConstraintCheckerTool(repository).run(
        [{"field": "memory_gb", "operator": "gte", "value": 1, "unit": "GB"}],
        candidate_ids=[product_id],
    )
    assert conflict.status == "success"
    assert conflict.data["results"][0]["eligible"] is False
    assert conflict.data["results"][0]["conflicts"] == ["memory_gb"]
    wrong_identity = DomainConstraintCheckerTool(repository).run(
        [{"field": "memory_gb", "operator": "gte", "value": 1, "unit": "GB"}],
        candidate_ids=["unknown-product"],
    )
    assert wrong_identity.status == "failed" and wrong_identity.data["fail_closed"]


def test_wrong_region_evidence_is_unknown_and_cannot_grant_eligibility(tmp_path: Path) -> None:
    _, _, snapshot, repository = _runtime(tmp_path)
    products = repository.load()
    product_id, product = next(iter(products.items()))
    source = next(item for item in product["evidence"] if item["field_id"] == "memory_gb")
    connection = sqlite3.connect(snapshot.database_path)
    try:
        connection.execute(
            "DELETE FROM evidence_records WHERE product_id=? AND field_id='memory_gb'",
            (product_id,),
        )
        connection.execute(
            "INSERT INTO evidence_records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "ev-wrong-region-only", source["source_id"], product_id, "memory_gb",
                json.dumps(source["normalized_value"]), "GB", "wrong region injection", "ZZ",
                product["variant_key"], "2026-09-02T00:00:00Z", None,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    constraint = [{"field": "memory_gb", "operator": "gte", "value": 1, "unit": "GB"}]
    evidence = DomainEvidenceCheckTool(repository).run(product_id, constraint)
    field = evidence.data["field_results"][0]
    assert field["state"] == "unknown" and field["reason"] == "region_mismatch_only"
    assert field["evidence_ids"] == [] and field["non_target_evidence_ids"] == ["ev-wrong-region-only"]
    checked = DomainConstraintCheckerTool(repository).run(constraint, candidate_ids=[product_id])
    row = checked.data["results"][0]
    assert row["eligible"] is False and row["unknown_fields"] == ["memory_gb"]


def test_domain_pack_data_memory_and_checkpoint_are_cross_category_scoped(tmp_path: Path) -> None:
    laptop, _, snapshot, _ = _runtime(tmp_path)
    monitor = DomainPackLoader().load(ROOT / "smartbuy" / "domain_packs" / "monitor")
    with pytest.raises(Exception, match="domain and data differ"):
        DomainReadonlyRepository(snapshot, monitor)
    assert "memory_gb" in laptop.fields and "memory_gb" not in monitor.fields
    assert "usb_c_power_delivery_w" in monitor.fields and "usb_c_power_delivery_w" not in laptop.fields
    laptop_scope = DomainExecutionScope("laptop", "user", "session", "thread")
    monitor_scope = DomainExecutionScope("monitor", "user", "session", "thread")
    assert laptop_scope.key("memory") != monitor_scope.key("memory")
    assert laptop_scope.key("checkpoint") != monitor_scope.key("checkpoint")
    envelope = laptop_scope.envelope({"constraints": ["memory"]})
    with pytest.raises(Exception, match="cross-domain"):
        monitor_scope.restore(envelope)
    assert laptop_scope.restore(envelope) == {"constraints": ["memory"]}
