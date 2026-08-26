"""Evaluate vector retrieval and qwen3-rerank over the Stage 3 monitor corpus."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from pathlib import Path
from typing import Any

from smartbuy.config import load_bailian_settings
from smartbuy.observability import UsageLedger
from smartbuy.providers import BailianProvider
from smartbuy.retrieval.knowledge_base import DEFAULT_INDEX_DIR, INDEX_CONTRACT, youtu_environment


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = Path(__file__).with_name("cases.jsonl")
RESULTS_PATH = PROJECT_ROOT / "smartbuy" / "data" / "processed" / "stage3_retrieval_results.json"
RERANK_ABSTAIN_THRESHOLD = 0.20


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _dedupe_models(results: list[tuple[Any, float]], limit: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk, score in results:
        model_id = (chunk.metadata or {}).get("model_id")
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        candidates.append(
            {
                "model_id": model_id,
                "chunk_id": chunk.id,
                "document": chunk.content,
                "vector_score": float(score),
                "metadata": chunk.metadata or {},
            }
        )
        if len(candidates) >= limit:
            break
    return candidates


def recall_at_k(predicted: list[str], expected: list[str], k: int = 5) -> float:
    if not expected:
        return 0.0
    return len(set(predicted[:k]) & set(expected)) / len(set(expected))


def ndcg_at_k(predicted: list[str], expected: list[str], k: int = 5) -> float:
    if not expected:
        return 0.0
    relevant = set(expected)
    dcg = sum((1.0 / math.log2(index + 2)) for index, model_id in enumerate(predicted[:k]) if model_id in relevant)
    ideal_length = min(k, len(relevant))
    ideal = sum(1.0 / math.log2(index + 2) for index in range(ideal_length))
    return dcg / ideal if ideal else 0.0


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def usage_by_operation(ledger: UsageLedger) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for record in ledger.snapshot():
        key = (str(record["operation"]), str(record["model"]))
        item = grouped.setdefault(
            key,
            {
                "operation": key[0],
                "model": key[1],
                "call_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "estimated_cost_cny": 0.0,
                "latencies_ms": [],
            },
        )
        item["call_count"] += 1
        item["input_tokens"] += int(record["input_tokens"])
        item["output_tokens"] += int(record["output_tokens"])
        item["estimated_cost_cny"] += float(record["estimated_cost_cny"])
        item["latencies_ms"].append(float(record["latency_ms"]))
    output = []
    for item in grouped.values():
        latencies = item.pop("latencies_ms")
        item["estimated_cost_cny"] = round(item["estimated_cost_cny"], 8)
        item["average_latency_ms"] = round(statistics.fmean(latencies), 3)
        item["p95_latency_ms"] = round(percentile(latencies, 0.95), 3)
        output.append(item)
    return sorted(output, key=lambda item: (item["operation"], item["model"]))


def _open_store(settings: Any, index_dir: Path):
    with youtu_environment(settings):
        from utu.rag.config import VectorStoreConfig
        from utu.rag.storage.implementations.chroma_store import ChromaVectorStore

        return ChromaVectorStore(
            VectorStoreConfig(
                collection_name=INDEX_CONTRACT["collection_name"],
                persist_directory=str(index_dir.resolve()),
                distance_metric="cosine",
            )
        )


async def evaluate(index_dir: Path = DEFAULT_INDEX_DIR) -> dict[str, Any]:
    cases = load_cases()
    settings = load_bailian_settings()
    store = _open_store(settings, index_dir)
    index_count = await store.count()
    if index_count <= 0:
        raise RuntimeError("Stage 3 Chroma collection is empty")

    ledger = UsageLedger()
    async with BailianProvider(settings, ledger=ledger, timeout_seconds=30.0) as provider:
        embedding_started = time.perf_counter()
        query_vectors: list[list[float]] = []
        # The workspace-compatible endpoint rejected a 40-item request with HTTP 400.
        # Keep evaluation batches explicitly bounded at ten items.
        questions = [case["question"] for case in cases]
        for offset in range(0, len(questions), 10):
            embedding_result = await provider.embed(questions[offset : offset + 10])
            query_vectors.extend(embedding_result.data)
        embedding_latency_ms = (time.perf_counter() - embedding_started) * 1000
        output_rows: list[dict[str, Any]] = []
        query_latencies: list[float] = []
        for case, query_vector in zip(cases, query_vectors, strict=True):
            started = time.perf_counter()
            vector_results = await store.search(query_vector, top_k=min(40, index_count))
            candidates = _dedupe_models(vector_results, 10)
            vector_models = [item["model_id"] for item in candidates[:5]]
            degraded = case["category"] == "reranker_degradation"
            rerank_scores: list[float] = []
            if degraded:
                reranked = candidates[:5]
                rerank_scores = [item["vector_score"] for item in reranked]
            else:
                result = await provider.rerank_or_fallback(
                    case["question"],
                    [item["document"] for item in candidates],
                    top_n=5,
                    vector_scores=[item["vector_score"] for item in candidates],
                )
                degraded = result.degraded
                reranked = [candidates[item["index"]] for item in result.data]
                rerank_scores = [float(item["relevance_score"]) for item in result.data]
            rerank_models = [item["model_id"] for item in reranked]
            should_abstain_prediction = bool(rerank_scores and max(rerank_scores) < RERANK_ABSTAIN_THRESHOLD)
            if not rerank_scores:
                should_abstain_prediction = True
            query_latency_ms = (time.perf_counter() - started) * 1000 + embedding_latency_ms / len(cases)
            query_latencies.append(query_latency_ms)
            expected = case["expected_model_ids"]
            output_rows.append(
                {
                    "case_id": case["case_id"],
                    "category": case["category"],
                    "expected_model_ids": expected,
                    "vector_model_ids": vector_models,
                    "reranked_model_ids": rerank_models,
                    "vector_recall_at_5": recall_at_k(vector_models, expected),
                    "reranked_recall_at_5": recall_at_k(rerank_models, expected),
                    "vector_ndcg_at_5": ndcg_at_k(vector_models, expected),
                    "reranked_ndcg_at_5": ndcg_at_k(rerank_models, expected),
                    "top_relevance_score": max(rerank_scores) if rerank_scores else None,
                    "predicted_abstain": should_abstain_prediction,
                    "should_abstain": case["should_abstain"],
                    "degraded": degraded,
                    "latency_ms": round(query_latency_ms, 3),
                }
            )

    scored = [row for row in output_rows if row["expected_model_ids"]]
    similar = [row for row in output_rows if row["category"] == "similar_model"]
    abstain = [row for row in output_rows if row["should_abstain"]]
    fallback = next(row for row in output_rows if row["category"] == "reranker_degradation")
    metrics = {
        "case_count": len(cases),
        "scored_retrieval_case_count": len(scored),
        "vector_only_recall_at_5": round(statistics.fmean(row["vector_recall_at_5"] for row in scored), 6),
        "vector_reranker_recall_at_5": round(statistics.fmean(row["reranked_recall_at_5"] for row in scored), 6),
        "vector_only_ndcg_at_5": round(statistics.fmean(row["vector_ndcg_at_5"] for row in scored), 6),
        "vector_reranker_ndcg_at_5": round(statistics.fmean(row["reranked_ndcg_at_5"] for row in scored), 6),
        "similar_model_error_rate_vector": round(
            sum(row["vector_model_ids"][:1] != row["expected_model_ids"][:1] for row in similar) / max(1, len(similar)), 6
        ),
        "similar_model_error_rate_reranked": round(
            sum(row["reranked_model_ids"][:1] != row["expected_model_ids"][:1] for row in similar) / max(1, len(similar)), 6
        ),
        "abstention_accuracy": round(
            sum(row["predicted_abstain"] == row["should_abstain"] for row in abstain) / max(1, len(abstain)), 6
        ),
        "abstention_correct_count": sum(row["predicted_abstain"] == row["should_abstain"] for row in abstain),
        "abstention_case_count": len(abstain),
        "reranker_degradation_available": fallback["degraded"] and fallback["reranked_model_ids"] == fallback["vector_model_ids"],
        "average_latency_ms": round(statistics.fmean(query_latencies), 3),
        "p95_latency_ms": round(percentile(query_latencies, 0.95), 3),
        "embedding_batch_latency_ms": round(embedding_latency_ms, 3),
        "index_chunk_count": index_count,
    }
    payload = {
        "evaluation_version": "monitor-retrieval-v1",
        "data_version": "monitor-cn-2026-08-26-v1",
        "index_contract": INDEX_CONTRACT,
        "rerank_abstain_threshold": RERANK_ABSTAIN_THRESHOLD,
        "metrics": metrics,
        "usage": ledger.summary(),
        "usage_by_operation": usage_by_operation(ledger),
        "cases": output_rows,
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--output", type=Path, default=RESULTS_PATH)
    args = parser.parse_args()
    payload = asyncio.run(evaluate(args.index_dir))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": "completed", "metrics": payload["metrics"], "usage": payload["usage"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
