"""V2-1D V1 request/response compatibility and default-off rollback tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from smartbuy.api.router import (
    get_smartbuy_orchestrator,
    set_smartbuy_agent,
    set_smartbuy_orchestrator,
)
from smartbuy.constraints import (
    CandidateConstraintVerifier,
    CandidateVerification,
    ConstraintNormalizer,
    VerificationBatch,
    VerificationStatus,
)
from smartbuy.contracts import FieldState
from smartbuy.db.build_database import build_database
from smartbuy.domain import CandidateDecision, ConstraintStatus, DecisionReport
from smartbuy.domain_packs import DEFAULT_MONITOR_PACK, DomainPackLoader
from smartbuy.domain_packs.orchestrator import DomainPackOrchestrator
from smartbuy.domain_packs.v1_adapter import V1CompatibilityAdapter
from smartbuy.memory import LongTermPreferenceStore
from smartbuy.orchestration import OrchestratorKind, OrchestratorRequest, ReactOrchestrator


ROOT = Path(__file__).resolve().parents[3]


class OfflineAgent:
    def __init__(self, tmp_path: Path, report: DecisionReport):
        self.preference_memory = LongTermPreferenceStore(tmp_path / "preferences.json")
        self.report = report
        self.calls = 0

    async def run(self, query, **_kwargs):
        self.calls += 1
        return self.report.model_copy(deep=True, update={"request_summary": query})


def _report_from_frozen_case(case: dict) -> DecisionReport:
    checked_at = "2026-08-31T00:00:00Z"
    eligible = set(case["eligible_model_ids"])
    candidates = [
        CandidateVerification(
            model_id=model_id,
            overall_status=(
                VerificationStatus.PASSED if model_id in eligible else VerificationStatus.FAILED
            ),
            eligible=model_id in eligible,
            violated_fields=[] if model_id in eligible else ["frozen_fixture_outcome"],
            checked_at=checked_at,
            verifier_version="smartbuy-constraint-checker-v1",
        )
        for model_id in case["candidate_pool_model_ids"]
    ]
    batch = VerificationBatch(
        verifier_version="smartbuy-constraint-checker-v1",
        checked_at=checked_at,
        constraint_set_version="smartbuy-constraint-set-v1",
        candidate_pool_model_ids=case["candidate_pool_model_ids"],
        candidates=candidates,
        eligible_model_ids=case["eligible_model_ids"],
        rejected_model_ids=[item.model_id for item in candidates if not item.eligible],
        semantic_fingerprint=f"frozen-{case['case_id']}",
    )
    return DecisionReport(
        request_summary=case["case_id"],
        constraint_verification=batch,
        candidates=[
            CandidateDecision(
                model_id=item.model_id,
                overall_status=(
                    ConstraintStatus.MATCHED if item.eligible else ConstraintStatus.NOT_MATCHED
                ),
                eligible=item.eligible,
                verifier_status=item.overall_status,
                verifier_version=item.verifier_version,
            )
            for item in candidates
        ],
        recommended_model_ids=case["eligible_model_ids"],
        abstained=not bool(case["eligible_model_ids"]),
        stop_reason="冻结回归夹具；未调用模型。",
    )


@pytest.mark.parametrize(
    "case",
    json.loads(
        (ROOT / "smartbuy/data/processed/stage6_stage4_regression_results.json").read_text(
            encoding="utf-8"
        )
    )["cases"],
    ids=lambda case: case["case_id"],
)
def test_sixteen_frozen_v1_results_round_trip_exactly(case):
    assert case["end_to_end_pass"] is True
    adapter = V1CompatibilityAdapter(DomainPackLoader().load(DEFAULT_MONITOR_PACK))
    original = _report_from_frozen_case(case)
    mapped = adapter.from_v1_report(original)
    restored = adapter.to_v1_report(mapped, original)
    assert restored.model_dump(mode="json") == original.model_dump(mode="json")
    assert mapped.recommended_product_ids == case["eligible_model_ids"]


def test_generic_mapping_preserves_real_v1_checker_results_for_complete_catalog(tmp_path):
    database = tmp_path / "catalog.sqlite"
    build_database(database)
    adapter = V1CompatibilityAdapter(DomainPackLoader().load(DEFAULT_MONITOR_PACK))
    constraints = ConstraintNormalizer().build(
        "中国版、非 OLED、至少 4K 且需要 USB-C 视频输入",
        source_turn=1,
    )
    pool = [row["model_id"] for row in adapter.catalog.products]
    verification = CandidateConstraintVerifier(
        database,
        as_of=datetime(2026, 8, 27, tzinfo=UTC),
    ).verify_candidates(constraints, pool)
    report = DecisionReport(
        request_summary="真实 V1 Checker 映射",
        constraint_set=constraints,
        constraint_verification=verification,
        recommended_model_ids=verification.eligible_model_ids,
        abstained=not bool(verification.eligible_model_ids),
        stop_reason="本地确定性检查。",
    )
    mapped = adapter.from_v1_report(report)
    assert [item.product_id for item in mapped.candidates] == [
        item.model_id for item in verification.candidates
    ]
    assert [item.eligible for item in mapped.candidates] == [
        item.eligible for item in verification.candidates
    ]
    assert adapter.to_v1_report(mapped, report) == report


def test_generic_result_cannot_override_v1_checker_eligibility():
    case = json.loads(
        (ROOT / "smartbuy/data/processed/stage6_stage4_regression_results.json").read_text(
            encoding="utf-8"
        )
    )["cases"][2]
    adapter = V1CompatibilityAdapter(DomainPackLoader().load(DEFAULT_MONITOR_PACK))
    report = _report_from_frozen_case(case)
    mapped = adapter.from_v1_report(report)
    original = mapped.candidates[0]
    tampered = original.model_copy(
        update={"eligible": not original.eligible, "overall_state": FieldState.MATCHED}
    )
    changed = mapped.model_copy(update={"candidates": [tampered, *mapped.candidates[1:]]})
    with pytest.raises(RuntimeError, match="differs from V1 Checker"):
        adapter.to_v1_report(changed, report)


@pytest.mark.asyncio
async def test_domain_pack_path_is_explicit_and_preserves_v1_response(tmp_path):
    frozen = json.loads(
        (ROOT / "smartbuy/data/processed/stage6_stage4_regression_results.json").read_text(
            encoding="utf-8"
        )
    )["cases"][1]
    report = _report_from_frozen_case(frozen)
    agent = OfflineAgent(tmp_path, report)
    wrapped = DomainPackOrchestrator(
        ReactOrchestrator(agent),
        DomainPackLoader().load(DEFAULT_MONITOR_PACK),
    )
    events = []
    result = await wrapped.run(
        OrchestratorRequest(query="V1 兼容映射", session_id="compat"),
        event_callback=events.append,
    )
    assert result.orchestrator == OrchestratorKind.REACT
    assert result.report.model_dump(mode="json") == report.model_copy(
        update={"request_summary": "V1 兼容映射"}
    ).model_dump(mode="json")
    assert [event["type"] for event in events if event["type"].startswith("domain_pack_")] == [
        "domain_pack_selected", "domain_pack_completed"
    ]
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_feature_flag_off_restores_unwrapped_v1_without_migration(tmp_path, monkeypatch):
    case = json.loads(
        (ROOT / "smartbuy/data/processed/stage6_stage4_regression_results.json").read_text(
            encoding="utf-8"
        )
    )["cases"][0]
    agent = OfflineAgent(tmp_path, _report_from_frozen_case(case))
    monkeypatch.setenv("PROOFPICK_DOMAIN_PACK_ENABLED", "false")
    monkeypatch.setenv("PROOFPICK_ORCHESTRATOR", "react")
    set_smartbuy_agent(agent)
    try:
        orchestrator = get_smartbuy_orchestrator()
        assert not isinstance(orchestrator, DomainPackOrchestrator)
        result = await orchestrator.run(OrchestratorRequest(query="完整回滚"))
        assert result.report.recommended_model_ids == case["eligible_model_ids"]
        assert agent.calls == 1
    finally:
        set_smartbuy_orchestrator(None)
        set_smartbuy_agent(None)


def test_enabled_missing_pack_fails_before_agent_execution(tmp_path, monkeypatch):
    case = json.loads(
        (ROOT / "smartbuy/data/processed/stage6_stage4_regression_results.json").read_text(
            encoding="utf-8"
        )
    )["cases"][0]
    agent = OfflineAgent(tmp_path, _report_from_frozen_case(case))
    monkeypatch.setenv("PROOFPICK_DOMAIN_PACK_ENABLED", "true")
    monkeypatch.setenv("PROOFPICK_DOMAIN_PACK_PATH", str(tmp_path / "missing-pack"))
    set_smartbuy_agent(agent)
    try:
        with pytest.raises(RuntimeError, match="directory is missing"):
            get_smartbuy_orchestrator()
        assert agent.calls == 0
    finally:
        set_smartbuy_orchestrator(None)
        set_smartbuy_agent(None)
