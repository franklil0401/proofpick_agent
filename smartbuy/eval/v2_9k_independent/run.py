"""RC4 single-use evaluation via the actual FastAPI default portfolio route."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from smartbuy.eval.v2_9i_independent.run import record, safe_text, verify_freeze
from smartbuy.eval.v2_9i_independent.score import summarize
from smartbuy.eval.v2_9i_independent.score_v2 import all_rows, score_case_v2

BASE = Path(__file__).resolve().parent
OLD = BASE.with_name("v2_9i_independent")
RUNTIME = Path("C:/ppv2rc3evalrun")
EXPOSED = {f"rc3i-monitor-{n:03}" for n in (1, 5, 7, 11)}


def runtime_environment():
    inherited = [k for k in os.environ if k.startswith(("PROOFPICK_", "SMARTBUY_"))]
    if inherited:
        raise RuntimeError("undeclared_runtime_overrides:" + ",".join(sorted(inherited)))
    os.environ.update({
        "SMARTBUY_DB_PATH": str(RUNTIME / "monitor/smartbuy_monitors_v1.sqlite"),
        "SMARTBUY_INDEX_PATH": str(RUNTIME / "monitor/vector_store_text_embedding_v4_1024"),
        "SMARTBUY_MEMORY_PATH": str(RUNTIME / "monitor/rc4_preferences.json"),
        "PROOFPICK_V2_RUNTIME_ROOT": str(RUNTIME / "v2"),
        "PROOFPICK_V2_MEMORY_PATH": str(RUNTIME / "v2/rc4_memory"),
        "PROOFPICK_DOMAIN_AGENT_ENABLED": "true",
        "UTU_LOG_LEVEL": "ERROR",
    })


def load_verified():
    verify_freeze()
    revision = json.loads((OLD / "adapter_revision_freeze.json").read_text(encoding="utf8"))
    for name, expected in revision["files"].items():
        assert hashlib.sha256((OLD / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == expected
    freeze = json.loads((BASE / "freeze.json").read_text(encoding="utf8"))
    for name, expected in freeze["files"].items():
        assert hashlib.sha256((BASE / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == expected
    cases = [json.loads(x) for x in (OLD / "trusted_cases.jsonl").read_text(encoding="utf8").splitlines()]
    catalog = json.loads((OLD / "gold_catalog.json").read_text(encoding="utf8"))
    return cases, catalog


async def main(phase):
    cases, catalog = load_verified()
    used = {row["case_id"] for row in all_rows()}
    assert len(used) == 11 and EXPOSED <= used
    if phase == "exposed":
        selected = [c for c in cases if c["case_id"] in EXPOSED]
        prior_cost = 0.0
    else:
        prior = json.loads((BASE / "results/exposed_scores.json").read_text(encoding="utf8"))
        assert prior["summary"]["passed"] == prior["summary"]["total"] == 4
        assert not prior["summary"]["safety"]
        selected = [c for c in cases if c["case_id"] not in used]
        assert len(selected) == 79
        prior_cost = prior["estimated_cost_cny"]
    runtime_environment()
    import httpx
    from fastapi import FastAPI

    api = importlib.import_module("smartbuy.api.router")
    app = FastAPI()
    app.include_router(api.router)
    cumulative = prior_cost
    scores = []
    run_id = "rc4-" + phase + "-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    results = BASE / "results"
    results.mkdir(exist_ok=True)
    stop_reason = "completed"
    try:
        with (results / f"{phase}_first.jsonl").open("x", encoding="utf8", newline="\n") as handle:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://rc4-eval.local") as client:
                for case in selected:
                    if cumulative + 0.25 > 2.0:
                        stop_reason = "budget_stop"
                        break
                    domain = case["domain"]
                    provider = api.get_smartbuy_agent().provider if domain == "monitor" else api._portfolio_runtimes.get(domain).provider
                    before = len(provider.ledger.snapshot())
                    started_at = datetime.now(UTC).isoformat()
                    started = time.perf_counter()
                    response, error, status = {}, None, None
                    try:
                        http = await asyncio.wait_for(client.post("/api/smartbuy/portfolio/run", json={
                            "domain_id": domain, "mode": "trusted", "query": case["query"],
                            "session_id": run_id + "-" + case["case_id"],
                            "user_id": "rc4-independent-user", "use_long_term_memory": False,
                        }), timeout=180)
                        status = http.status_code
                        response = http.json()
                        if status != 200:
                            error = {"type": "HTTPError", "status": status}
                    except Exception as exc:
                        error = {"type": type(exc).__name__}
                    usage = provider.ledger.snapshot()[before:]
                    cumulative += sum(float(u.get("estimated_cost_cny", 0)) for u in usage)
                    row = {"case_id": case["case_id"], "phase": phase, "run_id": run_id,
                           "production_commit": "99c7bccc523addc7e8904571dbe8e20a24615c66",
                           "started_at": started_at, "http_status": status,
                           "response": response, "error": error, "usage": usage,
                           "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                           "estimated_cumulative_cost_cny": cumulative, "checkpoint_recoveries": 0}
                    record(handle, row)
                    try:
                        score = score_case_v2(case, row, catalog)
                    except Exception as exc:
                        stop_reason = "harness_error:" + type(exc).__name__
                        print(safe_text({"case_id": case["case_id"], "stop": stop_reason}), flush=True)
                        break
                    scores.append(score)
                    print(safe_text({"case_id": case["case_id"], "passed": score["passed"],
                                     "reasons": score["reasons"], "safety": score["safety"],
                                     "cost": round(cumulative, 7)}), flush=True)
                    if score["safety"]:
                        stop_reason = "safety_stop_requires_audit"
                        break
    finally:
        if api._agent:
            await api._agent.provider.aclose()
        await api._portfolio_runtimes.close()
    output = {"phase": phase, "planned_count": len(selected), "stop_reason": stop_reason,
              "summary": summarize(scores), "cases": scores, "estimated_cost_cny": cumulative,
              "budget_limit_cny": 2.0,
              "note": "Old 90-task release boolean is not applicable to this separate phase denominator."}
    with (results / f"{phase}_scores.json").open("x", encoding="utf8", newline="\n") as handle:
        record(handle, output)
    print(safe_text({k: v for k, v in output.items() if k != "cases"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["exposed", "unseen"])
    asyncio.run(main(parser.parse_args().phase))
