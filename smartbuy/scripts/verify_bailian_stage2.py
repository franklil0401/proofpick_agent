"""Run the bounded Stage 2 Model Studio live verification without printing content or secrets."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from typing import Sequence

from smartbuy.config import ConfigurationError, load_bailian_settings
from smartbuy.providers import BailianError, BailianProvider


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm)


async def verify() -> dict[str, object]:
    settings = load_bailian_settings()
    report: dict[str, object] = {
        "configuration": settings.availability(),
        "models": {
            "llm": settings.chat_model,
            "embedding": settings.embedding_model,
            "embedding_dimensions": settings.embedding_dimensions,
            "reranker": settings.reranker_model,
        },
    }

    async with BailianProvider(settings) as provider:
        ordinary = await provider.chat(
            [{"role": "user", "content": "只回答 OK。"}], max_tokens=8
        )
        report["ordinary_chat"] = {
            "success": bool(ordinary.data.get("content")),
            "attempts": ordinary.attempts,
            "latency_ms": round(ordinary.latency_ms, 1),
            "usage": ordinary.usage,
        }

        stream_chunks = 0
        stream_content_chars = 0
        async for chunk in provider.chat_stream(
            [{"role": "user", "content": "用一句很短的话说明显示器刷新率。"}],
            max_tokens=32,
        ):
            stream_chunks += 1
            for choice in chunk.get("choices") or []:
                stream_content_chars += len((choice.get("delta") or {}).get("content") or "")
        report["stream_chat"] = {
            "success": stream_chunks > 0 and stream_content_chars > 0,
            "chunk_count": stream_chunks,
            "content_char_count": stream_content_chars,
        }

        tool_name = "lookup_product_specs"
        tool = await provider.chat(
            [
                {
                    "role": "user",
                    "content": "请调用工具查询型号 DEMO-27 的尺寸，不要直接回答。",
                }
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": "查询自制演示商品参数",
                        "parameters": {
                            "type": "object",
                            "properties": {"model": {"type": "string"}},
                            "required": ["model"],
                            "additionalProperties": False,
                        },
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": tool_name}},
            max_tokens=64,
        )
        calls = tool.data.get("tool_calls") or []
        report["tool_calling"] = {
            "success": bool(calls),
            "tool_name_matches": bool(calls) and calls[0].get("function", {}).get("name") == tool_name,
            "attempts": tool.attempts,
            "latency_ms": round(tool.latency_ms, 1),
            "usage": tool.usage,
        }

        embedding = await provider.embed(
            [
                "27 英寸 4K 显示器适合高分辨率办公。",
                "这款 27 英寸屏幕用于文档和设计工作。",
                "厨房电饭煲支持预约煮饭。",
            ]
        )
        vectors = embedding.data
        related = cosine(vectors[0], vectors[1])
        unrelated = cosine(vectors[0], vectors[2])
        report["embedding"] = {
            "success": len(vectors) == 3 and all(len(vector) == 1024 for vector in vectors),
            "input_count": 3,
            "output_count": len(vectors),
            "dimensions": sorted({len(vector) for vector in vectors}),
            "related_similarity": round(related, 6),
            "unrelated_similarity": round(unrelated, 6),
            "semantic_order_ok": related > unrelated,
            "attempts": embedding.attempts,
            "latency_ms": round(embedding.latency_ms, 1),
            "usage": embedding.usage,
        }

        rerank = await provider.rerank(
            "适合 4K 办公的 27 英寸显示器",
            [
                "24 英寸 1080p 电竞显示器，刷新率 180Hz。",
                "27 英寸 4K IPS 显示器，面向办公和设计。",
                "家用电饭煲，容量 4 升。",
            ],
            top_n=3,
        )
        report["reranker"] = {
            "success": len(rerank.data) == 3,
            "result_count": len(rerank.data),
            "ranked_indices": [item["index"] for item in rerank.data],
            "expected_first": bool(rerank.data) and rerank.data[0]["index"] == 1,
            "attempts": rerank.attempts,
            "latency_ms": round(rerank.latency_ms, 1),
            "usage": rerank.usage,
        }
        report["usage_summary"] = provider.ledger.summary()
        report["usage_records"] = provider.ledger.snapshot()

    checks = [
        report["ordinary_chat"]["success"],
        report["stream_chat"]["success"],
        report["tool_calling"]["success"],
        report["tool_calling"]["tool_name_matches"],
        report["embedding"]["success"],
        report["embedding"]["semantic_order_ok"],
        report["reranker"]["success"],
        report["reranker"]["expected_first"],
    ]
    report["all_checks_passed"] = all(checks)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        report = asyncio.run(verify())
    except (ConfigurationError, BailianError) as exc:
        print(json.dumps({"all_checks_passed": False, "error_type": type(exc).__name__}))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
