"""Scope-preserving field checks for governed and temporary web evidence."""

from __future__ import annotations

import json
from typing import Any

from smartbuy.open_research.models import (
    OpenEvidenceRecord,
    OpenEvidenceStatus,
    OpenFieldAssessment,
    ScopedEvidenceValue,
)


def _signature(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _unique_values(records: list[ScopedEvidenceValue]) -> list[Any]:
    values: list[Any] = []
    seen: set[str] = set()
    for item in records:
        signature = _signature(item.normalized_value)
        if signature not in seen:
            seen.add(signature)
            values.append(item.normalized_value)
    return values


def _from_open(record: OpenEvidenceRecord) -> ScopedEvidenceValue:
    return ScopedEvidenceValue(
        evidence_id=record.evidence_id,
        field_name=record.field_name,
        normalized_value=record.normalized_value,
        unit=record.unit,
        source_url=record.final_url,
        source_region=record.source_region,
        product_region=record.product_region,
        observed_at=record.observed_at,
        exact_snippet=record.exact_snippet,
        evidence_scope="open",
    )


class OpenEvidenceChecker:
    """Determine four-state field coverage without granting Trusted eligibility."""

    def assess(
        self,
        required_fields: list[str],
        open_records: list[OpenEvidenceRecord],
        *,
        governed_records: list[ScopedEvidenceValue] | None = None,
    ) -> list[OpenFieldAssessment]:
        scoped = [*(governed_records or []), *[_from_open(item) for item in open_records]]
        output: list[OpenFieldAssessment] = []
        for field in list(dict.fromkeys(required_fields)):
            records = [item for item in scoped if item.field_name == field]
            if not records:
                output.append(
                    OpenFieldAssessment(
                        field_name=field,
                        status=OpenEvidenceStatus.UNKNOWN,
                        reason="没有正文片段支持该字段；搜索摘要不能替代证据。",
                    )
                )
                continue
            target_regions = list(dict.fromkeys(item.product_region for item in records))
            if len(target_regions) != 1:
                output.append(
                    OpenFieldAssessment(
                        field_name=field,
                        status=OpenEvidenceStatus.CONFLICT,
                        values=_unique_values(records),
                        reason="target_region_scope_conflict",
                        evidence=records,
                        target_region_status=OpenEvidenceStatus.CONFLICT,
                        conflict_evidence_ids=[item.evidence_id for item in records],
                    )
                )
                continue
            target_region = target_regions[0]
            target_records = [
                item
                for item in records
                if item.source_region == target_region
            ]
            non_target_records = [
                item for item in records if item.source_region != target_region
            ]
            target_ids = [item.evidence_id for item in target_records]
            non_target_ids = [item.evidence_id for item in non_target_records]
            if not target_records:
                output.append(
                    OpenFieldAssessment(
                        field_name=field,
                        status=OpenEvidenceStatus.UNKNOWN,
                        reason="region_mismatch_only",
                        target_region=target_region,
                        target_region_evidence_ids=[],
                        non_target_region_evidence_ids=non_target_ids,
                        target_region_status=OpenEvidenceStatus.UNKNOWN,
                        cross_region_conflict=False,
                        non_comparable_evidence=non_target_records,
                    )
                )
                continue

            usable_target = [
                item
                for item in target_records
                if item.normalized_value is not None and bool(item.exact_snippet.strip())
            ]
            if not usable_target:
                output.append(
                    OpenFieldAssessment(
                        field_name=field,
                        status=OpenEvidenceStatus.UNKNOWN,
                        reason="target_region_evidence_incomplete",
                        evidence=target_records,
                        target_region=target_region,
                        target_region_evidence_ids=target_ids,
                        non_target_region_evidence_ids=non_target_ids,
                        target_region_status=OpenEvidenceStatus.UNKNOWN,
                        cross_region_conflict=False,
                        non_comparable_evidence=non_target_records,
                    )
                )
                continue

            target_values = {_signature(item.normalized_value) for item in usable_target}
            target_conflict = len(target_values) > 1
            target_status = (
                OpenEvidenceStatus.CONFLICT
                if target_conflict
                else OpenEvidenceStatus.MATCHED
            )
            comparable_non_target = [
                item
                for item in non_target_records
                if item.normalized_value is not None and bool(item.exact_snippet.strip())
            ]
            differing_non_target = [
                item
                for item in comparable_non_target
                if _signature(item.normalized_value) not in target_values
            ]
            cross_region_conflict = bool(differing_non_target)
            if target_conflict or cross_region_conflict:
                conflict_records = [
                    *usable_target,
                    *(differing_non_target if cross_region_conflict else []),
                ]
                reason = (
                    "target_and_cross_region_value_conflict"
                    if target_conflict and cross_region_conflict
                    else (
                        "cross_region_value_conflict"
                        if cross_region_conflict
                        else "target_region_value_conflict"
                    )
                )
                output.append(
                    OpenFieldAssessment(
                        field_name=field,
                        status=OpenEvidenceStatus.CONFLICT,
                        values=_unique_values(conflict_records),
                        reason=reason,
                        evidence=conflict_records,
                        target_region=target_region,
                        target_region_evidence_ids=target_ids,
                        non_target_region_evidence_ids=non_target_ids,
                        target_region_status=target_status,
                        cross_region_conflict=cross_region_conflict,
                        conflict_evidence_ids=[
                            item.evidence_id for item in conflict_records
                        ],
                        non_comparable_evidence=non_target_records,
                    )
                )
                continue
            output.append(
                OpenFieldAssessment(
                    field_name=field,
                    status=OpenEvidenceStatus.MATCHED,
                    values=_unique_values(usable_target),
                    reason="target_region_evidence_matched",
                    evidence=usable_target,
                    target_region=target_region,
                    target_region_evidence_ids=target_ids,
                    non_target_region_evidence_ids=non_target_ids,
                    target_region_status=OpenEvidenceStatus.MATCHED,
                    cross_region_conflict=False,
                    non_comparable_evidence=non_target_records,
                )
            )
        return output
