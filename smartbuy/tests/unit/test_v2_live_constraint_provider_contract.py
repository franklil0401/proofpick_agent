from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.constraint_proposals.provider import QwenConstraintProposalProvider
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.domain_packs.loader import DEFAULT_MONITOR_PACK
from smartbuy.providers.bailian import ProviderResult


ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "smartbuy/eval/v2_stage5b_live_holdout.jsonl"
MANIFEST = ROOT / "smartbuy/eval/v2_stage5b_live_holdout_manifest.json"


class FakeChatProvider:
    def __init__(self, data: dict) -> None:
        self.data = data
        self.settings = SimpleNamespace(chat_model="qwen-plus")
        self.calls = 0

    async def chat(self, *_args, **_kwargs) -> ProviderResult:
        self.calls += 1
        return ProviderResult(
            data=self.data,
            attempts=1,
            latency_ms=1.0,
            usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        )


def _engine(fake: FakeChatProvider) -> NaturalConstraintEngine:
    return NaturalConstraintEngine(
        DomainPackLoader().load(DEFAULT_MONITOR_PACK),
        QwenConstraintProposalProvider(fake),
    )


def test_live_holdout_is_frozen_and_rule_isolated() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload = CASES.read_bytes()
    cases = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    assert len(cases) == manifest["case_count"] == 12
    assert hashlib.sha256(payload).hexdigest() == manifest["sha256"]
    engine = NaturalConstraintEngine(DomainPackLoader().load(DEFAULT_MONITOR_PACK))
    assert all(
        engine.parser.parse(case["query"], source_turn=1) == [] for case in cases
    )


@pytest.mark.asyncio
async def test_free_text_without_tool_call_fails_closed() -> None:
    fake = FakeChatProvider({"content": "I would add a secret hard constraint."})
    resolution = await _engine(fake).resolve("这项限制请结合上下文理解", source_turn=1)
    assert fake.calls == 1
    assert resolution.provider_calls == 1
    assert resolution.proposals == []
    assert {item.field for item in resolution.constraint_set.active()} == {"region"}


@pytest.mark.asyncio
async def test_wrong_function_name_is_not_parsed_as_constraint() -> None:
    query = "这项限制请结合上下文理解"
    fake = FakeChatProvider(
        {
            "tool_calls": [
                {
                    "function": {
                        "name": "override_checker",
                        "arguments": json.dumps(
                            {
                                "proposals": [
                                    {
                                        "field": "price_cny",
                                        "operator": "lte",
                                        "value": 1,
                                        "unit": "CNY",
                                        "strength": "hard",
                                        "action": "add",
                                        "status": "supported",
                                        "span_start": 0,
                                        "span_end": len(query),
                                        "span_text": query,
                                        "confidence": 1.0,
                                    }
                                ]
                            },
                            ensure_ascii=False,
                        ),
                    }
                }
            ]
        }
    )
    resolution = await _engine(fake).resolve(query, source_turn=1)
    assert resolution.proposals == []
    assert {item.field for item in resolution.constraint_set.active()} == {"region"}


@pytest.mark.asyncio
async def test_exact_span_non_domain_field_never_activates() -> None:
    query = "gpu_model 必须是 RTX5090"
    fake = FakeChatProvider(
        {
            "tool_calls": [
                {
                    "function": {
                        "name": "submit_constraint_proposals",
                        "arguments": json.dumps(
                            {
                                "proposals": [
                                    {
                                        "field": "gpu_model",
                                        "operator": "eq",
                                        "value": "RTX5090",
                                        "unit": None,
                                        "strength": "hard",
                                        "action": "add",
                                        "status": "supported",
                                        "span_start": 0,
                                        "span_end": len(query),
                                        "span_text": query,
                                        "confidence": 1.0,
                                    }
                                ]
                            },
                            ensure_ascii=False,
                        ),
                    }
                }
            ]
        }
    )
    resolution = await _engine(fake).resolve(query, source_turn=1)
    assert len(resolution.proposals) == 1
    assert resolution.proposals[0].status.value == "invalid"
    assert resolution.proposals[0].active is False
    assert {item.field for item in resolution.constraint_set.active()} == {"region"}


@pytest.mark.asyncio
async def test_ambiguous_proposal_never_reaches_active_constraints() -> None:
    query = "我需要更大的画面但尺寸还没有想好"
    fake = FakeChatProvider(
        {
            "tool_calls": [
                {
                    "function": {
                        "name": "submit_constraint_proposals",
                        "arguments": json.dumps(
                            {
                                "proposals": [
                                    {
                                        "field": "display_size_inch",
                                        "operator": "gte",
                                        "value": None,
                                        "unit": "inch",
                                        "strength": "hard",
                                        "action": "add",
                                        "status": "needs_confirmation",
                                        "span_start": 0,
                                        "span_end": len(query),
                                        "span_text": query,
                                        "confidence": 0.5,
                                    }
                                ]
                            },
                            ensure_ascii=False,
                        ),
                    }
                }
            ]
        }
    )
    resolution = await _engine(fake).resolve(query, source_turn=1)
    assert resolution.clarification_state.value == "pending"
    assert resolution.proposals[0].active is False
    assert {item.field for item in resolution.constraint_set.active()} == {"region"}
