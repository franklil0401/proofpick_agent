"""Release-report convergence and fail-closed presentation tests."""

from smartbuy.agent.reporting import build_report
from smartbuy.constraints import CandidateVerification, VerificationBatch, VerificationStatus
from smartbuy.domain import (
    AgentState,
    ConstraintStatus,
    EvidenceReference,
    FieldAssessment,
    UserRequirements,
)


def _evidence(evidence_id: str, field: str, value, *, model_id="benq-pd2705u-us"):
    return EvidenceReference(
        evidence_id=evidence_id,
        source_id=f"source-{evidence_id}",
        source_url=f"https://example.com/{evidence_id}",
        source_type="official_product",
        model_id=model_id,
        region="US",
        field=field,
        value=value,
    )


def _passed_batch(model_id: str) -> VerificationBatch:
    checked_at = "2026-08-27T00:00:00Z"
    candidate = CandidateVerification(
        model_id=model_id,
        overall_status=VerificationStatus.PASSED,
        eligible=True,
        checked_at=checked_at,
        verifier_version="smartbuy-constraint-checker-v1",
    )
    return VerificationBatch(
        verifier_version="smartbuy-constraint-checker-v1",
        checked_at=checked_at,
        constraint_set_version="smartbuy-constraint-set-v1",
        candidate_pool_model_ids=[model_id],
        candidates=[candidate],
        eligible_model_ids=[model_id],
        semantic_fingerprint="release-report-fixture",
    )


def test_evidence_conflict_cannot_be_overridden_by_passed_checker():
    model_id = "benq-pd2705u-us"
    values = [_evidence("pd-60", "usb_c_power_delivery_w", 60), _evidence("pd-65", "usb_c_power_delivery_w", 65)]
    state = AgentState(
        session_id="release-conflict",
        query="PD2705U 的 USB-C 供电是 60W 还是 65W？",
        requirements=UserRequirements(
            summary="核验 PD2705U USB-C 供电冲突",
            task_type="comparison",
            required_fields=["usb_c_power_delivery_w"],
        ),
        candidate_pool_rows={model_id: {"model_id": model_id, "region": "US"}},
        assessments={
            model_id: [
                FieldAssessment(
                    field="usb_c_power_delivery_w",
                    status=ConstraintStatus.CONFLICT,
                    actual_value=[60, 65],
                    reason="两个官方来源值冲突。",
                    evidence=values,
                )
            ]
        },
        constraint_verification=_passed_batch(model_id),
        ranked_eligible_model_ids=[model_id],
    )

    report = build_report(state, latency_ms=1, usage={})

    assert report.report_version == "smartbuy-decision-v3"
    assert report.recommended_model_ids == []
    assert report.abstained is True
    assert report.candidates[0].overall_status == ConstraintStatus.CONFLICT
    assert report.candidates[0].eligible is False
    assert report.unresolved_facts[0].values == [60, 65]
    markdown = report.to_markdown()
    assert "60" in markdown and "65" in markdown
    assert "source-pd-60" in markdown and "source-pd-65" in markdown


def test_comparison_keeps_evidence_but_does_not_publish_purchase_recommendation():
    model_id = "benq-pd2705u-us"
    evidence = _evidence("comparison-video", "usb_c_video", True)
    state = AgentState(
        session_id="comparison-reference",
        query="比较两个型号的 USB-C 视频能力。",
        requirements=UserRequirements(
            summary="对照 USB-C 视频事实",
            task_type="comparison",
            required_fields=["usb_c_video"],
        ),
        candidate_pool_rows={model_id: {"model_id": model_id, "region": "US"}},
        assessments={
            model_id: [
                FieldAssessment(
                    field="usb_c_video",
                    status=ConstraintStatus.MATCHED,
                    actual_value=True,
                    reason="官方证据支持。",
                    evidence=[evidence],
                )
            ]
        },
        constraint_verification=_passed_batch(model_id),
        ranked_eligible_model_ids=[model_id],
    )

    report = build_report(state, latency_ms=1, usage={})

    assert report.recommended_model_ids == []
    assert {(item.model_id, item.field) for item in report.evidence} == {
        (model_id, "usb_c_video")
    }


def test_missing_required_fields_are_explicit_unknowns():
    state = AgentState(
        session_id="release-missing",
        query="当前价格和库存是多少？",
        requirements=UserRequirements(
            summary="核验动态价格和库存",
            task_type="dynamic",
            required_fields=["price_cny", "stock_status"],
        ),
        constraint_verification=VerificationBatch(
            verifier_version="smartbuy-constraint-checker-v1",
            checked_at="2026-08-27T00:00:00Z",
            constraint_set_version="smartbuy-constraint-set-v1",
            semantic_fingerprint="empty-release-fixture",
        ),
    )

    report = build_report(state, latency_ms=1, usage={})

    assert report.abstained is True
    assert {item.field for item in report.unresolved_facts} == {"price_cny", "stock_status"}
    assert all(item.status == "unknown" for item in report.unresolved_facts)
    assert "可能支持" not in report.to_markdown()


def test_report_evidence_is_limited_to_requested_fields_and_models():
    model_id = "benq-pd2705u-us"
    relevant = _evidence("video", "usb_c_video", True, model_id=model_id)
    unrelated_field = _evidence("width", "width_mm", 614, model_id=model_id)
    unrelated_model = _evidence("other", "usb_c_video", True, model_id="other-model")
    state = AgentState(
        session_id="release-evidence",
        query="是否支持 USB-C 视频？",
        requirements=UserRequirements(
            summary="核验 USB-C 视频",
            task_type="fact",
            required_fields=["usb_c_video"],
        ),
        assessments={
            model_id: [
                FieldAssessment(
                    field="usb_c_video",
                    status=ConstraintStatus.MATCHED,
                    actual_value=True,
                    reason="官方证据支持。",
                    evidence=[relevant],
                )
            ]
        },
        kb_hits=[relevant, unrelated_field, unrelated_model],
    )

    report = build_report(state, latency_ms=1, usage={})

    assert [item.evidence_id for item in report.evidence] == ["video"]


def test_filter_report_does_not_surface_planner_only_marketing_fields():
    state = AgentState(
        session_id="release-convergence",
        query="找 27 英寸 4K、不要 OLED 的显示器。",
        requirements=UserRequirements(
            summary="筛选 27 英寸 4K 非 OLED 显示器",
            task_type="filter",
            required_fields=[
                "display_size_inch",
                "resolution",
                "is_oled",
                "panel_type",
                "warranty",
                "model_name",
            ],
        ),
    )

    report = build_report(state, latency_ms=1, usage={})

    unresolved = {item.field for item in report.unresolved_facts}
    assert unresolved == {"display_size_inch", "resolution", "is_oled"}
