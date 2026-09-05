"""Single-use independent runner. Production modules remain unchanged."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from .score import score_case

BASE = Path(__file__).resolve().parent
RUNTIME = Path("C:/ppv2rc3evalrun")
SECRETS = [os.getenv(k, "") for k in ["Qianwen_api_key", "Qianwen_workspace_id", "ZhiPu_api_key", "BoCha_api_key", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"]]


def safe_text(value):
    text = json.dumps(value, ensure_ascii=False)
    for secret in SECRETS:
        if len(secret) >= 5:
            text = text.replace(secret, "[REDACTED]")
    return text


def record(handle, data):
    handle.write(safe_text(data) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def verify_freeze():
    frozen = json.loads((BASE / "freeze.json").read_text(encoding="utf8"))
    for path, expected in frozen["files"].items():
        actual = hashlib.sha256((BASE / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if actual != expected:
            raise RuntimeError("evaluator_freeze_changed:" + path)
    return frozen


def runtime_environment():
    # Match documented start.ps1, with isolated paths. Do not silently activate optional engines.
    for key in list(os.environ):
        if key.startswith("PROOFPICK_"):
            os.environ.pop(key)
    os.environ.update({
        "SMARTBUY_DB_PATH": str(RUNTIME / "monitor/smartbuy_monitors_v1.sqlite"),
        "SMARTBUY_INDEX_PATH": str(RUNTIME / "monitor/vector_store_text_embedding_v4_1024"),
        "SMARTBUY_MEMORY_PATH": str(RUNTIME / "monitor/eval_preferences.json"),
        "PROOFPICK_V2_RUNTIME_ROOT": str(RUNTIME / "v2"),
        "PROOFPICK_V2_MEMORY_PATH": str(RUNTIME / "v2/eval_memory"),
        "PROOFPICK_DOMAIN_AGENT_ENABLED": "true",
        "UTU_LOG_LEVEL": "ERROR",
    })


async def run_trusted():
    frozen = verify_freeze()
    runtime_environment()
    from smartbuy.api import router as router_export
    import importlib
    api = importlib.import_module("smartbuy.api.router")
    del router_export
    cases = [json.loads(x) for x in (BASE / "trusted_cases.jsonl").read_text(encoding="utf8").splitlines()]
    catalog = json.loads((BASE / "gold_catalog.json").read_text(encoding="utf8"))
    result_dir = BASE / "results"
    result_dir.mkdir(exist_ok=True)
    cumulative = frozen["bootstrap_cost_cny"]
    run_id = "rc3i-trusted-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (result_dir / "trusted_started.json").open("x", encoding="utf8").write(safe_text({"run_id": run_id, "freeze": frozen["identity"], "started_at": datetime.now(UTC).isoformat()}))
    try:
        with (result_dir / "trusted_first.jsonl").open("x", encoding="utf8", newline="\n") as handle:
            for case in cases:
                if cumulative + .25 > 2.0:
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
                cumulative += sum(float(x.get("estimated_cost_cny", 0)) for x in usage)
                row = {"case_id": case["case_id"], "run_id": run_id, "response": response or {}, "error": error,
                       "latency_ms": round((time.perf_counter() - start) * 1000, 3), "usage": usage,
                       "estimated_cumulative_cost_cny": cumulative, "checkpoint_recoveries": 0}
                record(handle, row)
                score = score_case(case, row, catalog)
                print(safe_text({"case_id": case["case_id"], "passed": score["passed"], "safety": score["safety"], "cost": round(cumulative, 6)}), flush=True)
                if score["safety"]:
                    with (result_dir / "trusted_safety_stop.json").open("x", encoding="utf8") as stop:
                        json.dump(score, stop, ensure_ascii=False, indent=2)
                    print("SAFETY_STOP: inspect first result, no production repair or repeat", flush=True)
                    break
    finally:
        if api._agent:
            await api._agent.provider.aclose()
        await api._portfolio_runtimes.close()


async def run_online():
    frozen = verify_freeze()
    if (BASE / "results/trusted_safety_stop.json").exists():
        raise RuntimeError("Trusted safety stop prohibits continuing paid release evaluation")
    from smartbuy.domain_packs import DomainPackRegistry
    from smartbuy.observability import UsageLedger
    from smartbuy.open_research import OpenResearchService, OpenResearchSettings, StaticHTMLExtractor, TemporaryEvidenceStore
    from smartbuy.providers.zhipu_search import ZhipuSourceSearchProvider
    from smartbuy.source_search import SourceSearchRequest, SourceSearchSettings
    from urllib.parse import urlsplit
    cases = [json.loads(x) for x in (BASE / "online_cases.jsonl").read_text(encoding="utf8").splitlines()]
    result_dir = BASE / "results"
    result_dir.mkdir(exist_ok=True)
    cumulative = 0.0
    with (result_dir / "online_first.jsonl").open("x", encoding="utf8", newline="\n") as handle:
        for case in cases:
            if cumulative + .2 > frozen["online_budget_cny"]:
                break
            start = time.perf_counter()
            ledger = UsageLedger()
            settings = SourceSearchSettings(enabled=True, api_key=os.getenv("ZhiPu_api_key"), max_retries=0)
            provider = ZhipuSourceSearchProvider(settings, ledger=ledger)
            opens = OpenResearchSettings(enabled=True, evidence_root=RUNTIME / "open_evidence")
            pack = DomainPackRegistry(BASE.parents[1] / "domain_packs").load(case["domain"])
            service = OpenResearchService(opens, pack, StaticHTMLExtractor(opens), TemporaryEvidenceStore(opens.evidence_root, enabled=True))
            search, outcomes, error = None, [], None
            try:
                request = SourceSearchRequest(query=case["query"], product_category=case["domain"], target_model=case["model"],
                    target_fields=case["fields"], region=case["region"], allowed_domains=case["allowed_domains"],
                    trigger_reason="out_of_catalog_model")
                search = await provider.search(request)
                candidates = (list(search.usable_candidates) + list(search.navigation_candidates))[:3]
                for candidate in candidates:
                    outcome = await service.research(candidate, target_fields=case["fields"], allowed_domains=case["allowed_domains"],
                        provisional_product_id=case["case_id"], configuration=None, user_id="rc3-independent-user", session_id=case["case_id"],
                        thread_id=case["case_id"], request_id=case["case_id"], allow_region_discovery=True)
                    outcomes.append(outcome.model_dump(mode="json"))
                    verified = {f for o in outcomes for f in o["report"]["verified_fields"]}
                    if set(case["fields"]).issubset(verified):
                        break
            except Exception as exc:
                error = {"type": type(exc).__name__}
            finally:
                await provider.aclose()
                await service.aclose()
            usage = ledger.snapshot()
            cumulative += sum(float(x.get("estimated_cost_cny", 0)) for x in usage)
            safety = []
            verified = set()
            for o in outcomes:
                for e in o["evidence"]:
                    host = urlsplit(e["final_url"]).hostname or ""
                    if not any(host == d or host.endswith("." + d) for d in case["allowed_domains"]):
                        safety.append("wrong_domain_evidence")
                    if e["usable_for_trusted_checker"] or o["report"]["trusted_eligible"]:
                        safety.append("open_to_trusted")
                for assessment in o["report"]["field_assessments"]:
                    if assessment["status"] == "matched" and assessment["evidence"]:
                        if any(e["source_region"] != case["region"] for e in assessment["evidence"]):
                            safety.append("wrong_region_matched")
                        else:
                            verified.add(assessment["field_name"])
            row = {"case_id": case["case_id"], "search": search.model_dump(mode="json") if search else None,
                   "outcomes": outcomes, "error": error, "usage": usage,
                   "requested_verified": sorted(set(case["fields"]) & verified),
                   "full_requested_completion": set(case["fields"]).issubset(verified),
                   "safety": sorted(set(safety)), "latency_ms": round((time.perf_counter() - start) * 1000, 3)}
            record(handle, row)
            print(safe_text({"case_id": case["case_id"], "verified": row["requested_verified"], "safety": row["safety"], "cost": cumulative}), flush=True)
            if safety:
                print("ONLINE_SAFETY_STOP", flush=True)
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["trusted", "online"])
    args = parser.parse_args()
    asyncio.run(run_trusted() if args.mode == "trusted" else run_online())
