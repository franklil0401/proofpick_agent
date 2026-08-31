"""Run the bounded V2-2B live Product Pack index acceptance checks."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from smartbuy.config import load_bailian_settings
from smartbuy.constraints import CandidateConstraintVerifier, ConstraintNormalizer
from smartbuy.observability import UsageLedger
from smartbuy.product_packs import (
    ProductIndexManager,
    ProductPackRuntimeSettings,
    ProductPackValidationError,
    resolve_product_snapshot,
)
from smartbuy.providers import BailianProvider
from smartbuy.providers.bailian import ProviderResult
from smartbuy.tools import EvidenceCheckTool, KBSearchTool, Text2SQLTool


TARGET_MODEL_ID = "dell-u2725qe-us"
DATA_VERSION = "monitor-multi-region-2026-08-31-v2"
INDEX_VERSION = "monitor-multi-region-h2-v2-embedding1024-r1"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _inside_project(path: Path) -> bool:
    try:
        path.resolve().relative_to(PROJECT_ROOT.resolve())
        return True
    except ValueError:
        return False


class VectorFallbackProvider:
    """Reuse live query embeddings but inject a deterministic Reranker outage."""

    def __init__(self, provider: BailianProvider) -> None:
        self.provider = provider

    async def embed(self, texts: Sequence[str]) -> ProviderResult:
        return await self.provider.embed(texts)

    async def rerank_or_fallback(
        self,
        _query: str,
        documents: Sequence[str],
        *,
        top_n: int,
        vector_scores: Sequence[float] | None = None,
    ) -> ProviderResult:
        scores = list(vector_scores or [0.0] * len(documents))
        ranked = sorted(range(len(documents)), key=lambda index: scores[index], reverse=True)
        return ProviderResult(
            data=[
                {"index": index, "relevance_score": float(scores[index])}
                for index in ranked[:top_n]
            ],
            attempts=0,
            latency_ms=0.0,
            usage={},
            degraded=True,
        )


def _safe_hits(result: Any) -> list[dict[str, Any]]:
    return [
        {
            "rank": hit["rank"],
            "model_id": hit["model_id"],
            "region": hit["region"],
            "variant_key": hit["variant_key"],
            "source_version": hit["source_version"],
            "source_id": hit["source_id"],
            "evidence_ids": sorted(
                {
                    binding["evidence_id"]
                    for binding in hit["evidence_bindings"]
                    if binding.get("evidence_id")
                }
            ),
        }
        for hit in result.data.get("hits", [])
    ]


async def _query(
    tool: KBSearchTool,
    query: str,
    *,
    required_fields: list[str],
    model_ids: list[str] | None = None,
    expected_model_id: str = TARGET_MODEL_ID,
) -> dict[str, Any]:
    result = await tool.invoke(
        {
            "query": query,
            "model_ids": model_ids or [],
            "required_fields": required_fields,
            "reason": "V2-2B live index acceptance",
        }
    )
    hits = _safe_hits(result)
    target_ranks = [item["rank"] for item in hits if item["model_id"] == expected_model_id]
    if result.status not in {"success", "degraded"} or not target_ranks:
        raise RuntimeError("live KB Search did not return the governed target")
    for item in hits:
        if item["model_id"] == TARGET_MODEL_ID and (
            item["region"] != "US"
            or item["variant_key"] != "u2725qe-us-210-bqhr"
            or item["source_id"] != "src-dell-u2725qe-us-official-product"
        ):
            raise RuntimeError("live KB Search mixed a target region or variant")
    return {
        "query_label": query,
        "status": result.status,
        "reranker_degraded": result.data["reranker_degraded"],
        "target_ranks": target_ranks,
        "hits": hits,
    }


async def run(runtime_root: Path, output: Path) -> dict[str, Any]:
    if _inside_project(output):
        raise ValueError("live verification output must stay outside the Git workspace")
    settings = load_bailian_settings()
    if settings.embedding_model != "text-embedding-v4" or settings.embedding_dimensions != 1024:
        raise RuntimeError("the live embedding contract is not text-embedding-v4/1024")
    index_manager = ProductIndexManager(runtime_root)
    index = index_manager.current()
    if index.data_version != DATA_VERSION or index.index_version != INDEX_VERSION:
        raise RuntimeError("the selected Product Pack index is not the V2-2B target")
    resolved = resolve_product_snapshot(
        ProductPackRuntimeSettings(enabled=True, runtime_root=runtime_root)
    )
    if resolved is None:
        raise RuntimeError("the Product Pack runtime did not resolve")

    ledger = UsageLedger()
    async with BailianProvider(settings, timeout_seconds=30.0, ledger=ledger) as provider:
        kb = KBSearchTool(
            settings,
            provider,
            index_dir=resolved.index_dir,
            evidence_path=resolved.evidence_path,
            sources_path=resolved.sources_path,
            collection_name=resolved.collection_name,
        )
        identity_queries = []
        for query in ("U2725QE", "dell-u2725qe-us", "210-BQHR"):
            identity_queries.append(
                await _query(
                    kb,
                    query,
                    required_fields=["resolution", "usb_c_video", "usb_c_power_delivery_w"],
                )
            )
        combination = await _query(
            kb,
            "筛选 4K、USB-C 视频且供电至少 140W 的显示器，并核验 U2725QE 美国版规格",
            required_fields=["resolution", "usb_c_video", "usb_c_power_delivery_w"],
            model_ids=[TARGET_MODEL_ID],
        )
        similar_model = await _query(
            kb,
            "核验 Dell U2723QE 中国版 USB-C 供电规格",
            required_fields=["usb_c_power_delivery_w"],
            model_ids=["dell-u2723qe-cn"],
            expected_model_id="dell-u2723qe-cn",
        )
        if any(item["model_id"] == TARGET_MODEL_ID for item in similar_model["hits"]):
            raise RuntimeError("similar model query mixed the U2725QE US variant")

        fallback = await _query(
            KBSearchTool(
                settings,
                VectorFallbackProvider(provider),
                index_dir=resolved.index_dir,
                evidence_path=resolved.evidence_path,
                sources_path=resolved.sources_path,
                collection_name=resolved.collection_name,
            ),
            "210-BQHR USB-C 140W",
            required_fields=["usb_c_power_delivery_w"],
            model_ids=[TARGET_MODEL_ID],
        )
        if fallback["status"] != "degraded" or not fallback["reranker_degraded"]:
            raise RuntimeError("Reranker fallback was not exposed as degraded")

    sql_result = await Text2SQLTool(resolved.database_path).invoke(
        {
            "sql": "",
            "filters": [
                {"field": "resolution", "operator": "eq", "value": "4K"},
                {"field": "usb_c_video", "operator": "eq", "value": True},
                {"field": "usb_c_power_delivery_w", "operator": "gte", "value": 140},
                {"field": "region", "operator": "eq", "value": "US"},
            ],
            "reason": "V2-2B deterministic candidate filtering",
            "_deterministic_filters": True,
        }
    )
    sql_ids = [row["model_id"] for row in sql_result.data.get("rows", [])]
    if sql_result.status != "success" or TARGET_MODEL_ID not in sql_ids:
        raise RuntimeError("Text2SQL did not return the governed target")

    evidence_result = await EvidenceCheckTool(resolved.database_path).invoke(
        {
            "model_ids": [TARGET_MODEL_ID],
            "required_fields": ["resolution", "usb_c_video", "usb_c_power_delivery_w"],
            "constraints": [
                {"field": "resolution", "operator": "eq", "value": "4K"},
                {"field": "usb_c_video", "operator": "eq", "value": True},
                {"field": "usb_c_power_delivery_w", "operator": "gte", "value": 140},
            ],
            "reason": "V2-2B governed field evidence",
        }
    )
    if evidence_result.status != "success" or evidence_result.data["status_counts"]["matched"] != 3:
        raise RuntimeError("Evidence Check did not match all governed fields")

    constraints = ConstraintNormalizer().build(
        "美国版 4K、USB-C 视频且供电至少 140W", source_turn=1
    )
    verification = CandidateConstraintVerifier(
        resolved.database_path,
        as_of=datetime(2026, 8, 31, tzinfo=UTC),
    ).verify_candidates(constraints, sql_ids)
    if verification.eligible_model_ids != [TARGET_MODEL_ID]:
        raise RuntimeError("Constraint Checker did not retain exactly the governed target")

    incomplete = index_manager.indices_root / "incomplete-v2-2b-acceptance"
    if incomplete.exists():
        raise RuntimeError("the isolated incomplete-index fixture already exists")
    incomplete.mkdir(parents=True)
    previous_hash = index_manager.current().manifest_hash
    incomplete_rejected = False
    try:
        try:
            index_manager.activate(incomplete.name)
        except ProductPackValidationError:
            incomplete_rejected = True
        if not incomplete_rejected or index_manager.current().manifest_hash != previous_hash:
            raise RuntimeError("an incomplete index changed the trusted pointer")
    finally:
        shutil.rmtree(incomplete)

    rolled_back = index_manager.rollback(INDEX_VERSION)
    if (
        rolled_back.manifest_hash != previous_hash
        or index_manager.current().manifest_hash != previous_hash
    ):
        raise RuntimeError("index rollback did not restore the trusted snapshot")
    if resolve_product_snapshot(ProductPackRuntimeSettings(enabled=False)) is not None:
        raise RuntimeError("disabling Product Pack did not restore the V1 runtime path")

    usage = ledger.summary()
    build_cost = float(index.manifest["embedding_estimated_cost_cny"])
    total_cost = round(build_cost + float(usage["estimated_cost_cny"]), 8)
    if total_cost > 1.0:
        raise RuntimeError("V2-2B live acceptance exceeded the cost limit")
    report = {
        "status": "completed",
        "data_version": index.data_version,
        "index_version": index.index_version,
        "collection_name": index.collection_name,
        "document_count": index.manifest["document_count"],
        "chunk_count": index.manifest["chunk_count"],
        "embedding_model": index.manifest["embedding_model"],
        "embedding_dimensions": index.manifest["embedding_dimensions"],
        "identity_queries": identity_queries,
        "combination_query": combination,
        "similar_model_query": similar_model,
        "reranker_fallback": fallback,
        "tool_closure": {
            "text2sql": {"status": sql_result.status, "model_ids": sql_ids},
            "kb_search": {"status": combination["status"], "target_found": True},
            "evidence_check": {
                "status": evidence_result.status,
                "status_counts": evidence_result.data["status_counts"],
            },
            "constraint_checker": {
                "status": "passed",
                "eligible_model_ids": verification.eligible_model_ids,
            },
        },
        "safety": {
            "incomplete_index_rejected": incomplete_rejected,
            "pointer_unchanged_after_rejection": True,
            "rollback_manifest_hash_restored": True,
            "v1_path_restored_when_feature_disabled": True,
        },
        "usage": {
            "build_embedding_calls": index.manifest["embedding_call_count"],
            "build_embedding_input_tokens": index.manifest["embedding_input_tokens"],
            "build_estimated_cost_cny": build_cost,
            "query_ledger": usage,
            "total_estimated_cost_cny": total_cost,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run(args.runtime_root.resolve(), args.output.resolve()))
    print(
        json.dumps(
            {
                "status": report["status"],
                "data_version": report["data_version"],
                "index_version": report["index_version"],
                "collection_name": report["collection_name"],
                "document_count": report["document_count"],
                "chunk_count": report["chunk_count"],
                "embedding_dimensions": report["embedding_dimensions"],
                "tool_closure": report["tool_closure"],
                "safety": report["safety"],
                "usage": report["usage"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
