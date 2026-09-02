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
            target_regions = {item.product_region for item in records}
            wrong_region = [
                item for item in records if item.source_region != item.product_region
            ]
            values = {_signature(item.normalized_value) for item in records}
            governed_values = {
                _signature(item.normalized_value)
                for item in records
                if item.evidence_scope == "governed"
            }
            open_values = {
                _signature(item.normalized_value)
                for item in records
                if item.evidence_scope == "open"
            }
            conflict_reasons: list[str] = []
            if wrong_region or len(target_regions) > 1:
                conflict_reasons.append("同型号不同地区来源不能静默合并")
            if len(values) > 1:
                conflict_reasons.append("字段存在多个不同正文值或观察值")
            if governed_values and open_values and governed_values != open_values:
                conflict_reasons.append("Open Evidence 与治理证据不一致，不能覆盖 Trusted Evidence")
            if conflict_reasons:
                output.append(
                    OpenFieldAssessment(
                        field_name=field,
                        status=OpenEvidenceStatus.CONFLICT,
                        values=_unique_values(records),
                        reason="；".join(dict.fromkeys(conflict_reasons)) + "。",
                        evidence=records,
                    )
                )
                continue
            usable = [
                item
                for item in records
                if item.source_region == item.product_region
                and item.normalized_value is not None
                and bool(item.exact_snippet.strip())
            ]
            if not usable:
                output.append(
                    OpenFieldAssessment(
                        field_name=field,
                        status=OpenEvidenceStatus.UNKNOWN,
                        values=_unique_values(records),
                        reason="只有错误地区、空值或无正文片段记录，不能标记 matched。",
                        evidence=records,
                    )
                )
                continue
            output.append(
                OpenFieldAssessment(
                    field_name=field,
                    status=OpenEvidenceStatus.MATCHED,
                    values=_unique_values(usable),
                    reason="目标地区官方正文片段支持该字段；证据仍仅限 Open Mode。",
                    evidence=usable,
                )
            )
        return output
