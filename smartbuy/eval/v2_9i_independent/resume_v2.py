"""Authorized continuation: excludes all case IDs already present in raw results."""
from __future__ import annotations

import asyncio
import importlib
import json
import time
from datetime import UTC, datetime

from .run import BASE, record, runtime_environment, safe_text, verify_freeze
from .score_v2 import all_rows, score_case_v2


async def main():
    frozen = verify_freeze()
    from hashlib import sha256
    revision = json.loads((BASE / "adapter_revision_freeze.json").read_text(encoding="utf8"))
    for name, expected in revision["files"].items():
        assert sha256((BASE / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == expected
    existing = all_rows()
    assert len(existing) == 2, "This continuation is authorized only after the preserved first two cases"
    used_ids = {r["case_id"] for r in existing}
    catalog = json.loads((BASE / "gold_catalog.json").read_text(encoding="utf8"))
    cases = [json.loads(x) for x in (BASE / "trusted_cases.jsonl").read_text(encoding="utf8").splitlines()]
    for c in cases:
        for r in existing:
            if c["case_id"] == r["case_id"]:
                assert not score_case_v2(c, r, catalog)["safety"], "Prior product safety failure cannot be waived"
    runtime_environment()
    api = importlib.import_module("smartbuy.api.router")
    cumulative = frozen["bootstrap_cost_cny"] + sum(float(u["estimated_cost_cny"]) for r in existing for u in r["usage"])
    run_id = "rc3i-continuation-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    try:
        with (BASE / "results/trusted_continuation_first.jsonl").open("x", encoding="utf8", newline="\n") as handle:
            for case in cases:
                if case["case_id"] in used_ids:
                    continue
                if cumulative + .25 > 2:
                    print("BUDGET_STOP", flush=True)
                    break
                domain = case["domain"]
                provider = api.get_smartbuy_agent().provider if domain == "monitor" else api._portfolio_runtimes.get(domain).provider
                before = len(provider.ledger.snapshot())
                start = time.perf_counter()
                response, error = None, None
                try:
                    response = await asyncio.wait_for(api.portfolio_run(api.PortfolioRunRequest(
                        domain_id=domain, query=case["query"], session_id=case["case_id"],
                        user_id="rc3-independent-user", use_long_term_memory=False), memory_identity=None), timeout=180)
                except Exception as exc:
                    error = {"type": type(exc).__name__, "detail": getattr(exc, "detail", None)}
                usage = provider.ledger.snapshot()[before:]
                cumulative += sum(float(u.get("estimated_cost_cny", 0)) for u in usage)
                row = {"case_id": case["case_id"], "run_id": run_id, "response": response or {}, "error": error,
                       "latency_ms": round((time.perf_counter() - start) * 1000, 3), "usage": usage,
                       "estimated_cumulative_cost_cny": cumulative, "checkpoint_recoveries": 0}
                record(handle, row)
                score = score_case_v2(case, row, catalog)
                print(safe_text({"case_id": case["case_id"], "passed": score["passed"], "safety": score["safety"], "cost": round(cumulative, 6)}), flush=True)
                if score["safety"]:
                    with (BASE / "results/trusted_v2_safety_stop.json").open("x", encoding="utf8") as stop:
                        json.dump(score, stop, ensure_ascii=False, indent=2)
                    print("SAFETY_STOP: new product issue requires independent audit", flush=True)
                    break
    finally:
        if api._agent:
            await api._agent.provider.aclose()
        await api._portfolio_runtimes.close()


if __name__ == "__main__":
    asyncio.run(main())
