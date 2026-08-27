"""Field-level evidence sufficiency checks independent of retrieval scores."""

from __future__ import annotations

import sqlite3
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smartbuy.constraints.normalize import normalize_resolution
from smartbuy.domain import ConstraintOperator, ConstraintSpec, ConstraintStatus, EvidenceReference, FieldAssessment
from smartbuy.tools.base import ToolResult


PRODUCT_FIELDS = {
    "model_id", "brand", "model_name", "region", "display_size_inch", "resolution", "refresh_rate_hz", "panel_type",
    "is_oled", "has_usb_c", "usb_c_video", "usb_c_power_delivery_w", "stand_adjustment", "width_mm",
    "weight_kg", "warranty", "release_date",
}
PRICE_FIELDS = {"price_cny", "stock_status", "observed_at"}
EVIDENCE_ONLY_FIELDS = {
    "camera", "face_recognition", "ten_year_burn_in_guarantee", "interface_marketing",
    "source_type", "confidence_level", "conflict_group", "source_id",
}
CHECKABLE_FIELDS = PRODUCT_FIELDS | PRICE_FIELDS | EVIDENCE_ONLY_FIELDS


def _coerce(value: Any, expected: Any) -> Any:
    if expected is None:
        return value
    if isinstance(expected, bool):
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes"}
        return bool(value)
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return value


def _matches(actual: Any, constraint: ConstraintSpec | None) -> bool:
    if constraint is None:
        return True
    expected = constraint.value
    if constraint.field == "resolution":
        actual_resolution = normalize_resolution(actual)
        expected_resolution = normalize_resolution(expected)
        if constraint.operator == ConstraintOperator.EQ:
            return actual_resolution == expected_resolution
        if constraint.operator == ConstraintOperator.GTE:
            actual_match = re.fullmatch(r"(\d{3,5})x(\d{3,5})", actual_resolution)
            expected_match = re.fullmatch(r"(\d{3,5})x(\d{3,5})", expected_resolution)
            if actual_match is None or expected_match is None:
                return False
            actual_pixels = int(actual_match.group(1)) * int(actual_match.group(2))
            expected_pixels = int(expected_match.group(1)) * int(expected_match.group(2))
            return actual_pixels >= expected_pixels
    actual = _coerce(actual, expected)
    if constraint.operator == ConstraintOperator.EQ:
        return str(actual).lower() == str(expected).lower() if isinstance(expected, str) else actual == expected
    if constraint.operator == ConstraintOperator.LTE:
        return float(actual) <= float(expected)
    if constraint.operator == ConstraintOperator.GTE:
        return float(actual) >= float(expected)
    values = expected if isinstance(expected, list) else [expected]
    contained = actual in values
    return not contained if constraint.operator == ConstraintOperator.NOT_IN else contained


class EvidenceCheckTool:
    name = "evidence_check"
    description = "按正确型号和地区核验关键字段，输出 matched/not_matched/unknown/conflict。"

    def __init__(self, database_path: Path | str, *, price_max_age_days: int = 30) -> None:
        self.database_path = Path(database_path).resolve()
        self.price_max_age_days = price_max_age_days

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
                        "required_fields": {
                            "type": "array", "items": {"type": "string", "enum": sorted(CHECKABLE_FIELDS)},
                        },
                        "constraints": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "field": {"type": "string", "enum": sorted(CHECKABLE_FIELDS)},
                                    "operator": {"type": "string", "enum": ["eq", "lte", "gte", "in", "not_in"]},
                                    "value": {},
                                    "hard": {"type": "boolean"},
                                },
                                "required": ["field", "operator", "value"],
                            },
                        },
                        "reason": {"type": "string", "maxLength": 200},
                        "parent_step": {"type": ["integer", "null"]},
                    },
                    "required": ["model_ids", "required_fields", "constraints", "reason"],
                    "additionalProperties": False,
                },
            },
        }

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise FileNotFoundError("governed product database is unavailable")
        connection = sqlite3.connect(f"file:{self.database_path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection

    @staticmethod
    def _resolve_model_id(connection: sqlite3.Connection, requested: str) -> str:
        exact = connection.execute(
            "SELECT model_id FROM products WHERE lower(model_id)=lower(?)", (requested,)
        ).fetchone()
        if exact:
            return str(exact["model_id"])
        token = requested.strip().lower()
        matches = connection.execute(
            "SELECT model_id FROM products WHERE lower(model_id) LIKE ? OR lower(model_name) LIKE ? "
            "ORDER BY model_id LIMIT 2",
            (f"%{token}%", f"%{token}%"),
        ).fetchall()
        return str(matches[0]["model_id"]) if len(matches) == 1 else requested

    @staticmethod
    def _evidence_reference(row: sqlite3.Row, field: str) -> EvidenceReference:
        return EvidenceReference(
            evidence_id=row["evidence_id"],
            source_id=row["source_id"],
            source_url=row["url"],
            source_type=row["source_type"],
            model_id=row["model_id"],
            region=row["source_region"],
            field=field,
            value=row["normalized_value"],
            location=row["evidence_location"],
            effective_time=row["effective_time"],
        )

    def _price_assessment(
        self, connection: sqlite3.Connection, model_id: str, field: str, constraint: ConstraintSpec | None
    ) -> FieldAssessment:
        row = connection.execute(
            "SELECT p.model_id, p.region AS product_region, po.price_cny, po.stock_status, po.url, "
            "po.observed_at, po.observation_id, po.region AS source_region "
            "FROM products p LEFT JOIN price_observations po ON po.observation_id = ("
            "SELECT observation_id FROM price_observations WHERE model_id=p.model_id "
            "ORDER BY observed_at DESC LIMIT 1) WHERE p.model_id=?",
            (model_id,),
        ).fetchone()
        if row is None or row[field] is None:
            return FieldAssessment(field=field, status=ConstraintStatus.UNKNOWN, expected=constraint, reason="没有价格观测。")
        observed_at = datetime.fromisoformat(str(row["observed_at"]).replace("Z", "+00:00"))
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        age_days = (datetime.now(UTC) - observed_at.astimezone(UTC)).days
        reference = EvidenceReference(
            source_id=row["observation_id"], source_url=row["url"], source_type="retail_price",
            model_id=model_id, region=row["source_region"], field=field, value=row[field],
            location="price_observations latest append-only record", effective_time=row["observed_at"],
        )
        if row["source_region"] != row["product_region"]:
            return FieldAssessment(
                field=field, status=ConstraintStatus.CONFLICT, actual_value=row[field], expected=constraint,
                reason="价格观测地区与商品版本不一致。", evidence=[reference],
            )
        if age_days > self.price_max_age_days:
            return FieldAssessment(
                field=field, status=ConstraintStatus.UNKNOWN, actual_value=row[field], expected=constraint,
                reason=f"价格观测已超过 {self.price_max_age_days} 天，只作历史参考。", evidence=[reference],
            )
        matched = _matches(row[field], constraint)
        return FieldAssessment(
            field=field,
            status=ConstraintStatus.MATCHED if matched else ConstraintStatus.NOT_MATCHED,
            actual_value=row[field], expected=constraint,
            reason="价格观测有时效且满足条件。" if matched else "价格观测有时效但不满足条件。",
            evidence=[reference],
        )

    def _evidence_only_assessment(
        self, connection: sqlite3.Connection, product: sqlite3.Row, field: str, constraint: ConstraintSpec | None
    ) -> FieldAssessment:
        rows = connection.execute(
            "SELECT e.*, s.url, s.source_type, s.region AS source_region, s.is_official "
            "FROM evidence_records e JOIN source_records s ON s.source_id=e.source_id "
            "WHERE e.model_id=? AND e.normalized_field=? ORDER BY s.is_official DESC, e.confidence_level",
            (product["model_id"], field),
        ).fetchall()
        rows = [row for row in rows if row["source_region"] == product["region"]]
        if not rows:
            return FieldAssessment(field=field, status=ConstraintStatus.UNKNOWN, expected=constraint, reason="没有该字段证据。")
        values = {str(row["normalized_value"]).strip().lower() for row in rows}
        references = [self._evidence_reference(row, field) for row in rows]
        if len(values) > 1 or any(row["conflict_group"] for row in rows):
            return FieldAssessment(
                field=field, status=ConstraintStatus.CONFLICT, actual_value=sorted(values), expected=constraint,
                reason="该证据字段存在冲突。", evidence=references,
            )
        actual = rows[0]["normalized_value"]
        matched = _matches(actual, constraint)
        return FieldAssessment(
            field=field, status=ConstraintStatus.MATCHED if matched else ConstraintStatus.NOT_MATCHED,
            actual_value=actual, expected=constraint,
            reason="证据字段满足条件。" if matched else "证据字段不满足条件。", evidence=references,
        )

    def _product_assessment(
        self, connection: sqlite3.Connection, product: sqlite3.Row, field: str, constraint: ConstraintSpec | None
    ) -> FieldAssessment:
        actual = product[field]
        if actual is None:
            return FieldAssessment(field=field, status=ConstraintStatus.UNKNOWN, expected=constraint, reason="结构化字段未知。")
        evidence_rows = connection.execute(
            "SELECT e.*, s.url, s.source_type, s.region AS source_region, s.is_official "
            "FROM evidence_records e JOIN source_records s ON s.source_id=e.source_id "
            "WHERE e.model_id=? AND e.normalized_field=? ORDER BY s.is_official DESC, e.confidence_level",
            (product["model_id"], field),
        ).fetchall()
        correct_region = [row for row in evidence_rows if row["source_region"] == product["region"]]
        if not correct_region:
            return FieldAssessment(
                field=field, status=ConstraintStatus.UNKNOWN, actual_value=actual, expected=constraint,
                reason="字段存在，但没有属于正确型号与地区版本的可访问证据。",
            )
        values = {str(row["normalized_value"]).strip().lower() for row in correct_region}
        conflict_groups = {row["conflict_group"] for row in correct_region if row["conflict_group"]}
        references = [self._evidence_reference(row, field) for row in correct_region]
        if len(values) > 1 or conflict_groups:
            return FieldAssessment(
                field=field, status=ConstraintStatus.CONFLICT, actual_value=actual, expected=constraint,
                reason="同一型号和地区的来源值存在冲突。", evidence=references,
            )
        matched = _matches(actual, constraint)
        return FieldAssessment(
            field=field,
            status=ConstraintStatus.MATCHED if matched else ConstraintStatus.NOT_MATCHED,
            actual_value=actual, expected=constraint,
            reason="字段有同型号、同地区证据且满足条件。" if matched else "字段有证据但不满足条件。",
            evidence=references,
        )

    async def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        model_ids = list(dict.fromkeys(str(item) for item in arguments.get("model_ids", [])))[:10]
        required_fields = list(dict.fromkeys(str(item) for item in arguments.get("required_fields", [])))
        invalid_fields = sorted(set(required_fields) - CHECKABLE_FIELDS)
        if not model_ids or invalid_fields:
            return ToolResult(
                tool=self.name, status="failed", error_code="INVALID_EVIDENCE_REQUEST",
                summary="证据核验参数不完整或字段不在白名单。",
                data={"invalid_fields": invalid_fields},
            )
        constraints: dict[str, ConstraintSpec] = {}
        for raw in arguments.get("constraints", []):
            try:
                item = ConstraintSpec.model_validate(raw)
            except ValueError:
                continue
            constraints[item.field] = item
        try:
            connection = self._connect()
        except FileNotFoundError:
            return ToolResult(
                tool=self.name, status="failed", error_code="DATABASE_UNAVAILABLE",
                summary="证据数据库不可用。", data={"models": {}},
            )
        output: dict[str, list[dict[str, Any]]] = {}
        status_counts = {status.value: 0 for status in ConstraintStatus}
        try:
            for requested_model_id in model_ids:
                model_id = self._resolve_model_id(connection, requested_model_id)
                product = connection.execute("SELECT * FROM products WHERE model_id=?", (model_id,)).fetchone()
                assessments: list[FieldAssessment] = []
                if product is None:
                    assessments = [
                        FieldAssessment(
                            field=field, status=ConstraintStatus.UNKNOWN, expected=constraints.get(field),
                            reason="型号不存在于治理数据集。",
                        )
                        for field in required_fields
                    ]
                else:
                    for field in required_fields:
                        if field in PRICE_FIELDS:
                            assessment = self._price_assessment(connection, model_id, field, constraints.get(field))
                        elif field in EVIDENCE_ONLY_FIELDS:
                            assessment = self._evidence_only_assessment(
                                connection, product, field, constraints.get(field)
                            )
                        else:
                            assessment = self._product_assessment(connection, product, field, constraints.get(field))
                        assessments.append(assessment)
                for assessment in assessments:
                    status_counts[assessment.status.value] += 1
                output[model_id] = [item.model_dump(mode="json") for item in assessments]
        finally:
            connection.close()
        blocking = status_counts[ConstraintStatus.UNKNOWN.value] + status_counts[ConstraintStatus.CONFLICT.value]
        summary = (
            f"核验 {len(model_ids)} 个型号、{len(required_fields)} 个字段；"
            f"matched={status_counts['matched']}，not_matched={status_counts['not_matched']}，"
            f"unknown={status_counts['unknown']}，conflict={status_counts['conflict']}。"
        )
        return ToolResult(
            tool=self.name, status="success", summary=summary,
            data={"models": output, "status_counts": status_counts, "evidence_incomplete": blocking > 0},
        )
