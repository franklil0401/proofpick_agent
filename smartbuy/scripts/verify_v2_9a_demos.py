"""Verify the five V2 portfolio demos without silently calling paid providers."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smartbuy.domain_packs import DomainPackLoader
from smartbuy.memory import DomainPreferenceMemoryStore
from smartbuy.portfolio import load_demo_bundle
from smartbuy.portfolio.dynamic_facts import assess_dynamic_observation


ROOT = Path(__file__).resolve().parents[2]


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _verify_trusted_headphone() -> dict[str, Any]:
    result = _json(ROOT / "smartbuy/eval/results/v2_8_headphone_engineering_regression_after_fix.json")
    row = next(item for item in result["cases"] if item["case_id"] == "headphone-e2e-004")
    report = row["report"]
    assert report["recommended_model_ids"][0] == "sony-wh-1000xm5-black-us"
    assert "steelseries-arctis-nova-pro-wireless-ps-us" in report["eliminated_model_ids"]
    assert report["ranking"]["candidate_contributions"][0]["total_score"] == 0.83751759
    assert report["constraint_verification"]["degraded"] is False
    return {"status": "passed", "source": "saved_redacted_online_regression"}


def _verify_open_research() -> dict[str, Any]:
    result = _json(ROOT / "smartbuy/eval/results/v2_8_headphone_open_research.json")
    assert result["report_status"] == "completed"
    assert result["verified_field_count"] == 5
    assert result["trusted_eligible"] is False
    assert result["entered_constraint_checker"] == 0
    return {"status": "passed", "source": "saved_redacted_live_open_research"}


def _verify_dynamic_fact() -> dict[str, Any]:
    row = next(
        item
        for item in _jsonl(ROOT / "smartbuy/data/processed/price_observations.jsonl")
        if item["observation_id"] == "price-dell-u2724d-20260826"
    )
    result = assess_dynamic_observation(
        row,
        as_of=datetime(2026, 9, 4, 12, tzinfo=UTC),
    )
    assert result.status == "unknown" and result.expired
    assert result.price is None and result.availability is None
    assert not result.eligible_for_trusted_checker and not result.saved_to_long_term_memory
    return {"status": "passed", "source": "governed_append_only_observation"}


def _verify_conflict() -> dict[str, Any]:
    catalog = _jsonl(ROOT / "smartbuy/data/processed/evidence_records.jsonl")
    values = {
        float(item["normalized_value"])
        for item in catalog
        if item["model_id"] == "benq-pd2705u-us"
        and item["normalized_field"] == "usb_c_power_delivery_w"
    }
    assert values == {60.0, 65.0}
    return {"status": "passed", "source": "governed_bilateral_conflict"}


def _verify_memory() -> dict[str, Any]:
    pack = DomainPackLoader().load(ROOT / "smartbuy/domain_packs/laptop")
    with tempfile.TemporaryDirectory(prefix="proofpick-v2-9a-memory-") as root:
        store = DomainPreferenceMemoryStore(Path(root), pack)
        user = "portfolio-demo-browser"
        store.upsert(user, {"min_memory_gb": 32}, explicitly_confirmed=True)
        store.upsert(user, {"min_memory_gb": 64}, explicitly_confirmed=True)
        assert store.recall(user, requested=True)["min_memory_gb"] == 64
        store.upsert(
            user,
            {"ranking_scenario": "portability"},
            explicitly_confirmed=True,
        )
        assert store.recall(user, requested=True)["ranking_scenario"] == "portability"
        store.delete(user, None)
        assert store.recall(user, requested=True) == {}
    return {"status": "passed", "source": "live_local_memory_contract"}


VERIFIERS = {
    "trusted-headphone-filter": _verify_trusted_headphone,
    "open-airpods-max": _verify_open_research,
    "dynamic-price-expired": _verify_dynamic_fact,
    "conflict-fail-closed": _verify_conflict,
    "memory-follow-up": _verify_memory,
}


def run(selected: str | None = None) -> dict[str, Any]:
    bundle = load_demo_bundle()
    identifiers = [selected] if selected else [item.demo_id for item in bundle.demos]
    unknown = sorted(set(identifiers) - set(VERIFIERS))
    if unknown:
        raise ValueError(f"unknown demo: {', '.join(unknown)}")
    results = {identifier: VERIFIERS[identifier]() for identifier in identifiers}
    return {
        "status": "passed",
        "passed": len(results),
        "total": len(results),
        "api_calls": 0,
        "estimated_cost_cny": 0,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", choices=sorted(VERIFIERS))
    parser.add_argument(
        "--mode",
        choices=("local", "replay", "online"),
        default="local",
        help="online is deliberately rejected; use the documented bounded command instead",
    )
    args = parser.parse_args()
    if args.mode == "online":
        raise SystemExit(
            "Online demos are explicit per-provider commands; see smartbuy/docs/v2/v2_demo_guide.md."
        )
    print(json.dumps(run(args.demo), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
