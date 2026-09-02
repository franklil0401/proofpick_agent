"""V2-5 frozen expression evaluation and proposal safety tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from smartbuy.constraint_proposals.engine import (
    ConstraintProposalValidator,
    NaturalConstraintEngine,
)
from smartbuy.constraint_proposals.models import (
    ClarificationState,
    ProposalSource,
    ProposalStatus,
)
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


ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "smartbuy/eval/v2_stage5_expression_cases.jsonl"
MANIFEST = ROOT / "smartbuy/eval/v2_stage5_expression_manifest.json"
FROZEN_SHA256 = "9c03937ba7897b9e390f2e73099d394f331bfd696ea763cfc1c3b4b27741eb75"


def _pack():
    return DomainPackLoader().load(DEFAULT_MONITOR_PACK)


def _previous(items: list[dict]) -> ConstraintSet | None:
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
                provenance=ConstraintProvenance.SESSION_CONFIRMED,
                source_text="frozen fixture",
                source_turn=1,
                confidence=1.0,
                supported=True,
                active=True,
            )
            for item in items
        ]
    )


def _public_proposal(item) -> dict:
    return {
        "field": item.field,
        "operator": item.operator.value if item.operator else "eq",
        "value": item.normalized_value,
        "unit": item.unit,
        "strength": item.strength.value,
        "status": item.status.value,
        "action": item.action.value,
    }


def _signature(item: dict) -> str:
    return json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_expression_dataset_is_frozen_before_tuning():
    payload = CASES.read_bytes()
    cases = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert hashlib.sha256(payload).hexdigest() == FROZEN_SHA256
    assert len(cases) == manifest["case_count"] == 50
    assert sum(case["split"] == "regression" for case in cases) == 30
    assert sum(case["split"] == "holdout" for case in cases) == 20
    assert len({case["case_id"] for case in cases}) == 50


@pytest.mark.asyncio
async def test_frozen_fifty_cases_exceed_field_f1_gate_and_report_task_exactness():
    engine = NaturalConstraintEngine(_pack())
    tp = fp = fn = exact = 0
    for line in CASES.read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        resolution = await engine.resolve(
            case["query"],
            source_turn=2 if case.get("previous") else 1,
            previous=_previous(case.get("previous", [])),
        )
        expected = {_signature(item) for item in case["expected"]}
        actual = {_signature(_public_proposal(item)) for item in resolution.proposals}
        tp += len(expected & actual)
        fp += len(actual - expected)
        fn += len(expected - actual)
        exact += expected == actual
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    f1 = 2 * precision * recall / (precision + recall)
    assert (tp, fp, fn) == (55, 0, 0)
    assert precision == recall == f1 == 1.0
    assert exact == 50


def test_llm_hallucinated_span_and_non_domain_field_never_activate():
    validator = ConstraintProposalValidator(_pack())
    invalid_span = validator.validate(
        "预算三千元",
        {
            "field": "price_cny",
            "operator": "lte",
            "value": 3000,
            "unit": "CNY",
            "strength": "hard",
            "status": "supported",
            "action": "add",
            "span_start": 0,
            "span_end": 2,
            "span_text": "四千",
            "confidence": 1,
        },
        source=ProposalSource.LLM,
        source_turn=1,
    )
    query = "必须带摄像头"
    unsupported = validator.validate(
        query,
        {
            "field": "camera",
            "operator": "eq",
            "value": True,
            "unit": None,
            "strength": "hard",
            "status": "supported",
            "action": "add",
            "span_start": 2,
            "span_end": len(query),
            "span_text": query[2:],
            "confidence": 1,
        },
        source=ProposalSource.LLM,
        source_turn=1,
    )
    assert invalid_span.status == ProposalStatus.INVALID and not invalid_span.active
    assert unsupported.status == ProposalStatus.INVALID and not unsupported.active


@pytest.mark.asyncio
async def test_ambiguous_and_unsupported_never_enter_effective_checker_constraints():
    engine = NaturalConstraintEngine(_pack())
    ambiguous = await engine.resolve("屏幕不要太大", source_turn=1)
    unsupported = await engine.resolve("必须带摄像头", source_turn=1)
    assert ambiguous.clarification_state == ClarificationState.PENDING
    assert not any(item.field == "display_size_inch" for item in ambiguous.constraint_set.active())
    assert not any(item.field == "camera" for item in unsupported.constraint_set.active())


@pytest.mark.asyncio
async def test_current_input_overrides_long_term_preference_and_cancel_is_explicit():
    engine = NaturalConstraintEngine(_pack())
    current = await engine.resolve(
        "预算 3500 元",
        source_turn=1,
        preferences={"price_cny": 3000},
    )
    active = [item for item in current.constraint_set.active() if item.field == "price_cny"]
    assert len(active) == 1
    assert active[0].normalized_value == 3500
    assert active[0].provenance == ConstraintProvenance.CURRENT_INPUT
    cancelled = await engine.resolve(
        "取消预算限制",
        source_turn=2,
        previous=current.constraint_set,
        preferences={"price_cny": 3000},
    )
    assert "price_cny" in cancelled.constraint_set.cancelled_fields
    assert not any(item.field == "price_cny" for item in cancelled.constraint_set.active())


@pytest.mark.asyncio
async def test_rule_gap_uses_one_schema_provider_call_then_deterministic_validation():
    query = "必须要可调支架"

    class FakeProposalProvider:
        calls = 0

        async def propose(self, received_query, _pack):
            self.calls += 1
            assert received_query == query
            return {
                "proposals": [
                    {
                        "field": "stand_adjustment",
                        "operator": "contains_all",
                        "value": ["高度"],
                        "unit": None,
                        "strength": "hard",
                        "action": "add",
                        "status": "supported",
                        "span_start": 0,
                        "span_end": len(query),
                        "span_text": query,
                        "confidence": 0.9,
                    }
                ],
                "input_tokens": 12,
                "output_tokens": 8,
                "latency_ms": 10,
                "estimated_cost_cny": 0.001,
            }

    provider = FakeProposalProvider()
    resolution = await NaturalConstraintEngine(_pack(), provider).resolve(query, source_turn=1)
    assert provider.calls == resolution.provider_calls == 1
    assert resolution.proposals[0].source == ProposalSource.LLM
    assert resolution.proposals[0].active is True
    assert any(
        item.field == "stand_adjustment" for item in resolution.constraint_set.active()
    )


@pytest.mark.asyncio
async def test_qwen_fallback_forces_schema_function_call_at_temperature_zero():
    query = "必须要可调支架"

    class FakeBailian:
        settings = SimpleNamespace(chat_model="qwen-plus")
        captured = None

        async def chat(self, messages, **kwargs):
            self.captured = {"messages": messages, **kwargs}
            return SimpleNamespace(
                data={
                    "tool_calls": [
                        {
                            "function": {
                                "name": "submit_constraint_proposals",
                                "arguments": json.dumps(
                                    {
                                        "proposals": [
                                            {
                                                "field": "stand_adjustment",
                                                "operator": "contains_all",
                                                "value": ["高度"],
                                                "unit": None,
                                                "strength": "hard",
                                                "action": "add",
                                                "status": "supported",
                                                "span_start": 0,
                                                "span_end": len(query),
                                                "span_text": query,
                                                "confidence": 0.9,
                                            }
                                        ]
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                },
                usage={"input_tokens": 20, "output_tokens": 10},
                latency_ms=12.5,
            )

    fake = FakeBailian()
    result = await QwenConstraintProposalProvider(fake).propose(query, _pack())
    assert len(result["proposals"]) == 1
    assert fake.captured["temperature"] == 0.0
    assert fake.captured["tool_choice"]["function"]["name"] == "submit_constraint_proposals"
    assert fake.captured["tools"][0]["function"]["parameters"]["additionalProperties"] is False
