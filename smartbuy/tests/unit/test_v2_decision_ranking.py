from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from smartbuy.domain_packs import DomainPackRegistry
from smartbuy.ranking import (
    DeterministicDecisionRanker,
    RankingCandidateInput,
    RankingEvidence,
    RankingInvariantError,
    RankingProfile,
    RankingProfileLoader,
    RankingRequest,
)


ROOT = Path(__file__).resolve().parents[3]
REGISTRY = DomainPackRegistry(ROOT / "smartbuy" / "domain_packs")


def _candidate(
    product_id: str,
    region: str,
    values: dict[str, object],
    *,
    source_type: str = "official_product",
) -> RankingCandidateInput:
    return RankingCandidateInput(
        product_id=product_id,
        configuration_id=product_id.upper(),
        region=region,
        values=values,
        evidence=[
            RankingEvidence(
                evidence_id=f"ev-{product_id}-{field}",
                source_id=f"src-{product_id}",
                source_type=source_type,
                field_id=field,
                normalized_value=value,
                region=region,
            )
            for field, value in values.items()
            if value is not None
        ],
    )


MONITORS = [
    _candidate("monitor-a", "CN", {
        "resolution": "3840x2160", "has_usb_c": True, "usb_c_video": True,
        "refresh_rate_hz": 60, "is_oled": False, "panel_type": "IPS",
        "display_size_inch": 27, "usb_c_power_delivery_w": 96,
        "width_mm": 612, "weight_kg": 5.8,
    }),
    _candidate("monitor-b", "CN", {
        "resolution": "2560x1440", "has_usb_c": False, "usb_c_video": False,
        "refresh_rate_hz": 240, "is_oled": True, "panel_type": "OLED",
        "display_size_inch": 26.5, "usb_c_power_delivery_w": None,
        "width_mm": 604, "weight_kg": 6.9,
    }),
    _candidate("monitor-c", "CN", {
        "resolution": "5120x2880", "has_usb_c": True, "usb_c_video": True,
        "refresh_rate_hz": 60, "is_oled": False, "panel_type": "IPS",
        "display_size_inch": 27, "usb_c_power_delivery_w": 90,
        "width_mm": 620, "weight_kg": 5.9,
    }),
]

LAPTOPS = [
    _candidate("laptop-a", "CN", {
        "memory_gb": 64, "storage_gb": 4096, "battery_wh": 90,
        "weight_kg": 1.95, "gpu_vram_gb": 24, "refresh_rate_hz": 60,
        "resolution": "3840x2400", "height_mm": 18.3,
    }),
    _candidate("laptop-b", "CN", {
        "memory_gb": 32, "storage_gb": 1024, "battery_wh": 56,
        "weight_kg": 1.2, "gpu_vram_gb": None, "refresh_rate_hz": 120,
        "resolution": "2880x1800", "height_mm": 14,
    }),
    _candidate("laptop-c", "CN", {
        "memory_gb": 16, "storage_gb": 512, "battery_wh": 90,
        "weight_kg": 1.0, "gpu_vram_gb": 8, "refresh_rate_hz": 240,
        "resolution": "2560x1600", "height_mm": 13,
    }),
]


def _request(
    domain_id: str,
    candidates: list[RankingCandidateInput],
    *,
    scenario: str | None = None,
    weights: dict[str, float] | None = None,
    explicit: dict[str, object] | None = None,
    memory: dict[str, object] | None = None,
    memory_enabled: bool = False,
) -> tuple[DeterministicDecisionRanker, RankingRequest]:
    pack = REGISTRY.load(domain_id)
    profile = RankingProfileLoader.load(pack)
    request = RankingRequest(
        domain_id=domain_id,
        scenario=scenario,
        eligible_candidates=candidates,
        checker_eligible_ids=[item.product_id for item in candidates],
        explicit_preferences=explicit or {},
        confirmed_memory_preferences=memory or {},
        weight_overrides=weights or {},
        ranking_profile_version=profile.profile.profile_version,
        data_version=f"{domain_id}-fixture-v1",
        domain_pack_version=pack.version,
        memory_enabled=memory_enabled,
        what_if=True,
    )
    return DeterministicDecisionRanker(profile), request


def test_pack_profiles_declare_required_monitor_and_laptop_scenarios() -> None:
    monitor = RankingProfileLoader.load(REGISTRY.load("monitor"))
    laptop = RankingProfileLoader.load(REGISTRY.load("laptop"))
    assert set(monitor.scenarios) == {
        "office_text", "gaming", "creative_color", "laptop_docking", "desk_fit"
    }
    assert set(laptop.scenarios) == {
        "office", "software_development", "creative_work", "gaming", "portability"
    }
    assert all(
        abs(sum(item.weight for item in scenario.dimensions) - 1.0) < 1e-9
        for profile in (monitor, laptop)
        for scenario in profile.scenarios.values()
    )


def test_profile_schema_rejects_bad_weights_ranges_and_fields() -> None:
    raw = REGISTRY.load("monitor").pack.policies["ranking"]["profile"]
    broken = json.loads(json.dumps(raw))
    broken["scenarios"][0]["dimensions"][0]["weight"] = -1
    with pytest.raises(ValidationError):
        RankingProfile.model_validate(broken)
    broken = json.loads(json.dumps(raw))
    broken["scenarios"][0]["dimensions"][0]["fixed_range"] = [10, 1]
    broken["scenarios"][0]["dimensions"][0]["normalization"] = "fixed_range"
    broken["scenarios"][0]["dimensions"][0].pop("enum_scores")
    with pytest.raises(ValidationError):
        RankingProfile.model_validate(broken)


@pytest.mark.parametrize(
    ("domain_id", "candidates", "scenario", "weights", "memory_enabled"),
    [
        ("monitor", MONITORS, "office_text", None, False),
        ("monitor", MONITORS, "gaming", None, False),
        ("monitor", MONITORS, "creative_color", {"creative_resolution": 0.8}, False),
        ("monitor", MONITORS, "laptop_docking", {"dock_power": 0.75}, False),
        ("monitor", MONITORS, "desk_fit", {"desk_width": 0.9}, False),
        ("monitor", MONITORS, None, None, True),
        ("laptop", LAPTOPS, "office", None, False),
        ("laptop", LAPTOPS, "software_development", {"dev_memory": 0.75}, False),
        ("laptop", LAPTOPS, "creative_work", None, False),
        ("laptop", LAPTOPS, "gaming", {"gaming_refresh": 0.75}, False),
        ("laptop", LAPTOPS, "portability", {"portable_weight": 0.8}, False),
        ("laptop", LAPTOPS, None, None, True),
    ],
)
def test_twelve_what_if_cases_keep_set_and_explain_every_rank(
    domain_id: str,
    candidates: list[RankingCandidateInput],
    scenario: str | None,
    weights: dict[str, float] | None,
    memory_enabled: bool,
) -> None:
    memory = {"ranking_scenario": "gaming"} if memory_enabled else {}
    ranker, request = _request(
        domain_id,
        candidates,
        scenario=scenario,
        weights=weights,
        explicit={"ranking_scenario": scenario} if scenario else {},
        memory=memory,
        memory_enabled=memory_enabled,
    )
    result = ranker.rank(request)
    assert set(result.ranked_ids) == set(request.checker_eligible_ids)
    assert len(result.candidate_contributions) == len(candidates)
    assert all(item.advantages or item.tradeoffs for item in result.candidate_contributions)
    assert all(
        dimension.evidence_ids
        for item in result.candidate_contributions
        for dimension in item.dimension_scores
        if dimension.status == "scored"
    )


def test_unknown_has_no_reward_or_false_negative_and_evidence_coverage_is_traceable() -> None:
    ranker, request = _request("laptop", LAPTOPS, scenario="gaming")
    result = ranker.rank(request)
    unknown = next(item for item in result.candidate_contributions if item.product_id == "laptop-b")
    vram = next(item for item in unknown.dimension_scores if item.dimension_id == "gaming_vram")
    assert vram.status == "unknown"
    assert vram.actual_value is None and vram.contribution == 0
    assert "不推断负面事实" in vram.reason
    assert result.candidate_contributions[0].evidence_coverage >= 0.95


def test_ranker_is_byte_deterministic_and_uses_stable_tie_breaker() -> None:
    ties = [
        _candidate("z-product", "CN", {"memory_gb": None}),
        _candidate("a-product", "CN", {"memory_gb": None}),
    ]
    ranker, request = _request("laptop", ties, scenario="office")
    first = ranker.fallback(request, "fixture")
    second = ranker.fallback(request, "fixture")
    assert first.ranked_ids == ["a-product", "z-product"]
    assert ranker.canonical_bytes(first) == ranker.canonical_bytes(second)


def test_invalid_weight_fails_explicitly_and_fallback_cannot_expand_checker_set() -> None:
    ranker, request = _request(
        "monitor", MONITORS, scenario="gaming", weights={"unknown_dimension": 0.5}
    )
    with pytest.raises(RankingInvariantError):
        ranker.rank(request)
    fallback = ranker.fallback(request, "RankingInvariantError")
    assert set(fallback.ranked_ids) == set(request.checker_eligible_ids)
    assert fallback.ranking_degraded is True
    with pytest.raises(ValidationError, match="Checker"):
        RankingRequest.model_validate(
            {
                **request.model_dump(mode="json"),
                "checker_eligible_ids": request.checker_eligible_ids[:-1],
            }
        )


def test_generic_ranker_contains_no_domain_business_field_constants() -> None:
    text = (ROOT / "smartbuy" / "ranking" / "ranker.py").read_text(encoding="utf-8")
    for forbidden in (
        "refresh_rate_hz", "is_oled", "cpu_model", "gpu_model", "memory_gb",
        "weight_kg", "battery_wh",
    ):
        assert forbidden not in text
