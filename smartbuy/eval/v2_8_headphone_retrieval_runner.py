"""Run the frozen V2-8 Headphone retrieval evaluation once."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from smartbuy.config import load_bailian_settings
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.providers import BailianProvider
from smartbuy.retrieval.domain_index import DomainIndexManager
from smartbuy.tools.domain import DomainKBSearchTool


ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "smartbuy" / "eval" / "v2_8_headphone_retrieval_cases.jsonl"
CASES_SHA256 = "637c2b4a8fc61f97429af36cb6fc9e628b661212435c93497ae1b01d74e5efb1"
DOMAIN_PACK = ROOT / "smartbuy" / "domain_packs" / "headphone"
PRODUCT_PACK = ROOT / "smartbuy" / "product_packs" / "examples" / "headphone-v1" / "pack.json"
INDEX_VERSION = "headphone-governed-2026-09-03-v1-embedding1024-v1"


def _ndcg(ranking: list[str], gold: set[str], k: int = 5) -> float:
    dcg = sum(1 / math.log2(rank + 2) for rank, item in enumerate(ranking[:k]) if item in gold)
    ideal = sum(1 / math.log2(rank + 2) for rank in range(min(len(gold), k)))
    return dcg / ideal if ideal else 0.0


def _p95(values: list[float]) -> float:
    return sorted(values)[max(0, math.ceil(0.95 * len(values)) - 1)]


async def run(runtime_root: Path, output: Path) -> dict:
    if output.exists():
        raise RuntimeError("evaluation output already exists; first run is immutable")
    if hashlib.sha256(CASES.read_bytes()).hexdigest() != CASES_SHA256:
        raise RuntimeError("frozen retrieval cases changed")
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines()]
    pack = DomainPackLoader().load(DOMAIN_PACK)
    data_manager = DomainProductPackManager(runtime_root / "data", domain_pack_path=DOMAIN_PACK)
    data = data_manager.publish(data_manager.stage(PRODUCT_PACK).data_version)
    index_manager = DomainIndexManager(
        runtime_root / "index", data_manager=data_manager, domain_id=pack.domain_id,
        domain_pack_version=pack.version,
    )
    settings = load_bailian_settings()
    async with BailianProvider(settings) as provider:
        index = await index_manager.build(
            data.data_version, INDEX_VERSION, provider, batch_size=10, cost_limit_cny=1.0
        )
        index_manager.activate(index.index_version)
        search = DomainKBSearchTool(index_manager, provider)
        rows = []
        vector_latencies: list[float] = []
        rerank_latencies: list[float] = []
        for case in cases:
            started = time.perf_counter()
            vector_result = await search.run(case["query"], vector_top_k=12, top_k=12, use_reranker=False)
            vector_ms = (time.perf_counter() - started) * 1000
            vector_latencies.append(vector_ms)
            hits = vector_result.data["hits"]
            vector_ids = [hit["product_id"] for hit in hits]
            started = time.perf_counter()
            reranked = await provider.rerank(
                case["query"], [hit["content"] for hit in hits], top_n=min(5, len(hits)),
                instruct="按耳机精确型号、配置、地区、连接能力和治理证据排序，不合并相似版本。",
            )
            rerank_ms = (time.perf_counter() - started) * 1000
            rerank_latencies.append(rerank_ms)
            rerank_ids = [hits[int(item["index"])]["product_id"] for item in reranked.data]
            gold = set(case["gold_product_ids"])
            rows.append({
                "case_id":case["case_id"],"category":case["category"],"difficulty":case["difficulty"],
                "gold_product_ids":sorted(gold),"vector_top5":vector_ids[:5],"reranker_top5":rerank_ids[:5],
                "vector_recall_at_5":len(gold & set(vector_ids[:5])) / len(gold),
                "reranker_recall_at_5":len(gold & set(rerank_ids[:5])) / len(gold),
                "vector_ndcg_at_5":_ndcg(vector_ids,gold),"reranker_ndcg_at_5":_ndcg(rerank_ids,gold),
                "vector_latency_ms":round(vector_ms,3),"reranker_latency_ms":round(rerank_ms,3),
                "exact_top1_required":case["require_top1_exact"],
                "vector_exact_top1":not case["require_top1_exact"] or vector_ids[0] in gold,
                "reranker_exact_top1":not case["require_top1_exact"] or rerank_ids[0] in gold,
                "cross_domain_hits":sum(hit["domain_id"] != "headphone" for hit in hits),
            })
        ledger = provider.ledger.summary()
    exact = [row for row in rows if row["exact_top1_required"]]
    result = {
        "run_type":"v2_8_headphone_retrieval_first","created_at":datetime.now(UTC).isoformat(),
        "case_file_sha256":CASES_SHA256,"case_count":len(rows),"domain_id":"headphone",
        "domain_pack_version":pack.version,"data_version":data.data_version,"data_manifest_hash":data.manifest_hash,
        "index_version":index.index_version,"collection_name":index.collection_name,"index_manifest_hash":index.manifest_hash,
        "document_count":index.manifest["document_count"],"chunk_count":index.manifest["chunk_count"],
        "embedding_model":"text-embedding-v4","embedding_dimensions":1024,
        "metrics":{
            "vector_recall_at_5":sum(row["vector_recall_at_5"] for row in rows)/len(rows),
            "reranker_recall_at_5":sum(row["reranker_recall_at_5"] for row in rows)/len(rows),
            "vector_ndcg_at_5":sum(row["vector_ndcg_at_5"] for row in rows)/len(rows),
            "reranker_ndcg_at_5":sum(row["reranker_ndcg_at_5"] for row in rows)/len(rows),
            "vector_exact_top1_errors":sum(not row["vector_exact_top1"] for row in exact),
            "reranker_exact_top1_errors":sum(not row["reranker_exact_top1"] for row in exact),
            "exact_top1_denominator":len(exact),
            "wrong_region_or_configuration_bindings":sum(
                row["difficulty"] in {"region","similar_configuration"} and not row["reranker_exact_top1"] for row in rows
            ),
            "cross_domain_hits":sum(row["cross_domain_hits"] for row in rows),
            "vector_average_latency_ms":statistics.mean(vector_latencies),"vector_p95_latency_ms":_p95(vector_latencies),
            "reranker_average_latency_ms":statistics.mean(rerank_latencies),"reranker_p95_latency_ms":_p95(rerank_latencies),
        },
        "api_usage":ledger,"agent_e2e_run":False,"cases":rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=asyncio.run(run(args.runtime_root,args.output))
    print(json.dumps({"status":"completed","metrics":result["metrics"],"api_usage":result["api_usage"]},ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
