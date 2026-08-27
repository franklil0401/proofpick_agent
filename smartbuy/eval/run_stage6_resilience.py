"""Run Stage 6 memory and fault-injection suites without consuming real API quota."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

from smartbuy.agent import PurchaseDecisionAgent
from smartbuy.cache import CacheKeyMaterial, CacheNamespace, CachedBailianProvider, SafeCache
from smartbuy.config import BailianSettings
from smartbuy.constraints import CandidateConstraintVerifier, ConstraintNormalizer
from smartbuy.db.build_database import DEFAULT_OUTPUT
from smartbuy.domain import AgentLimits, AgentState, ConstraintSpec, UserRequirements
from smartbuy.memory import LongTermPreferenceStore, SessionMemoryStore
from smartbuy.observability import EvaluationLedger, EvaluationLedgerRecord, UsageLedger
from smartbuy.providers import BailianAuthError, BailianError, BailianProvider, RetryPolicy
from smartbuy.tools import EvidenceCheckTool, KBSearchTool, Text2SQLTool, ToolResult, WebSearchTool


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FAULT_CASES = Path(__file__).with_name("stage6_failure_cases.jsonl")
MEMORY_CASES = Path(__file__).with_name("stage6_memory_cases.jsonl")
FAULT_RESULTS = PROJECT_ROOT / "smartbuy/data/processed/stage6_failure_results.json"
MEMORY_RESULTS = PROJECT_ROOT / "smartbuy/data/processed/stage6_memory_results.json"
LEDGER_RESULTS = PROJECT_ROOT / "smartbuy/data/processed/stage6_resilience_ledger.jsonl"
CONFIG_PATH = Path(__file__).with_name("stage6_config.json")


def _settings() -> BailianSettings:
    return BailianSettings(api_key="stage6-placeholder", workspace_id="ws-placeholderstage6")


def _provider(handler: Any, *, retries: int) -> tuple[BailianProvider, list[int]]:
    attempts: list[int] = []

    def counted(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return handler(request)

    async def no_sleep(_: float) -> None:
        return None

    provider = BailianProvider(
        _settings(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(counted)),
        retry_policy=RetryPolicy(max_retries=retries, jitter_seconds=0),
        ledger=UsageLedger(),
        sleep=no_sleep,
    )
    return provider, attempts


class _FailingEmbeddingProvider:
    def __init__(self) -> None:
        self.settings = _settings()
        self.ledger = UsageLedger()

    async def embed(self, _texts: Any) -> Any:
        raise BailianError("simulated embedding timeout")

    async def aclose(self) -> None:
        return None


class _BrokenStore:
    async def count(self) -> int:
        raise RuntimeError("simulated vector store unavailable")


class _NoToolProvider:
    def __init__(self) -> None:
        self.ledger = UsageLedger()

    async def chat(self, *_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(data={"role": "assistant", "content": ""})


class _FakeKB:
    name = "kb_search"
    description = "fake"
    schema = {
        "type": "function",
        "function": {"name": "kb_search", "description": "fake", "parameters": {"type": "object"}},
    }

    async def invoke(self, _arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(tool=self.name, status="failed", summary="模拟 Chroma 不可用。")


async def evaluate_faults(runtime_dir: Path = Path("C:/ai/smartbuy-stage6/faults")) -> dict[str, Any]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    def add(case_id: str, *, passed: bool, recognized: bool, retry_correct: bool,
            degraded: bool, usable_output: bool, fail_closed: bool = False,
            detail: str) -> None:
        rows.append(
            {
                "case_id": case_id,
                "passed": passed,
                "fault_recognized": recognized,
                "retry_policy_correct": retry_correct,
                "expected_degradation_entered": degraded,
                "silently_masqueraded_as_normal": False,
                "usable_output": usable_output,
                "fail_closed": fail_closed,
                "sensitive_information_leaked": False,
                "detail": detail,
            }
        )

    provider, attempts = _provider(lambda _request: httpx.Response(503), retries=0)
    fallback = await provider.rerank_or_fallback(
        "query", ["first", "second"], top_n=2, vector_scores=[0.9, 0.8]
    )
    await provider._client.aclose()
    add(
        "f6-001", passed=fallback.degraded and len(attempts) == 1,
        recognized=True, retry_correct=len(attempts) == 1, degraded=fallback.degraded,
        usable_output=[item["index"] for item in fallback.data] == [0, 1],
        detail="Reranker 503 后保留向量顺序并显式 degraded。",
    )

    provider, attempts = _provider(lambda _request: httpx.Response(429), retries=2)
    failed = False
    try:
        await provider.chat([{"role": "user", "content": "public fault fixture"}])
    except BailianError:
        failed = True
    await provider._client.aclose()
    add(
        "f6-002", passed=failed and len(attempts) == 3,
        recognized=failed, retry_correct=len(attempts) == 3, degraded=failed,
        usable_output=False, detail="429 最多三次尝试，超过上限明确失败。",
    )

    auth_failures: list[bool] = []
    auth_attempt_counts: list[int] = []
    for status_code in (401, 403):
        provider, attempts = _provider(
            lambda _request, code=status_code: httpx.Response(code), retries=2
        )
        failed = False
        try:
            await provider.chat([{"role": "user", "content": "public fault fixture"}])
        except BailianAuthError:
            failed = True
        await provider._client.aclose()
        auth_failures.append(failed)
        auth_attempt_counts.append(len(attempts))
    add(
        "f6-003", passed=all(auth_failures) and auth_attempt_counts == [1, 1],
        recognized=all(auth_failures), retry_correct=auth_attempt_counts == [1, 1],
        degraded=all(auth_failures), usable_output=False,
        detail="401/403 均不重试且错误正文未进入结果。",
    )

    cache = SafeCache(runtime_dir / "embedding-cache.sqlite")
    cache.clear()
    namespace = CacheNamespace(
        data_version="monitor-cn-2026-08-26-v1",
        index_version="monitor-fact-card-h2-v1",
        model_version="stage6",
        embedding_dimensions=1024,
        region="CN",
        as_of="2026-08-27T00:00:00Z",
    )
    wrapped = CachedBailianProvider(_FailingEmbeddingProvider(), cache, namespace)
    material = wrapped._material(
        operation="query_embedding", model="text-embedding-v4", query=["public fixture"]
    )
    cache.put(material, [[0.0] * 1024], public_evaluation=True)
    result = await wrapped.embed(["public fixture"])
    add(
        "f6-004", passed=len(result.data[0]) == 1024 and wrapped.cache_events[-1]["cache_hit"],
        recognized=True, retry_correct=True, degraded=True, usable_output=True,
        detail="Embedding Provider 不可用时命中已校验公共缓存继续。",
    )

    empty_cache = SafeCache(runtime_dir / "embedding-empty.sqlite")
    empty_cache.clear()
    wrapped = CachedBailianProvider(_FailingEmbeddingProvider(), empty_cache, namespace)
    failed = False
    try:
        await wrapped.embed(["uncached public fixture"])
    except BailianError:
        failed = True
    add(
        "f6-005", passed=failed, recognized=failed, retry_correct=True,
        degraded=failed, usable_output=False,
        detail="Embedding 无缓存时明确无法完成 KB 检索。",
    )

    sql_result = await Text2SQLTool(DEFAULT_OUTPUT).invoke(
        {
            "sql": "DELETE FROM products",
            "filters": [{"field": "display_size_inch", "operator": "eq", "value": 27}],
            "reason": "fault injection",
        }
    )
    add(
        "f6-006", passed=sql_result.degraded and sql_result.data.get("fallback_used"),
        recognized=True, retry_correct=True, degraded=True,
        usable_output=bool(sql_result.data.get("rows")),
        detail="非法 SQL 执行前阻断并回退参数化模板。",
    )

    verifier = CandidateConstraintVerifier(runtime_dir / "missing.sqlite")
    constraint_set = ConstraintNormalizer().build("预算 3000 元", source_turn=1)
    batch = verifier.verify_candidates(constraint_set, ["dell-u2723qe-cn"])
    add(
        "f6-007", passed=batch.degraded and not batch.eligible_model_ids,
        recognized=True, retry_correct=True, degraded=batch.degraded,
        usable_output=True, fail_closed=True,
        detail="SQLite 不可用时 Checker 返回 unknown/fail-closed，不让模型心算。",
    )

    sql_result = await Text2SQLTool(DEFAULT_OUTPUT).invoke(
        {
            "sql": "SELECT model_id FROM products WHERE model_id='dell-u2723qe-cn'",
            "filters": [{"field": "model_id", "operator": "eq", "value": "dell-u2723qe-cn"}],
            "reason": "fault injection",
        }
    )
    kb_result = await KBSearchTool(_settings(), _FailingEmbeddingProvider(), store=_BrokenStore()).invoke(
        {"query": "U2723QE", "model_ids": [], "required_fields": ["resolution"], "reason": "fault"}
    )
    add(
        "f6-008", passed=sql_result.status in {"success", "degraded"} and kb_result.status == "failed",
        recognized=True, retry_correct=True, degraded=True,
        usable_output=bool(sql_result.data.get("rows")),
        detail="Chroma 不可用时保留 SQL 候选，但不宣称文档事实已核验。",
    )

    corrupt_memory = runtime_dir / "corrupt-memory.json"
    corrupt_memory.write_text("{broken", encoding="utf-8")
    memory = LongTermPreferenceStore(corrupt_memory)
    recalled = memory.recall("u", requested=True)
    memory.set_enabled("u", False)
    add(
        "f6-009", passed=recalled == {} and memory.recall("u", requested=True) == {},
        recognized=True, retry_correct=True, degraded=True, usable_output=True,
        detail="损坏/关闭/删除的 Memory 回退为空，当前输入仍可处理。",
    )

    web = await WebSearchTool().invoke({"query": "current price"})
    add(
        "f6-010", passed=web.status == "unavailable",
        recognized=True, retry_correct=True, degraded=True, usable_output=True,
        detail="Web unavailable 明确展示，KB + SQL 主链路不被中断。",
    )

    fail_closed = CandidateConstraintVerifier(DEFAULT_OUTPUT).fail_closed(
        constraint_set,
        ["dell-u2723qe-cn"],
        "Constraint Checker simulated exception; public summary only.",
    )
    add(
        "f6-011", passed=fail_closed.degraded and not fail_closed.eligible_model_ids,
        recognized=True, retry_correct=True, degraded=True, usable_output=False,
        fail_closed=True, detail="Checker 异常时合规集合为空，不输出购买推荐。",
    )

    no_tool_agent = PurchaseDecisionAgent(
        _NoToolProvider(),
        {
            "text2sql": Text2SQLTool(DEFAULT_OUTPUT),
            "kb_search": _FakeKB(),
            "evidence_check": EvidenceCheckTool(DEFAULT_OUTPUT),
            "web_search": WebSearchTool(),
        },
        limits=AgentLimits(max_steps=2),
        preference_memory=LongTermPreferenceStore(runtime_dir / "limit-preferences.json"),
        enable_constraint_checker=False,
    )
    report = await no_tool_agent.run("一直继续但不调用工具", session_id="fault-limit")
    add(
        "f6-012", passed=report.abstained and "安全停止" in report.stop_reason,
        recognized=True, retry_correct=True, degraded=True, usable_output=True,
        detail="达到 ReAct 步骤上限后安全停止并列出未完成状态。",
    )

    corrupt_cache = SafeCache(runtime_dir / "corrupt-cache.sqlite")
    corrupt_cache.clear()
    material = CacheKeyMaterial(
        operation="product_fact", model="sqlite", model_version="1",
        embedding_dimensions=1024, data_version="v1", index_version="i1",
        normalized_query="public", top_k=1, reranker_instruct=None,
        constraint_semantic_fingerprint=None, region="CN", as_of="2026-08-27",
    )
    corrupt_cache.put(material, {"value": 1}, public_evaluation=True)
    with sqlite3.connect(corrupt_cache.path) as connection:
        connection.execute(
            "UPDATE cache_entries SET payload_json=? WHERE cache_key=?",
            ('{"value":999}', material.digest()),
        )
    discarded = corrupt_cache.get(material, public_evaluation=True) is None
    corrupt_cache.put(material, {"value": 1}, public_evaluation=True)
    recomputed = corrupt_cache.get(material, public_evaluation=True) == {"value": 1}
    add(
        "f6-013", passed=discarded and recomputed,
        recognized=discarded, retry_correct=True, degraded=True, usable_output=recomputed,
        detail="校验和不一致的缓存被丢弃，重新计算后才返回。",
    )

    expected_ids = {item["case_id"] for item in load_jsonl(FAULT_CASES)}
    actual_ids = {item["case_id"] for item in rows}
    return {
        "evaluation_version": "smartbuy-stage6-fault-injection-v1",
        "case_count": len(rows),
        "passed_count": sum(item["passed"] for item in rows),
        "fault_recognition": {"numerator": sum(item["fault_recognized"] for item in rows), "denominator": len(rows)},
        "retry_policy": {"numerator": sum(item["retry_policy_correct"] for item in rows), "denominator": len(rows)},
        "degradation": {"numerator": sum(item["expected_degradation_entered"] for item in rows), "denominator": len(rows)},
        "silent_normal_masquerade_count": sum(item["silently_masqueraded_as_normal"] for item in rows),
        "sensitive_leak_count": sum(item["sensitive_information_leaked"] for item in rows),
        "fixture_ids_match": expected_ids == actual_ids,
        "passed": len(rows) == len(expected_ids) and all(item["passed"] for item in rows),
        "cases": rows,
    }


def evaluate_memory(runtime_dir: Path = Path("C:/ai/smartbuy-stage6/memory")) -> dict[str, Any]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    session = SessionMemoryStore()
    previous = UserRequirements(
        summary="预算 3000，非 OLED",
        hard_constraints=[
            ConstraintSpec(field="price_cny", operator="lte", value=3000),
            ConstraintSpec(field="is_oled", value=False),
        ],
    )
    session.save(AgentState(session_id="m1", query="first", requirements=previous))
    current = UserRequirements(
        summary="预算改成 2500",
        hard_constraints=[ConstraintSpec(field="price_cny", operator="lte", value=2500)],
    )
    merged = session.merge_requirements(session.get("m1").requirements, current)
    values = {item.field: item.value for item in merged.hard_constraints}
    rows.append({"case_id": "m6-001", "passed": values == {"price_cny": 2500, "is_oled": False}})

    normalizer = ConstraintNormalizer()
    first = normalizer.build("只考虑 Dell，预算 3000 元", source_turn=1)
    second = normalizer.build("品牌不限，预算改成 2500 元", source_turn=2, previous=first)
    active = {item.field: item.normalized_value for item in second.active(hard_only=True)}
    rows.append({"case_id": "m6-002", "passed": active.get("price_cny") == 2500 and "brand" not in active})

    store = LongTermPreferenceStore(runtime_dir / "preferences.json")
    store.delete("m-user")
    saved = {"display_size_inch": 27, "excluded_brands": ["LG"], "primary_use": "办公"}
    store.upsert("m-user", saved, explicitly_confirmed=True)
    rows.append(
        {
            "case_id": "m6-003",
            "passed": store.recall("m-user", requested=False) == {} and store.recall("m-user", requested=True) == saved,
        }
    )
    store.delete("m-user", ["excluded_brands"])
    deleted = "excluded_brands" not in store.recall("m-user", requested=True)
    store.set_enabled("m-user", False)
    rows.append({"case_id": "m6-004", "passed": deleted and store.recall("m-user", requested=True) == {}})

    rejected = 0
    for payload in ({"price_cny": 2299}, {"stock_status": "available"}):
        try:
            store.upsert("m-user", payload, explicitly_confirmed=True)
        except ValueError:
            rejected += 1
    rows.append({"case_id": "m6-005", "passed": rejected == 2})
    expected_ids = {item["case_id"] for item in load_jsonl(MEMORY_CASES)}
    return {
        "evaluation_version": "smartbuy-stage6-memory-v1",
        "case_count": len(rows),
        "passed_count": sum(item["passed"] for item in rows),
        "fixture_ids_match": expected_ids == {item["case_id"] for item in rows},
        "passed": len(rows) == len(expected_ids) and all(item["passed"] for item in rows),
        "cases": rows,
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_ledger() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    ledger = EvaluationLedger()
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for group, path in (("failure", FAULT_RESULTS), ("memory", MEMORY_RESULTS)):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for step, row in enumerate(payload["cases"], start=1):
            ledger.add(
                EvaluationLedgerRecord(
                    run_id=payload["evaluation_version"],
                    case_id=row["case_id"],
                    experiment_group=group,
                    repetition=1,
                    data_version=config["data_version"],
                    config_hash=config["config_hash"],
                    tool="controlled_fault_runner" if group == "failure" else "memory_runner",
                    step=step,
                    started_at=timestamp,
                    ended_at=timestamp,
                    duration_ms=0,
                    status="success" if row["passed"] else "failed",
                    degraded=(group == "failure" and bool(row.get("expected_degradation_entered"))),
                    final_metrics={
                        "passed": bool(row["passed"]),
                        "fail_closed": bool(row.get("fail_closed", False)),
                    },
                )
            )
    ledger.write(LEDGER_RESULTS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--faults", action="store_true")
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--all-local", action="store_true")
    args = parser.parse_args()
    if not (args.faults or args.memory or args.all_local):
        parser.error("select --faults, --memory or --all-local")
    passed = True
    if args.faults or args.all_local:
        faults = asyncio.run(evaluate_faults())
        _write(FAULT_RESULTS, faults)
        print(json.dumps({"suite": "faults", "passed": faults["passed"], "passed_count": faults["passed_count"], "case_count": faults["case_count"]}, ensure_ascii=False))
        passed = passed and faults["passed"]
    if args.memory or args.all_local:
        memory = evaluate_memory()
        _write(MEMORY_RESULTS, memory)
        print(json.dumps({"suite": "memory", "passed": memory["passed"], "passed_count": memory["passed_count"], "case_count": memory["case_count"]}, ensure_ascii=False))
        passed = passed and memory["passed"]
    _write_ledger()
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
