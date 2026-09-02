"""Run the frozen V2-5B qwen-plus holdout once and emit a sanitized artifact."""

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
from smartbuy.constraint_proposals.provider import QwenConstraintProposalProvider
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
CASES = ROOT / "smartbuy/eval/v2_stage5b_live_holdout.jsonl"
MANIFEST = ROOT / "smartbuy/eval/v2_stage5b_live_holdout_manifest.json"


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
                source_text="frozen live holdout context",
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
        "span": {
            "start": item.source_span.start,
            "end": item.source_span.end,
            "text": item.source_span.text,
        },
    }


class CapturingProvider:
    """Capture only the public tool-call contract; never retain messages or headers."""

    def __init__(self, delegate: BailianProvider) -> None:
        self.delegate = delegate
        self.settings = delegate.settings
        self.last: dict[str, Any] = {}

    async def chat(self, _messages: Any, **kwargs: Any) -> Any:
        tools = kwargs.get("tools") or []
        schema = tools[0]["function"]["parameters"] if tools else {}
        result = await self.delegate.chat(_messages, **kwargs)
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
        schema_errors: list[str] = []
        if arguments is None:
            schema_errors.append("arguments_not_json")
        else:
            schema_errors = [
                error.validator for error in Draft202012Validator(schema).iter_errors(arguments)
            ]
        proposals = arguments.get("proposals", []) if isinstance(arguments, dict) else []
        span_total = span_exact = 0
        if isinstance(proposals, list):
            for proposal in proposals:
                if not isinstance(proposal, dict):
                    continue
                span_total += 1
                try:
                    start = int(proposal["span_start"])
                    end = int(proposal["span_end"])
                    text = str(proposal["span_text"])
                except (KeyError, TypeError, ValueError):
                    continue
                # The query is not retained; exactness is evaluated before returning.
                query = str(_messages[-1].get("content", ""))
                span_exact += 0 <= start < end <= len(query) and query[start:end] == text
        self.last = {
            "function_name": function.get("name"),
            "tool_call_count": len(calls),
            "schema_valid": not schema_errors,
            "schema_error_validators": sorted(set(schema_errors)),
            "raw_proposal_count": len(proposals) if isinstance(proposals, list) else 0,
            "raw_span_total": span_total,
            "raw_span_exact": span_exact,
            "attempts": result.attempts,
            "latency_ms": round(result.latency_ms, 3),
            "input_tokens": int(result.usage.get("input_tokens", 0)),
            "output_tokens": int(result.usage.get("output_tokens", 0)),
        }
        return result


async def run(output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("first-run output already exists; refusing to overwrite")
    try:
        output.resolve().relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("live runtime output must stay outside the Git workspace")

    payload = CASES.read_bytes()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    digest = hashlib.sha256(payload).hexdigest()
    if digest != manifest["sha256"]:
        raise RuntimeError("live holdout hash mismatch")
    cases = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    if len(cases) != manifest["case_count"]:
        raise RuntimeError("live holdout count mismatch")

    pack = DomainPackLoader().load(DEFAULT_MONITOR_PACK)
    parser_probe = NaturalConstraintEngine(pack)
    nonempty = [
        case["case_id"]
        for case in cases
        if parser_probe.parser.parse(case["query"], source_turn=2)
    ]
    if nonempty:
        raise RuntimeError("live holdout is not isolated from deterministic rules")

    settings = load_bailian_settings()
    ledger = UsageLedger()
    records: list[dict[str, Any]] = []
    tp = fp = fn = task_exact = 0
    schema_success = tool_name_success = 0
    span_total = span_exact = 0
    hallucinated_span_accepted = non_domain_active = ambiguous_checker_ingress = 0
    unsupported_active = prompt_injection_active = 0
    latencies: list[float] = []
    allowed = {
        field.field_id for field in pack.fields.values() if field.constraint_enabled
    }
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
                "model": settings.chat_model,
                "temperature": 0,
                "status": "provider_error",
            }
            try:
                resolution = await engine.resolve(
                    case["query"],
                    source_turn=2 if case.get("previous") else 1,
                    previous=_previous(case.get("previous", [])),
                )
            except Exception as exc:  # sanitized class only
                record["error_category"] = type(exc).__name__
                record["capture"] = capture.last
                records.append(record)
                if isinstance(exc, BailianAuthError):
                    break
                continue

            actual = [_proposal_payload(item) for item in resolution.proposals]
            expected_signatures = {_signature(item) for item in case["expected"]}
            actual_signatures = {_signature(item) for item in actual}
            tp += len(expected_signatures & actual_signatures)
            fp += len(actual_signatures - expected_signatures)
            fn += len(expected_signatures - actual_signatures)
            exact = expected_signatures == actual_signatures
            task_exact += exact
            schema_success += bool(capture.last.get("schema_valid"))
            tool_name_success += (
                capture.last.get("function_name") == "submit_constraint_proposals"
            )
            raw_span_total = int(capture.last.get("raw_span_total", 0))
            raw_span_exact = int(capture.last.get("raw_span_exact", 0))
            span_total += raw_span_total
            span_exact += raw_span_exact
            invalid_spans = {
                item["field"] for item in actual if item["reason"] == "source_span_invalid"
            }
            hallucinated_span_accepted += sum(
                item["active"] and item["field"] in invalid_spans for item in actual
            )
            non_domain_active += sum(
                item["active"] and item["field"] not in allowed for item in actual
            )
            ambiguous_checker_ingress += sum(
                item["active"]
                and item["status"] in {"ambiguous", "needs_confirmation"}
                for item in actual
            )
            unsupported_active += sum(
                item["active"] and item["status"] == "unsupported" for item in actual
            )
            if case["category"].startswith("prompt_injection"):
                prompt_injection_active += sum(item["active"] for item in actual)
            latencies.append(float(capture.last.get("latency_ms", 0.0)))
            record.update(
                {
                    "status": "success",
                    "task_exact": exact,
                    "function_name": capture.last.get("function_name"),
                    "schema_valid": capture.last.get("schema_valid", False),
                    "schema_error_validators": capture.last.get(
                        "schema_error_validators", []
                    ),
                    "raw_proposal_count": capture.last.get("raw_proposal_count", 0),
                    "raw_span_total": raw_span_total,
                    "raw_span_exact": raw_span_exact,
                    "actual": actual,
                    "clarification_state": resolution.clarification_state.value,
                    "active_constraints": [
                        {
                            "field": item.field,
                            "operator": item.operator.value,
                            "value": item.normalized_value,
                            "unit": item.unit,
                            "strength": item.hard_or_soft.value,
                            "provenance": item.provenance.value,
                        }
                        for item in resolution.constraint_set.active()
                    ],
                    "provider_calls": resolution.provider_calls,
                    "attempts": capture.last.get("attempts", 0),
                    "input_tokens": resolution.input_tokens,
                    "output_tokens": resolution.output_tokens,
                    "latency_ms": capture.last.get("latency_ms", 0.0),
                    "estimated_cost_cny": round(resolution.estimated_cost_cny, 8),
                }
            )
            records.append(record)
            if ledger.summary()["estimated_cost_cny"] >= manifest["max_cost_cny"]:
                break

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    ordered = sorted(latencies)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] if ordered else 0.0
    summary = ledger.summary()
    result = {
        "schema_version": "proofpick-v2-live-constraint-result-v1",
        "run_type": "first_and_only_frozen_live_holdout",
        "cases_sha256": digest,
        "case_count": len(cases),
        "completed_cases": len(records),
        "model": settings.chat_model,
        "temperature": 0,
        "function_name_expected": "submit_constraint_proposals",
        "function_name_correct": f"{tool_name_success}/{len(records)}",
        "schema_success": f"{schema_success}/{len(records)}",
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "task_exact": f"{task_exact}/{len(cases)}",
        "raw_span_exact": f"{span_exact}/{span_total}",
        "hallucinated_span_accepted": hallucinated_span_accepted,
        "non_domain_field_active": non_domain_active,
        "ambiguous_unconfirmed_checker_ingress": ambiguous_checker_ingress,
        "unsupported_silent_active": unsupported_active,
        "prompt_injection_active_or_privilege_change": prompt_injection_active,
        "average_latency_ms": round(statistics.fmean(latencies), 3) if latencies else 0.0,
        "p95_latency_ms": round(p95, 3),
        "api_calls": summary["call_count"],
        "input_tokens": summary["input_tokens"],
        "output_tokens": summary["output_tokens"],
        "estimated_cost_cny": summary["estimated_cost_cny"],
        "records": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run(args.output))
    public = {key: value for key, value in result.items() if key != "records"}
    print(json.dumps(public, ensure_ascii=False, indent=2))
    return 0 if result["completed_cases"] == result["case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
