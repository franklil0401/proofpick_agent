"""Domain-neutral Product Query, KB Search, evidence and checker tools."""

from __future__ import annotations

import gc
import json
import sqlite3
import time
from dataclasses import asdict
from typing import Any, Iterable, Sequence

from smartbuy.contracts import FieldState
from smartbuy.domain_packs import (
    DomainConstraintEvaluator,
    DomainPackValidationError,
    LoadedDomainPack,
)
from smartbuy.product_packs.domain_builder import DomainProductSnapshot
from smartbuy.product_packs.loader import ProductPackValidationError
from smartbuy.providers.bailian import BailianError
from smartbuy.retrieval.domain_index import DomainIndexManager
from smartbuy.tools.base import ToolResult
from smartbuy.identity import (
    ProductIdentityMismatch,
    ProductScopeResolutionStatus,
    ResolvedProductScope,
    product_identity,
    require_product_in_scope,
)


_IDENTITY_FIELDS = {
    "product_id": "product_id", "brand": "brand", "model_name": "model_name",
    "region": "region",
}
_ALLOWED_TABLES = frozenset({"products", "product_attributes", "evidence_records", "source_records"})
_ALLOWED_COLUMNS = frozenset({
    "product_id", "domain_id", "brand", "model_name", "region", "variant_key",
    "aliases_json", "status", "field_id", "value_json", "evidence_id", "source_id",
    "normalized_value_json", "unit", "snippet", "market", "observed_at",
    "conflict_group", "source_type", "title", "uri", "publisher", "is_official",
    "source_version", "accessed_at", "redistribution_status",
})


def _authorizer(action: int, arg1: str | None, arg2: str | None, *_: object) -> int:
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK if arg1 in _ALLOWED_TABLES and arg2 in _ALLOWED_COLUMNS else sqlite3.SQLITE_DENY
    if action in {sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION}:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


class DomainReadonlyRepository:
    """Load a validated EAV snapshot with one bounded, read-only SELECT."""

    def __init__(self, snapshot: DomainProductSnapshot, domain_pack: LoadedDomainPack) -> None:
        self.snapshot = snapshot
        self.domain_pack = domain_pack
        if snapshot.manifest.get("domain_id") != domain_pack.domain_id:
            raise ProductPackValidationError("repository domain and data differ")
        if snapshot.manifest.get("domain_pack_version") != domain_pack.version:
            raise ProductPackValidationError("repository pack and data versions differ")

    def load(self, *, timeout_ms: int = 250) -> dict[str, dict[str, Any]]:
        database = self.snapshot.database_path.resolve()
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro&immutable=1", uri=True)
        started = time.perf_counter()

        def progress() -> int:
            return int((time.perf_counter() - started) * 1000 > timeout_ms)

        connection.set_authorizer(_authorizer)
        connection.set_progress_handler(progress, 1000)
        try:
            rows = connection.execute(
                """
                SELECT p.product_id,p.domain_id,p.brand,p.model_name,p.region,p.variant_key,
                       p.aliases_json,p.status,e.evidence_id,e.field_id,e.normalized_value_json,
                       e.unit,e.snippet,e.market,e.variant_key,e.observed_at,e.conflict_group,
                       s.source_id,s.source_type,s.title,s.uri,s.source_version,s.accessed_at,
                       a.value_json
                FROM products AS p
                LEFT JOIN evidence_records AS e ON e.product_id=p.product_id
                LEFT JOIN source_records AS s ON s.source_id=e.source_id
                LEFT JOIN product_attributes AS a
                  ON a.product_id=p.product_id AND a.field_id=e.field_id
                ORDER BY p.product_id,e.evidence_id
                """
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise ProductPackValidationError("read-only domain query failed") from exc
        finally:
            connection.close()
        products: dict[str, dict[str, Any]] = {}
        attribute_fields = self.domain_pack.pack.policies["product_pack"]["attribute_fields"]
        for row in rows:
            product_id = str(row[0])
            product = products.setdefault(product_id, {
                "product_id": product_id, "domain_id": row[1], "brand": row[2],
                "model_name": row[3], "region": row[4], "variant_key": row[5],
                "aliases": json.loads(row[6]), "status": row[7],
                "attributes": {field: None for field in attribute_fields},
                "evidence": [],
            })
            if row[8] is None:
                continue
            field_id = str(row[9])
            value = json.loads(row[10])
            if field_id in product["attributes"]:
                product["attributes"][field_id] = json.loads(row[23]) if row[23] is not None else value
            product["evidence"].append({
                "evidence_id": row[8], "field_id": field_id, "normalized_value": value,
                "unit": row[11], "snippet": row[12], "region": row[13],
                "variant_key": row[14], "observed_at": row[15], "conflict_group": row[16],
                "source_id": row[17], "source_type": row[18], "source_title": row[19],
                "source_url": row[20], "source_version": row[21], "accessed_at": row[22],
            })
        for product in products.values():
            product["attributes"].update({key: product[key] for key in _IDENTITY_FIELDS})
        return products


class DomainProductQueryTool:
    """Deterministic Product Query alternative to category-specific Text2SQL."""

    def __init__(self, repository: DomainReadonlyRepository, *, max_rows: int = 100) -> None:
        self.repository = repository
        self.max_rows = max_rows
        self.evaluator = DomainConstraintEvaluator(repository.domain_pack)

    def run(
        self,
        constraints: Sequence[dict[str, Any]],
        *,
        scope: ResolvedProductScope | None = None,
    ) -> ToolResult:
        if not constraints:
            return ToolResult(tool="domain_product_query", status="failed", summary="至少需要一个约束", error_code="empty_constraints")
        try:
            normalized: list[dict[str, Any]] = []
            for item in constraints:
                field = self.repository.domain_pack.canonical_field(str(item["field"]))
                self.repository.domain_pack.validate_operator(field, str(item["operator"]))
                normalized.append({**item, "field": field})
            products = self.repository.load()
            if scope is not None:
                scope.assert_runtime(
                    domain_id=self.repository.domain_pack.domain_id,
                    data_version=self.repository.snapshot.data_version,
                )
                if scope.resolution_status != ProductScopeResolutionStatus.RESOLVED:
                    raise ProductIdentityMismatch("unresolved scope cannot query products")
                products = {
                    product_id: products[product_id]
                    for product_id in scope.product_ids
                    if product_id in products
                }
                if set(products) != set(scope.product_ids):
                    raise ProductIdentityMismatch("scope contains an unknown product")
            rows = []
            for product in products.values():
                evidence_fields = {item["field_id"] for item in product["evidence"]}
                decisions, eligible = self.evaluator.evaluate(
                    product["attributes"], normalized, evidenced_fields=evidence_fields
                )
                rows.append({
                    **product_identity(
                        product, data_version=self.repository.snapshot.data_version
                    ),
                    "status": "matched" if eligible else (
                        "unknown" if any(item.state == FieldState.UNKNOWN for item in decisions) else "not_matched"
                    ),
                    "constraint_results": [asdict(item) for item in decisions],
                    "evidence_ids": sorted({item["evidence_id"] for item in product["evidence"] if item["field_id"] in {decision.field_id for decision in decisions}}),
                    "source_ids": sorted({item["source_id"] for item in product["evidence"] if item["field_id"] in {decision.field_id for decision in decisions}}),
                })
            return ToolResult(
                tool="domain_product_query", status="success",
                data={"domain_id": self.repository.domain_pack.domain_id,
                      "data_version": self.repository.snapshot.data_version,
                      "scope_fingerprint": scope.fingerprint if scope else None,
                      "candidate_pool_size": len(rows), "rows": rows[: self.max_rows],
                      "read_only": True, "statement_count": 1},
                summary=f"只读查询检查 {len(rows)} 个完整候选",
            )
        except (
            KeyError,
            ValueError,
            ProductIdentityMismatch,
            ProductPackValidationError,
            DomainPackValidationError,
        ) as exc:
            return ToolResult(tool="domain_product_query", status="failed", summary="查询被安全门拒绝", error_code=type(exc).__name__)


class DomainKBSearchTool:
    """Search one validated domain index and optionally apply the shared reranker."""

    def __init__(self, index_manager: DomainIndexManager, provider: Any) -> None:
        self.index_manager = index_manager
        self.provider = provider

    async def run(
        self,
        query: str,
        *,
        product_id: str | None = None,
        configuration_id: str | None = None,
        region: str | None = None,
        scope: ResolvedProductScope | None = None,
        vector_top_k: int = 12,
        top_k: int = 5,
        use_reranker: bool = True,
    ) -> ToolResult:
        try:
            snapshot = self.index_manager.current()
        except ProductPackValidationError:
            return ToolResult(
                tool="domain_kb_search", status="failed", degraded=True,
                summary="索引状态不可用，已拒绝检索", error_code="index_fail_closed",
            )
        if scope is not None:
            try:
                scope.assert_runtime(
                    domain_id=self.index_manager.domain_id,
                    data_version=snapshot.data_version,
                    index_version=snapshot.index_version,
                )
                if scope.resolution_status != ProductScopeResolutionStatus.RESOLVED:
                    raise ProductIdentityMismatch("unresolved scope cannot search the index")
                if product_id is not None and not scope.permits(product_id):
                    raise ProductIdentityMismatch("KB product filter is outside candidate scope")
            except (ValueError, ProductIdentityMismatch):
                return ToolResult(
                    tool="domain_kb_search", status="failed", degraded=True,
                    summary="检索身份与候选范围不一致", error_code="kb_scope_mismatch",
                )
        try:
            embedding = await self.provider.embed([query])
        except BailianError:
            return ToolResult(
                tool="domain_kb_search", status="failed", degraded=True,
                summary="查询向量不可用", error_code="embedding_unavailable",
            )
        vector = list(embedding.data[0])
        if len(vector) != 1024:
            return ToolResult(tool="domain_kb_search", status="failed", summary="查询向量维度不兼容", error_code="embedding_dimension")
        import chromadb
        from chromadb.config import Settings

        client = chromadb.PersistentClient(path=str(snapshot.root / "chroma"), settings=Settings(anonymized_telemetry=False))
        try:
            collection = client.get_collection(name=snapshot.collection_name)
            filters: list[dict[str, Any]] = [
                {"domain_id": self.index_manager.domain_id}, {"data_version": snapshot.data_version}
            ]
            for key, value in (("product_id", product_id), ("configuration_id", configuration_id), ("region", region)):
                if value is not None:
                    filters.append({key: value})
            if scope is not None and product_id is None:
                filters.append({"product_id": {"$in": list(scope.product_ids)}})
            where = {"$and": filters} if len(filters) > 1 else filters[0]
            result = collection.query(
                query_embeddings=[vector], n_results=min(vector_top_k, collection.count()),
                where=where, include=["documents", "metadatas", "distances"],
            )
            documents = list(result["documents"][0])
            metadatas = list(result["metadatas"][0])
            distances = [float(value) for value in result["distances"][0]]
        finally:
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
        vector_scores = [1.0 - value for value in distances]
        degraded = False
        order = list(range(min(top_k, len(documents))))
        scores = vector_scores[: len(order)]
        if use_reranker and documents:
            try:
                reranked = await self.provider.rerank(
                    query, documents, top_n=min(top_k, len(documents)),
                    instruct="按品类、精确商品、配置、地区与治理证据相关性排序，不合并不同版本。",
                )
                order = [int(item["index"]) for item in reranked.data]
                scores = [float(item["relevance_score"]) for item in reranked.data]
            except BailianError:
                degraded = True
        hits = []
        for rank, source_index in enumerate(order):
            metadata = dict(metadatas[source_index])
            if scope is not None:
                identity_ok = (
                    metadata.get("domain_id") == scope.domain_id
                    and metadata.get("data_version") == scope.data_version
                    and metadata.get("index_version") == snapshot.index_version
                    and scope.permits(str(metadata.get("product_id")))
                    and metadata.get("configuration_id") in scope.configuration_ids
                    and metadata.get("region") in scope.regions
                )
                if not identity_ok:
                    return ToolResult(
                        tool="domain_kb_search", status="failed", degraded=True,
                        summary="索引命中越过候选身份边界", error_code="kb_identity_mismatch",
                    )
            hits.append({
                "rank": rank + 1, "score": scores[rank], "vector_score": vector_scores[source_index],
                "content": documents[source_index], "domain_id": metadata["domain_id"],
                "product_id": metadata["product_id"], "configuration_id": metadata["configuration_id"],
                "region": metadata["region"], "data_version": metadata["data_version"],
                "index_version": metadata["index_version"],
                "source_ids": json.loads(metadata["source_ids"]),
                "evidence_ids": json.loads(metadata["evidence_ids"]),
            })
        return ToolResult(
            tool="domain_kb_search", status="degraded" if degraded else "success", degraded=degraded,
            data={"domain_id": self.index_manager.domain_id, "data_version": snapshot.data_version,
                  "index_version": snapshot.index_version, "hits": hits,
                  "reranker_degraded": degraded,
                  "scope_fingerprint": scope.fingerprint if scope else None},
            summary=f"返回 {len(hits)} 个治理文档" + ("；Reranker 降级" if degraded else ""),
        )


class DomainEvidenceCheckTool:
    """Four-state evidence check driven exclusively by a loaded Domain Pack."""

    def __init__(self, repository: DomainReadonlyRepository) -> None:
        self.repository = repository

    def run(
        self,
        product_id: str,
        constraints: Sequence[dict[str, Any]],
        *,
        scope: ResolvedProductScope | None = None,
    ) -> ToolResult:
        try:
            product = self.repository.load()[product_id]
            if scope is not None:
                require_product_in_scope(
                    product,
                    scope,
                    data_version=self.repository.snapshot.data_version,
                )
        except (KeyError, ValueError, ProductIdentityMismatch, ProductPackValidationError):
            return ToolResult(tool="domain_evidence_check", status="failed", summary="商品或数据不可用", error_code="product_unavailable")
        evaluator = DomainConstraintEvaluator(self.repository.domain_pack)
        output = []
        for constraint in constraints:
            try:
                field = self.repository.domain_pack.canonical_field(str(constraint["field"]))
                records = [item for item in product["evidence"] if item["field_id"] == field]
                target = [item for item in records if item["region"] == product["region"] and item["variant_key"] == product["variant_key"]]
                non_target = [item for item in records if item not in target]
                values = {json.dumps(item["normalized_value"], ensure_ascii=False, sort_keys=True) for item in target}
                cross_region_values = {
                    json.dumps(item["normalized_value"], ensure_ascii=False, sort_keys=True)
                    for item in records
                }
                cross_region_conflict = bool(target and non_target and len(cross_region_values) > 1)
                if len(values) > 1:
                    state, reason = FieldState.CONFLICT, "governed_evidence_conflict"
                    decision = None
                elif not target:
                    state = FieldState.UNKNOWN
                    reason = "region_mismatch_only" if any(
                        item["region"] != product["region"] for item in non_target
                    ) else (
                        "configuration_mismatch_only" if non_target else "missing_governed_evidence"
                    )
                    decision = None
                else:
                    decisions, _ = evaluator.evaluate(
                        product["attributes"], [{**constraint, "field": field}], evidenced_fields={field}
                    )
                    decision = decisions[0]
                    state, reason = decision.state, decision.reason
                output.append({
                    "field_id": field, "state": state.value, "reason": reason,
                    "actual_value": None if decision is None else decision.actual_value,
                    "evidence_ids": [item["evidence_id"] for item in target],
                    "source_ids": sorted({item["source_id"] for item in target}),
                    "non_target_evidence_ids": [item["evidence_id"] for item in non_target],
                    "cross_region_conflict": cross_region_conflict,
                    "conflict_evidence_ids": [item["evidence_id"] for item in records]
                    if cross_region_conflict else [],
                })
            except (KeyError, ValueError, ProductPackValidationError, DomainPackValidationError):
                output.append({"field_id": str(constraint.get("field", "")), "state": "unknown", "reason": "unsupported_constraint", "evidence_ids": [], "source_ids": []})
        return ToolResult(
            tool="domain_evidence_check", status="success",
            data={
                **product_identity(product, data_version=self.repository.snapshot.data_version),
                "field_results": output,
                "scope_fingerprint": scope.fingerprint if scope else None,
            },
            summary=f"核验 {len(output)} 个字段",
        )


class DomainConstraintCheckerTool:
    """Fail-closed final gate over the complete structured candidate pool."""

    VERSION = "proofpick-domain-checker-v2-6b"

    def __init__(self, repository: DomainReadonlyRepository) -> None:
        self.repository = repository
        self.evaluator = DomainConstraintEvaluator(repository.domain_pack)

    def run(
        self,
        constraints: Sequence[dict[str, Any]],
        *,
        candidate_ids: Iterable[str] | None = None,
        scope: ResolvedProductScope | None = None,
    ) -> ToolResult:
        try:
            products = self.repository.load()
            requested = set(candidate_ids or products)
            if not requested or not requested <= set(products):
                raise ProductPackValidationError("candidate pool identity is invalid")
            if scope is not None:
                scope.assert_runtime(
                    domain_id=self.repository.domain_pack.domain_id,
                    data_version=self.repository.snapshot.data_version,
                )
                if scope.resolution_status != ProductScopeResolutionStatus.RESOLVED:
                    raise ProductIdentityMismatch("unresolved scope cannot enter Checker")
                if requested != set(scope.product_ids):
                    raise ProductIdentityMismatch("Checker candidate pool differs from scope")
            hard_fields = set(self.repository.domain_pack.pack.policies["checker"].get("hard_fields", []))
            normalized = []
            unsupported = []
            for item in constraints:
                field = self.repository.domain_pack.canonical_field(str(item["field"]))
                self.repository.domain_pack.validate_operator(field, str(item["operator"]))
                if field not in hard_fields:
                    unsupported.append(field)
                normalized.append({**item, "field": field})
            results = []
            for product_id in sorted(requested):
                product = products[product_id]
                evidence_by_field: dict[str, list[dict[str, Any]]] = {}
                for row in product["evidence"]:
                    if row["region"] == product["region"] and row["variant_key"] == product["variant_key"]:
                        evidence_by_field.setdefault(row["field_id"], []).append(row)
                conflicts = {
                    field for field, rows in evidence_by_field.items()
                    if len({json.dumps(row["normalized_value"], sort_keys=True) for row in rows}) > 1
                }
                decisions, _ = self.evaluator.evaluate(
                    product["attributes"], normalized,
                    evidenced_fields=set(evidence_by_field) - conflicts,
                )
                violations = [item.field_id for item in decisions if item.state == FieldState.NOT_MATCHED]
                unknowns = [item.field_id for item in decisions if item.state == FieldState.UNKNOWN and item.field_id not in conflicts]
                conflict_fields = [item.field_id for item in decisions if item.field_id in conflicts]
                eligible = bool(decisions) and not (violations or unknowns or conflict_fields or unsupported)
                results.append({
                    **product_identity(
                        product, data_version=self.repository.snapshot.data_version
                    ),
                    "eligible": eligible, "violations": violations, "unknown_fields": unknowns,
                    "conflicts": conflict_fields, "unsupported_constraints": unsupported,
                    "evidence_ids": sorted({row["evidence_id"] for field in {item.field_id for item in decisions} for row in evidence_by_field.get(field, [])}),
                    "constraint_results": [asdict(item) for item in decisions],
                    "checker_version": self.VERSION,
                })
            return ToolResult(
                tool="domain_constraint_checker", status="success",
                data={"domain_id": self.repository.domain_pack.domain_id,
                      "data_version": self.repository.snapshot.data_version,
                      "candidate_pool_size": len(results), "results": results,
                      "scope_fingerprint": scope.fingerprint if scope else None,
                      "fail_closed": True},
                summary=f"确定性复核 {len(results)} 个完整候选",
            )
        except (
            KeyError,
            ValueError,
            ProductIdentityMismatch,
            ProductPackValidationError,
            DomainPackValidationError,
        ):
            return ToolResult(
                tool="domain_constraint_checker", status="failed", degraded=True,
                data={"eligible": [], "fail_closed": True}, summary="Checker 异常，已关闭推荐",
                error_code="checker_fail_closed",
            )
