"""One-shot real default-Portfolio evaluation with write-once raw records."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime

from smartbuy.eval.fact_completion_independent.preflight import main as production_audit
from smartbuy.eval.v2_9i_independent.run import record, safe_text, verify_freeze
from smartbuy.eval.v2_9i_independent.score_v2 import all_rows, score_case_v2

from .aggregate import aggregate
from .freeze import BASE, OLD, PRODUCTION, ROOT, file_hash, stable


def verified_inputs():
    verify_freeze()
    frozen = json.loads((BASE / "freeze.json").read_text(encoding="utf8"))
    assert file_hash(OLD / "freeze.json") == frozen["original_freeze_sha256"]
    assert file_hash(OLD / "adapter_revision_freeze.json") == frozen["adapter_freeze_sha256"]
    for name, expected in json.loads((OLD / "adapter_revision_freeze.json").read_text(encoding="utf8"))["files"].items():
        assert file_hash(OLD / name) == expected
    for name, expected in frozen["files"].items():
        assert file_hash(BASE / name) == expected, name
    selection = json.loads((BASE / "selection.json").read_text(encoding="utf8"))
    cases = {case["case_id"]: case for case in map(json.loads, (OLD / "trusted_cases.jsonl").read_text(encoding="utf8").splitlines())}
    selected = [cases[entry["case_id"]] for entry in selection["cases"]]
    used = {row["case_id"] for row in all_rows()}
    assert used == set(selection["excluded_previously_run"])
    assert len(selected) == 79 and not used.intersection(case["case_id"] for case in selected)
    for case, entry in zip(selected, selection["cases"], strict=True):
        assert stable(case) == entry["case_sha256"]
    return frozen, selected, json.loads((OLD / "gold_catalog.json").read_text(encoding="utf8"))


def runtime_environment():
    inherited = [key for key in os.environ if key.startswith(("PROOFPICK_", "SMARTBUY_"))]
    assert not inherited, "undeclared_runtime_overrides:" + ",".join(sorted(inherited))
    runtime = "C:/ppv2rc3evalrun"
    os.environ.update({"SMARTBUY_DB_PATH": runtime + "/monitor/smartbuy_monitors_v1.sqlite",
                       "SMARTBUY_INDEX_PATH": runtime + "/monitor/vector_store_text_embedding_v4_1024",
                       "SMARTBUY_MEMORY_PATH": runtime + "/monitor/trusted79_preferences.json",
                       "PROOFPICK_V2_RUNTIME_ROOT": runtime + "/v2",
                       "PROOFPICK_V2_MEMORY_PATH": runtime + "/v2/trusted79_memory",
                       "PROOFPICK_DOMAIN_AGENT_ENABLED": "true", "UTU_LOG_LEVEL": "ERROR"})


async def main():
    frozen, cases, catalog = verified_inputs()
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT), "commit freeze before execution"
    production = production_audit()
    assert production["git_blob_aggregate_sha256"] == json.loads((BASE / "preflight.json").read_text(encoding="utf8"))["git_blob_aggregate_sha256"]
    runtime_environment()
    import httpx
    from fastapi import FastAPI

    api = importlib.import_module("smartbuy.api.router")
    app = FastAPI()
    app.include_router(api.router)
    run_id = "trusted79-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    results = BASE / "results"
    results.mkdir(exist_ok=True)
    raw, scores = [], []
    cumulative = 0.0
    stop_reason = "completed"
    with (results / "started.json").open("x", encoding="utf8", newline="\n") as handle:
        record(handle, {"run_id": run_id, "freeze_sha256": file_hash(BASE / "freeze.json"),
                        "production_commit": PRODUCTION, "evaluation_commit": subprocess.check_output(
                            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                        "budget_cny": frozen["budget_cny"], "planned": len(cases)})
    try:
        with (results / "first.jsonl").open("x", encoding="utf8", newline="\n") as handle:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://trusted79-eval.local") as client:
                for case in cases:
                    verified_inputs()
                    if cumulative + frozen["reserve_before_task_cny"] > frozen["budget_cny"]:
                        stop_reason = "budget_stop"
                        break
                    provider = api.get_smartbuy_agent().provider if case["domain"] == "monitor" else api._portfolio_runtimes.get(case["domain"]).provider
                    before = len(provider.ledger.snapshot())
                    started_at = datetime.now(UTC).isoformat()
                    started = time.perf_counter()
                    response, error, status = {}, None, None
                    try:
                        http = await asyncio.wait_for(client.post("/api/smartbuy/portfolio/run", json={
                            "domain_id": case["domain"], "mode": "trusted", "query": case["query"],
                            "session_id": run_id + "-" + case["case_id"],
                            "user_id": "trusted79-independent-user", "use_long_term_memory": False,
                        }), timeout=frozen["timeout_seconds"])
                        status, response = http.status_code, http.json()
                        if status != 200:
                            error = {"type": "HTTPError", "status": status}
                    except Exception as exc:
                        error = {"type": type(exc).__name__}
                    usage = provider.ledger.snapshot()[before:]
                    cumulative += sum(float(u.get("estimated_cost_cny", 0)) for u in usage)
                    row = {"case_id": case["case_id"], "run_id": run_id, "production_commit": PRODUCTION,
                           "started_at": started_at, "http_status": status, "response": response,
                           "error": error, "usage": usage, "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                           "estimated_cumulative_cost_cny": cumulative, "checkpoint_recoveries": 0}
                    record(handle, row)
                    raw.append(row)
                    try:
                        score = score_case_v2(case, row, catalog)
                    except Exception as exc:
                        stop_reason = "harness_error:" + type(exc).__name__
                        print(safe_text({"case_id": case["case_id"], "stop": stop_reason}), flush=True)
                        break
                    scores.append(score)
                    print(safe_text({"done": len(raw), "case_id": case["case_id"], "passed": score["passed"],
                                     "reasons": score["reasons"], "safety": score["safety"], "cost": round(cumulative, 7)}), flush=True)
                    if score["safety"]:
                        stop_reason = "safety_stop_requires_audit"
                        break
                    if any(not u.get("success") or "estimated_cost_cny" not in u
                           or int(u.get("input_tokens", 0)) + int(u.get("output_tokens", 0)) <= 0 for u in usage):
                        stop_reason = "usage_or_provider_failure_requires_audit"
                        break
                    if cumulative >= frozen["budget_cny"]:
                        stop_reason = "budget_stop"
                        break
    except Exception as exc:
        stop_reason = "runner_failure:" + type(exc).__name__
        print(safe_text({"stop": stop_reason}), flush=True)
    finally:
        if api._agent:
            await api._agent.provider.aclose()
        await api._portfolio_runtimes.close()
        with (results / "first_scores.json").open("x", encoding="utf8", newline="\n") as handle:
            output = {"run_id": run_id, "stop_reason": stop_reason, "summary": aggregate(scores, raw),
                      "cases": scores, "scorer": "original-score-v2-unchanged", "budget_cny": frozen["budget_cny"]}
            record(handle, output)
        print(safe_text({key: value for key, value in output.items() if key != "cases"}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
