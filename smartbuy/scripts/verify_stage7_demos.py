"""Run four bounded public demos against the local FastAPI release candidate.

The result contains only fixed public inputs, report summaries, public tool traces,
and aggregate cost/latency already exposed by the sanitized monitor endpoint.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "smartbuy/data/processed/stage7_demo_results.json"


def _request(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310 - loopback URL only
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"local demo endpoint returned HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError("local demo endpoint is unavailable") from exc


def _chat(base_url: str, query: str, *, session_id: str, user_id: str | None = None,
          use_long_term_memory: bool = False) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    payload = _request(
        base_url,
        "POST",
        "/api/smartbuy/chat",
        {
            "query": query,
            "stream": False,
            "session_id": session_id,
            "user_id": user_id,
            "use_long_term_memory": use_long_term_memory,
        },
    )
    return payload["report"], round((time.perf_counter() - started) * 1_000, 3)


def _slim(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_summary": report.get("request_summary"),
        "task_type": report.get("task_type"),
        "tools_used": report.get("tools_used", []),
        "hard_constraints": report.get("hard_constraints", []),
        "candidates": [
            {
                "model_id": item.get("model_id"),
                "region": item.get("region"),
                "overall_status": item.get("overall_status"),
                "eligible": item.get("eligible"),
                "violated_fields": item.get("violated_fields", []),
                "unknown_fields": item.get("unknown_fields", []),
                "conflict_fields": item.get("conflict_fields", []),
                "price_cny": item.get("price_cny"),
                "price_observed_at": item.get("price_observed_at"),
            }
            for item in report.get("candidates", [])
        ],
        "recommended_model_ids": report.get("recommended_model_ids", []),
        "unresolved_facts": report.get("unresolved_facts", []),
        "degraded_states": report.get("degraded_states", []),
        "abstained": report.get("abstained"),
        "stop_reason": report.get("stop_reason"),
        "constraint_checker_version": (
            (report.get("constraint_verification") or {}).get("verifier_version")
        ),
        "trace": report.get("trace", []),
        "evidence": report.get("evidence", []),
        "usage": report.get("usage", {}),
    }


def _constraint_values(report: dict[str, Any]) -> dict[str, Any]:
    return {item.get("field"): item.get("value") for item in report.get("hard_constraints", [])}


def run(base_url: str) -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    fact_query = "Dell U2723QE 的屏幕尺寸和分辨率是多少？"
    fact, elapsed = _chat(base_url, fact_query, session_id="stage7-demo-fact")
    fact_tools = set(fact.get("tools_used", []))
    fact_checks = {
        "kb_search_called": "kb_search" in fact_tools,
        "no_sql_or_web": fact_tools.isdisjoint({"text2sql", "web_search"}),
        "evidence_present": bool(fact.get("evidence")),
    }
    results.append({
        "demo_id": "demo-1-fact",
        "input": fact_query,
        "elapsed_ms": elapsed,
        "checks": fact_checks,
        "passed": all(fact_checks.values()),
        "report": _slim(fact),
    })

    complex_query = "中国版中找 27 英寸、4K、USB-C 视频且供电不少于 90W 的显示器。"
    complex_report, elapsed = _chat(base_url, complex_query, session_id="stage7-demo-complex")
    complex_tools = set(complex_report.get("tools_used", []))
    complex_checks = {
        "required_tools_called": {"text2sql", "kb_search", "evidence_check"} <= complex_tools,
        "checker_completed": bool(complex_report.get("constraint_verification")),
        "no_violating_recommendation": all(
            item.get("eligible") and not item.get("violated_fields")
            for item in complex_report.get("candidates", [])
            if item.get("model_id") in complex_report.get("recommended_model_ids", [])
        ),
        "dependent_trace_present": any(
            item.get("parent_step") is not None for item in complex_report.get("trace", [])
        ),
    }
    results.append({
        "demo_id": "demo-2-multihop",
        "input": complex_query,
        "elapsed_ms": elapsed,
        "checks": complex_checks,
        "passed": all(complex_checks.values()),
        "report": _slim(complex_report),
    })

    memory_user = "stage7-demo-user"
    _request(base_url, "DELETE", f"/api/smartbuy/memory/{memory_user}", {})
    first_query = "预算不超过 3500 元，主要办公，想要 27 英寸 4K 显示器。"
    first, first_elapsed = _chat(
        base_url, first_query, session_id="stage7-demo-memory-session", user_id=memory_user
    )
    follow_query = "再便宜一点，预算改为 2500 元以内，而且不要 OLED。"
    follow, follow_elapsed = _chat(
        base_url, follow_query, session_id="stage7-demo-memory-session", user_id=memory_user
    )
    _request(
        base_url,
        "PUT",
        f"/api/smartbuy/memory/{memory_user}",
        {
            "preferences": {
                "budget_max_cny": 2500,
                "display_size_inch": 27,
                "exclude_oled": True,
            },
            "explicitly_confirmed": True,
        },
    )
    recalled_query = "请按我已确认的偏好筛选 4K 显示器。"
    recalled, recalled_elapsed = _chat(
        base_url,
        recalled_query,
        session_id="stage7-demo-memory-new-session",
        user_id=memory_user,
        use_long_term_memory=True,
    )
    before_delete = _request(base_url, "GET", f"/api/smartbuy/memory/{memory_user}")
    _request(base_url, "DELETE", f"/api/smartbuy/memory/{memory_user}", {})
    after_delete = _request(base_url, "GET", f"/api/smartbuy/memory/{memory_user}")
    follow_values = _constraint_values(follow)
    recalled_values = _constraint_values(recalled)
    memory_checks = {
        "same_session_budget_overridden": follow_values.get("price_cny") == 2500,
        "same_session_non_oled_added": follow_values.get("is_oled") is False,
        "confirmed_preferences_saved": bool(before_delete.get("preferences")),
        "new_session_preferences_recalled": (
            recalled_values.get("price_cny") == 2500
            and recalled_values.get("display_size_inch") == 27
            and recalled_values.get("is_oled") is False
        ),
        "delete_removes_preferences": not after_delete.get("preferences"),
    }
    results.append({
        "demo_id": "demo-3-memory",
        "input": [first_query, follow_query, recalled_query],
        "elapsed_ms": round(first_elapsed + follow_elapsed + recalled_elapsed, 3),
        "checks": memory_checks,
        "passed": all(memory_checks.values()),
        "reports": [_slim(first), _slim(follow), _slim(recalled)],
        "memory_after_delete": after_delete,
    })

    conflict_query = "BenQ PD2705U 的官方资料对 USB-C 供电数值是否一致？"
    conflict, elapsed = _chat(base_url, conflict_query, session_id="stage7-demo-conflict")
    conflict_checks = {
        "conflict_visible": any(
            item.get("status") == "conflict" for item in conflict.get("unresolved_facts", [])
        ),
        "no_recommendation": not conflict.get("recommended_model_ids"),
        "abstained": conflict.get("abstained") is True,
        "multiple_sources_visible": any(
            len(item.get("evidence", [])) >= 2
            for item in conflict.get("unresolved_facts", [])
            if item.get("status") == "conflict"
        ),
    }
    results.append({
        "demo_id": "demo-4-conflict",
        "input": conflict_query,
        "elapsed_ms": elapsed,
        "checks": conflict_checks,
        "passed": all(conflict_checks.values()),
        "report": _slim(conflict),
    })

    monitor = _request(base_url, "GET", "/api/smartbuy/monitor")
    return {
        "version": "stage7-demo-v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "demo_count": len(results),
        "passed": sum(item["passed"] for item in results),
        "all_passed": all(item["passed"] for item in results),
        "results": results,
        "monitor_summary": {
            "run_count": monitor.get("run_count"),
            "average_latency_ms": monitor.get("average_latency_ms"),
            "p95_latency_ms": monitor.get("p95_latency_ms"),
            "estimated_cost_cny": monitor.get("estimated_cost_cny"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.base_url.startswith("http://127.0.0.1:"):
        raise SystemExit("only a loopback FastAPI endpoint is allowed")
    result = run(args.base_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({
        "status": "completed" if result["all_passed"] else "failed",
        "passed": result["passed"],
        "total": result["demo_count"],
        "estimated_cost_cny": result["monitor_summary"]["estimated_cost_cny"],
        "output": args.output.as_posix(),
    }, ensure_ascii=False))
    if not result["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
