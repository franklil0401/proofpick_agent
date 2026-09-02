"""Run a frozen qwen-plus quote-to-span set and save a sanitized external artifact."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from smartbuy.config import load_bailian_settings
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.constraint_proposals.models import SpanSource
from smartbuy.constraint_proposals.provider import QwenConstraintProposalProvider
from smartbuy.constraint_proposals.spans import QuoteSpanResolver
from smartbuy.constraints import (
    ConstraintOperator,
    ConstraintProvenance,
    ConstraintSet,
    ConstraintStrength,
    NormalizedConstraint,
)
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.domain_packs.loader import DEFAULT_MONITOR_PACK
from smartbuy.observability import UsageLedger
from smartbuy.providers import BailianAuthError, BailianProvider, RetryPolicy


ROOT = Path(__file__).resolve().parents[2]


def _previous(items: list[dict[str, Any]]) -> ConstraintSet | None:
    if not items:
        return None
    return ConstraintSet(
        constraints=[
            NormalizedConstraint(
                field=item["field"],
                operator=ConstraintOperator(item["operator"]),
                normalized_value=item["value"],
                unit=item.get("unit"),
                hard_or_soft=ConstraintStrength(item["strength"]),
                provenance=ConstraintProvenance.LONG_TERM_PREFERENCE,
                source_text="frozen quote-span context",
                source_turn=1,
                confidence=1.0,
                supported=True,
                active=True,
            )
            for item in items
        ]
    )


def _signature(item: dict[str, Any]) -> str:
    selected = {
        key: item.get(key)
        for key in ("field", "operator", "value", "unit", "strength", "status", "action")
    }
    return json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _proposal_payload(item: Any) -> dict[str, Any]:
    span = item.source_span
    return {
        "field": item.field,
        "operator": item.operator.value if item.operator else None,
        "value": item.normalized_value,
        "unit": item.unit,
        "strength": item.strength.value,
        "status": item.status.value,
        "action": item.action.value,
        "active": item.active,
        "reason": item.reason,
        "proposal_kind": item.proposal_kind.value if item.proposal_kind else None,
        "source_quote": item.source_quote,
        "span_source": item.span_source.value,
        "span": (
            {"start": span.start, "end": span.end, "text": span.text}
            if span
            else None
        ),
    }


class CapturingProvider:
    """Capture the public function result without retaining messages or credentials."""

    def __init__(self, delegate: BailianProvider) -> None:
        self.delegate = delegate
        self.settings = delegate.settings
        self.last: dict[str, Any] = {}

    async def chat(self, messages: Any, **kwargs: Any) -> Any:
        tools = kwargs.get("tools") or []
        schema = tools[0]["function"]["parameters"] if tools else {}
        result = await self.delegate.chat(messages, **kwargs)
        calls = result.data.get("tool_calls") or []
        call = calls[0] if len(calls) == 1 else {}
        function = call.get("function") or {}
        raw_arguments = function.get("arguments", "{}")
        try:
            arguments = (
                json.loads(raw_arguments)
                if isinstance(raw_arguments, str)
                else raw_arguments
            )
        except (json.JSONDecodeError, TypeError):
            arguments = None
        schema_errors = (
            [
                error.validator
                for error in Draft202012Validator(schema).iter_errors(arguments)
            ]
            if arguments is not None
            else ["arguments_not_json"]
        )
        proposals = arguments.get("proposals", []) if isinstance(arguments, dict) else []
        query = str(messages[-1].get("content", ""))
        resolver = QuoteSpanResolver()
        quote_total = quote_unique = quote_resolvable = 0
        if isinstance(proposals, list):
            for proposal in proposals:
                if not isinstance(proposal, dict):
                    continue
                quote_total += 1
                resolved = resolver.resolve(
                    query,
                    proposal.get("quote"),
                    occurrence=proposal.get("occurrence"),
                )
                quote_unique += resolved.match_count == 1
                quote_resolvable += resolved.resolved
        self.last = {
            "function_name": function.get("name"),
            "tool_call_count": len(calls),
            "schema_valid": not schema_errors,
            "schema_error_validators": sorted(set(schema_errors)),
            "raw_proposal_count": len(proposals) if isinstance(proposals, list) else 0,
            "quote_total": quote_total,
            "quote_unique": quote_unique,
            "quote_resolvable": quote_resolvable,
            "attempts": result.attempts,
            "latency_ms": round(result.latency_ms, 3),
            "input_tokens": int(result.usage.get("input_tokens", 0)),
            "output_tokens": int(result.usage.get("output_tokens", 0)),
        }
        return result


async def run(
    cases_path: Path,
    manifest_path: Path,
    output: Path,
    run_type: str,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("frozen live output already exists; refusing to overwrite")
    try:
        output.resolve().relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("live output must stay outside the Git workspace")

    payload = cases_path.read_bytes()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(payload).hexdigest()
    if digest != manifest["sha256"]:
        raise RuntimeError("quote-span case hash mismatch")
    cases = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    if len(cases) != manifest["case_count"]:
        raise RuntimeError("quote-span case count mismatch")
    pack = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
    probe = NaturalConstraintEngine(pack)
    nonempty = [
        case["case_id"]
        for case in cases
        if probe.parser.parse(case["query"], source_turn=2)
    ]
    if nonempty:
        raise RuntimeError("live set is not isolated from deterministic rules")

    settings = load_bailian_settings()
    ledger = UsageLedger()
    allowed = {
        field.field_id for field in pack.fields.values() if field.constraint_enabled
    }
    records: list[dict[str, Any]] = []
    tp = fp = fn = exact = 0
    clear_tp = clear_fp = clear_fn = 0
    schema_success = function_success = http_success = 0
    quote_total = quote_unique = quote_resolvable = server_span = 0
    fabricated_quote_accepted = non_domain_active = ambiguous_checker = 0
    unsupported_active = injection_active = 0
    latencies: list[float] = []
    async with BailianProvider(
        settings,
        retry_policy=RetryPolicy(max_retries=2),
        ledger=ledger,
    ) as real_provider:
        for case in cases:
            capture = CapturingProvider(real_provider)
            engine = NaturalConstraintEngine(
                pack,
                QwenConstraintProposalProvider(capture),
                max_provider_calls=1,
                max_cost_cny=0.10,
            )
            record: dict[str, Any] = {
                "case_id": case["case_id"],
                "category": case["category"],
                "status": "provider_error",
            }
            try:
                resolution = await engine.resolve(
                    case["query"],
                    source_turn=2 if case.get("previous") else 1,
                    previous=_previous(case.get("previous", [])),
                )
            except Exception as exc:  # only the exception class is persisted
                record["error_category"] = type(exc).__name__
                record["capture"] = capture.last
                records.append(record)
                if isinstance(exc, BailianAuthError):
                    break
                continue
            http_success += 1
            actual = [_proposal_payload(item) for item in resolution.proposals]
            expected_set = {_signature(item) for item in case["expected"]}
            actual_set = {_signature(item) for item in actual}
            tp += len(expected_set & actual_set)
            fp += len(actual_set - expected_set)
            fn += len(expected_set - actual_set)
            task_exact = expected_set == actual_set
            exact += task_exact
            expected_clear = {
                _signature(item)
                for item in case["expected"]
                if item["status"] == "supported"
                and item["strength"] == "hard"
                and item["action"] in {"add", "override"}
            }
            actual_clear = {
                _signature(item)
                for item in actual
                if item["status"] == "supported"
                and item["strength"] == "hard"
                and item["action"] in {"add", "override"}
            }
            clear_tp += len(expected_clear & actual_clear)
            clear_fp += len(actual_clear - expected_clear)
            clear_fn += len(expected_clear - actual_clear)
            schema_success += bool(capture.last.get("schema_valid"))
            function_success += (
                capture.last.get("function_name") == "submit_constraint_proposals"
            )
            quote_total += int(capture.last.get("quote_total", 0))
            quote_unique += int(capture.last.get("quote_unique", 0))
            quote_resolvable += int(capture.last.get("quote_resolvable", 0))
            server_span += sum(
                item["span"] is not None
                and item["span_source"] == SpanSource.SERVER_EXACT_QUOTE.value
                for item in actual
            )
            fabricated_quote_accepted += sum(
                item["active"] and item["span"] is None for item in actual
            )
            non_domain_active += sum(
                item["active"] and item["field"] not in allowed for item in actual
            )
            ambiguous_checker += sum(
                item["active"]
                and item["status"] in {"ambiguous", "needs_confirmation"}
                for item in actual
            )
            unsupported_active += sum(
                item["active"] and item["status"] == "unsupported" for item in actual
            )
            if case["category"].startswith("prompt_injection"):
                injection_active += sum(item["active"] for item in actual)
            latency = float(capture.last.get("latency_ms", 0.0))
            latencies.append(latency)
            record.update(
                {
                    "status": "success",
                    "task_exact": task_exact,
                    "function_name": capture.last.get("function_name"),
                    "schema_valid": capture.last.get("schema_valid", False),
                    "schema_error_validators": capture.last.get(
                        "schema_error_validators", []
                    ),
                    "quote_total": capture.last.get("quote_total", 0),
                    "quote_unique": capture.last.get("quote_unique", 0),
                    "quote_resolvable": capture.last.get("quote_resolvable", 0),
                    "actual": actual,
                    "clarification_state": resolution.clarification_state.value,
                    "provider_calls": resolution.provider_calls,
                    "attempts": capture.last.get("attempts", 0),
                    "input_tokens": resolution.input_tokens,
                    "output_tokens": resolution.output_tokens,
                    "latency_ms": latency,
                    "estimated_cost_cny": round(resolution.estimated_cost_cny, 8),
                }
            )
            records.append(record)
            if ledger.summary()["estimated_cost_cny"] >= manifest["max_cost_cny"]:
                break

    def ratios(a: int, b: int, c: int) -> dict[str, float | int]:
        precision = a / (a + b) if a + b else 0.0
        recall = a / (a + c) if a + c else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {
            "true_positive": a,
            "false_positive": b,
            "false_negative": c,
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
        }

    ordered = sorted(latencies)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] if ordered else 0.0
    usage = ledger.summary()
    result = {
        "schema_version": "proofpick-v2-quote-span-live-result-v1",
        "run_type": run_type,
        "cases_sha256": digest,
        "case_count": len(cases),
        "completed_cases": len(records),
        "model": settings.chat_model,
        "temperature": 0,
        "http_success": f"{http_success}/{len(cases)}",
        "function_name_correct": f"{function_success}/{len(cases)}",
        "schema_success": f"{schema_success}/{len(cases)}",
        "quote_unique": f"{quote_unique}/{quote_total}",
        "quote_resolvable": f"{quote_resolvable}/{quote_total}",
        "server_span_success": f"{server_span}/{quote_total}",
        "all_proposals": ratios(tp, fp, fn),
        "clear_hard_constraints": ratios(clear_tp, clear_fp, clear_fn),
        "task_exact": f"{exact}/{len(cases)}",
        "fabricated_quote_accepted": fabricated_quote_accepted,
        "non_domain_field_active": non_domain_active,
        "ambiguous_unconfirmed_checker_ingress": ambiguous_checker,
        "unsupported_silent_active": unsupported_active,
        "prompt_injection_active_or_privilege_change": injection_active,
        "average_latency_ms": round(statistics.fmean(latencies), 3) if latencies else 0.0,
        "p95_latency_ms": round(p95, 3),
        "api_calls": usage["call_count"],
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "estimated_cost_cny": usage["estimated_cost_cny"],
        "records": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-type", required=True)
    args = parser.parse_args()
    result = asyncio.run(run(args.cases, args.manifest, args.output, args.run_type))
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "records"},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["completed_cases"] == result["case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
