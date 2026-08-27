"""Measure cold and hot public-evaluation cache paths without changing correctness."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smartbuy.cache import CacheNamespace, CachedBailianProvider, CachedReadOnlyTool, SafeCache
from smartbuy.config import load_bailian_settings
from smartbuy.db.build_database import DEFAULT_OUTPUT
from smartbuy.eval.stage6_scoring import percentile
from smartbuy.observability import EvaluationLedger, EvaluationLedgerRecord, UsageLedger
from smartbuy.providers import BailianProvider
from smartbuy.tools import KBSearchTool, Text2SQLTool


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).with_name("stage6_config.json")
RESULT_PATH = PROJECT_ROOT / "smartbuy/data/processed/stage6_cache_results.json"
LEDGER_PATH = PROJECT_ROOT / "smartbuy/data/processed/stage6_cache_ledger.jsonl"
DEFAULT_CACHE_PATH = Path("C:/ai/smartbuy-stage6/cache/benchmark.sqlite")

PUBLIC_QUERIES = [
    ("cache-001", "U2723QE 的分辨率是什么？", ["resolution"]),
    ("cache-002", "G2724D 是否为 OLED？", ["is_oled"]),
    ("cache-003", "PD2705U 的 USB-C 供电是多少？", ["usb_c_power_delivery_w"]),
    ("cache-004", "PA279CRV 支持 USB-C 视频吗？", ["usb_c_video"]),
    ("cache-005", "27UQ850V 的支架支持哪些调节？", ["stand_adjustment"]),
]


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _usage_delta(ledger: UsageLedger, start: int) -> dict[str, Any]:
    records = ledger.snapshot()[start:]
    return {
        "call_count": len(records),
        "input_tokens": sum(int(item["input_tokens"]) for item in records),
        "output_tokens": sum(int(item["output_tokens"]) for item in records),
        "estimated_cost_cny": round(
            sum(float(item["estimated_cost_cny"]) for item in records), 8
        ),
    }


async def evaluate(cache_path: Path = DEFAULT_CACHE_PATH) -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    settings = load_bailian_settings()
    usage_ledger = UsageLedger()
    provider = BailianProvider(settings, ledger=usage_ledger, timeout_seconds=30.0)
    cache = SafeCache(cache_path)
    cache.clear()
    namespace = CacheNamespace(
        data_version=config["data_version"],
        index_version=config["index_version"],
        model_version=config["evaluation_version"],
        embedding_dimensions=config["embedding_dimensions"],
        region=config["region"],
        as_of=config["as_of"],
        reranker_instruct=config["reranker_instruct"],
    )
    cached_provider = CachedBailianProvider(provider, cache, namespace)
    kb = CachedReadOnlyTool(
        KBSearchTool(settings, cached_provider, vector_top_k=30, result_top_k=5),
        cache,
        namespace,
        operation="vector_recall",
        model="text-embedding-v4+qwen3-rerank",
    )
    rows: list[dict[str, Any]] = []
    usage_start = len(usage_ledger.snapshot())
    try:
        for phase in ("cold", "hot"):
            for case_id, query, fields in PUBLIC_QUERIES:
                started = time.perf_counter()
                result = await kb.invoke(
                    {
                        "query": query,
                        "model_ids": [],
                        "required_fields": fields,
                        "reason": "阶段 6 公共评测缓存基准。",
                    }
                )
                duration = (time.perf_counter() - started) * 1000
                rows.append(
                    {
                        "case_id": case_id,
                        "phase": phase,
                        "duration_ms": round(duration, 3),
                        "cache_hit": kb.cache_events[-1]["cache_hit"],
                        "status": result.status,
                        "degraded": result.degraded,
                        "result": result.model_dump(mode="json"),
                    }
                )

        sql = CachedReadOnlyTool(
            Text2SQLTool(DEFAULT_OUTPUT), cache, namespace,
            operation="readonly_sql", model="sqlite-3-readonly",
        )
        dynamic_args = {
            "sql": (
                "SELECT model_id, price_cny, observed_at FROM price_observations "
                "ORDER BY observed_at DESC LIMIT 5"
            ),
            "filters": [],
            "reason": "验证动态价格默认不缓存。",
        }
        dynamic_first = await sql.invoke(dynamic_args)
        dynamic_second = await sql.invoke(dynamic_args)
    finally:
        await cached_provider.aclose()

    cold = [item for item in rows if item["phase"] == "cold"]
    hot = [item for item in rows if item["phase"] == "hot"]
    exact_matches = sum(
        cold_row["result"] == hot_row["result"]
        for cold_row, hot_row in zip(cold, hot, strict=True)
    )
    cold_times = [float(item["duration_ms"]) for item in cold]
    hot_times = [float(item["duration_ms"]) for item in hot]
    cold_average = statistics.fmean(cold_times)
    hot_average = statistics.fmean(hot_times)
    return {
        "evaluation_version": "smartbuy-stage6-cache-v1",
        "run_id": f"stage6-cache-{uuid.uuid4().hex[:12]}",
        "config_hash": config["config_hash"],
        "data_version": config["data_version"],
        "index_version": config["index_version"],
        "cache_policy": {
            "path_committed": False,
            "public_evaluation_opt_in": True,
            "ttl_seconds": cache.policy.ttl_seconds,
            "max_entries": cache.policy.max_entries,
            "dynamic_price_cached": False,
        },
        "case_count": len(PUBLIC_QUERIES),
        "cold": {
            "average_latency_ms": round(cold_average, 3),
            "p95_latency_ms": percentile(cold_times, 0.95),
            "cache_hits": sum(item["cache_hit"] for item in cold),
            "requests": len(cold),
        },
        "hot": {
            "average_latency_ms": round(hot_average, 3),
            "p95_latency_ms": percentile(hot_times, 0.95),
            "cache_hits": sum(item["cache_hit"] for item in hot),
            "requests": len(hot),
        },
        "average_speedup": round(cold_average / hot_average, 3) if hot_average else None,
        "output_identity": {
            "numerator": exact_matches,
            "denominator": len(PUBLIC_QUERIES),
            "rate": round(exact_matches / len(PUBLIC_QUERIES), 6),
        },
        "dynamic_bypass": {
            "first_cache_hit": sql.cache_events[0]["cache_hit"],
            "second_cache_hit": sql.cache_events[1]["cache_hit"],
            "outputs_identical": dynamic_first.model_dump(mode="json") == dynamic_second.model_dump(mode="json"),
        },
        "cache_stats": cache.stats(),
        "usage": _usage_delta(usage_ledger, usage_start),
        "rows": rows,
    }


def _write_ledger(payload: dict[str, Any]) -> None:
    ledger = EvaluationLedger()
    for step, row in enumerate(payload["rows"], start=1):
        timestamp = _now()
        ledger.add(
            EvaluationLedgerRecord(
                run_id=payload["run_id"],
                case_id=row["case_id"],
                experiment_group="cache",
                repetition=1 if row["phase"] == "cold" else 2,
                data_version=payload["data_version"],
                config_hash=payload["config_hash"],
                model="text-embedding-v4+qwen3-rerank",
                tool="kb_search",
                step=step,
                started_at=timestamp,
                ended_at=timestamp,
                duration_ms=row["duration_ms"],
                status=row["status"],
                cache_hit=row["cache_hit"],
                degraded=row["degraded"],
            )
        )
    ledger.write(LEDGER_PATH)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--output", type=Path, default=RESULT_PATH)
    args = parser.parse_args()
    payload = asyncio.run(evaluate(args.cache_path))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_ledger(payload)
    print(
        json.dumps(
            {
                "case_count": payload["case_count"],
                "cold": payload["cold"],
                "hot": payload["hot"],
                "output_identity": payload["output_identity"],
                "cost_cny": payload["usage"]["estimated_cost_cny"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
