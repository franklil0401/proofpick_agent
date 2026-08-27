"""Read-only, allow-listed Text2SQL execution with a deterministic fallback."""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from smartbuy.tools.base import ToolResult


class SQLValidationError(ValueError):
    """Raised before an unsafe or out-of-contract query reaches SQLite."""


ALLOWED_COLUMNS = {
    "products": {
        "model_id", "brand", "model_name", "region", "display_size_inch", "resolution",
        "refresh_rate_hz", "panel_type", "is_oled", "has_usb_c", "usb_c_video",
        "usb_c_power_delivery_w", "stand_adjustment", "width_mm", "weight_kg", "warranty",
        "release_date", "official_source_id", "source_updated_at",
    },
    "price_observations": {
        "observation_id", "model_id", "price_cny", "seller", "region", "stock_status", "url",
        "observed_at", "price_type",
    },
    "source_records": {
        "source_id", "model_id", "source_type", "title", "url", "is_official", "region",
        "published_at", "accessed_at", "content_hash", "redistribution_status", "notes",
    },
    "evidence_records": {
        "evidence_id", "source_id", "model_id", "normalized_field", "normalized_value",
        "original_value", "evidence_location", "confidence_level", "effective_time", "conflict_group",
    },
}
ALLOWED_TABLES = frozenset(ALLOWED_COLUMNS)
FORBIDDEN = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|ATTACH|DETACH|PRAGMA|REPLACE|CREATE|VACUUM|REINDEX|ANALYZE|TRIGGER)\b",
    re.IGNORECASE,
)
COMMENT = re.compile(r"--|/\*|\*/")


def validate_select_sql(sql: str) -> str:
    """Apply a conservative lexical gate before SQLite's authorizer gate."""
    candidate = sql.strip()
    if candidate.endswith(";"):
        candidate = candidate[:-1].rstrip()
    if not candidate or not re.match(r"^SELECT\b", candidate, flags=re.IGNORECASE):
        raise SQLValidationError("only a single SELECT statement is allowed")
    if ";" in candidate:
        raise SQLValidationError("multiple SQL statements are not allowed")
    if COMMENT.search(candidate) or FORBIDDEN.search(candidate):
        raise SQLValidationError("SQL contains a forbidden token")
    referenced = {
        match.group(1).lower()
        for match in re.finditer(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", candidate, re.IGNORECASE)
    }
    unknown = referenced - ALLOWED_TABLES
    if unknown:
        raise SQLValidationError(f"table is not allow-listed: {sorted(unknown)[0]}")
    if not referenced:
        raise SQLValidationError("query must read an allow-listed table")
    return candidate


def _authorizer(action: int, arg1: str | None, arg2: str | None, _db: str | None, _trigger: str | None) -> int:
    if action == sqlite3.SQLITE_READ:
        table = (arg1 or "").lower()
        column = (arg2 or "").lower()
        if table not in ALLOWED_COLUMNS or column not in ALLOWED_COLUMNS[table]:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    allowed_actions = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION}
    return sqlite3.SQLITE_OK if action in allowed_actions else sqlite3.SQLITE_DENY


class Text2SQLTool:
    name = "text2sql"
    description = "对只读商品 SQLite 执行经过验证的 SELECT；失败时使用受控筛选模板。"

    def __init__(self, database_path: Path | str, *, max_rows: int = 20, timeout_seconds: float = 2.0) -> None:
        self.database_path = Path(database_path).resolve()
        self.max_rows = max_rows
        self.timeout_seconds = timeout_seconds

    @property
    def schema(self) -> dict[str, Any]:
        fields = sorted(ALLOWED_COLUMNS["products"] | {"price_cny", "observed_at"})
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "单条 SELECT，不得包含注释或写操作"},
                        "filters": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "field": {"type": "string", "enum": fields},
                                    "operator": {"type": "string", "enum": ["eq", "lte", "gte", "in", "not_in"]},
                                    "value": {},
                                },
                                "required": ["field", "operator", "value"],
                            },
                            "description": "与 SQL 等价的结构化条件，供验证失败时受控降级",
                        },
                        "reason": {"type": "string", "maxLength": 200},
                    },
                    "required": ["sql", "filters", "reason"],
                    "additionalProperties": False,
                },
            },
        }

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise FileNotFoundError("governed product database is unavailable")
        uri = f"file:{self.database_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=self.timeout_seconds)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection

    def _execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> tuple[list[dict[str, Any]], list[str]]:
        validated = validate_select_sql(sql)
        started = time.monotonic()
        connection = self._connect()
        try:
            connection.set_authorizer(_authorizer)
            connection.set_progress_handler(
                lambda: 1 if time.monotonic() - started > self.timeout_seconds else 0,
                1_000,
            )
            bounded = f"SELECT * FROM ({validated}) AS safe_result LIMIT {self.max_rows + 1}"
            cursor = connection.execute(bounded, parameters)
            rows = [dict(row) for row in cursor.fetchall()]
            columns = [item[0] for item in cursor.description or []]
            if len(rows) > self.max_rows:
                rows = rows[: self.max_rows]
            return rows, columns
        except sqlite3.DatabaseError as exc:
            raise SQLValidationError("query was rejected or exceeded the execution limit") from exc
        finally:
            connection.close()

    def _normalize_model_filters(self, filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = [dict(item) for item in filters]
        resolution_aliases = {
            "qhd": "2560x1440", "2k": "2560x1440", "1440p": "2560x1440", "wqhd": "2560x1440",
            "4k": "3840x2160", "uhd": "3840x2160", "5k": "5120x2880", "8k": "7680x4320",
        }
        for item in normalized:
            if item.get("field") != "resolution":
                continue
            values = item.get("value") if isinstance(item.get("value"), list) else [item.get("value")]
            mapped = [resolution_aliases.get(str(value).strip().lower(), value) for value in values]
            item["value"] = mapped if isinstance(item.get("value"), list) else mapped[0]
        model_filters = [item for item in normalized if item.get("field") == "model_id"]
        if not model_filters or not self.database_path.is_file():
            return normalized
        connection = self._connect()
        try:
            for item in model_filters:
                values = item.get("value") if isinstance(item.get("value"), list) else [item.get("value")]
                resolved = []
                for value in values:
                    token = str(value or "").strip()
                    rows = connection.execute(
                        "SELECT model_id FROM products WHERE lower(model_id)=lower(?) "
                        "OR lower(model_id) LIKE ? OR lower(model_name) LIKE ? ORDER BY model_id LIMIT 2",
                        (token, f"%{token.lower()}%", f"%{token.lower()}%"),
                    ).fetchall()
                    resolved.append(rows[0][0] if len(rows) == 1 else value)
                item["value"] = resolved if isinstance(item.get("value"), list) else resolved[0]
        finally:
            connection.close()
        return normalized

    @staticmethod
    def _template(filters: list[dict[str, Any]]) -> tuple[str, tuple[Any, ...], int]:
        select = (
            "SELECT p.model_id, p.brand, p.model_name, p.region, p.display_size_inch, p.resolution, "
            "p.refresh_rate_hz, p.panel_type, p.is_oled, p.has_usb_c, p.usb_c_video, "
            "p.usb_c_power_delivery_w, p.stand_adjustment, p.width_mm, "
            "po.price_cny, po.observed_at, po.seller, po.stock_status "
            "FROM products p LEFT JOIN price_observations po ON po.observation_id = ("
            "SELECT po2.observation_id FROM price_observations po2 WHERE po2.model_id = p.model_id "
            "ORDER BY po2.observed_at DESC LIMIT 1)"
        )
        mapping = {
            **{field: f"p.{field}" for field in ALLOWED_COLUMNS["products"]},
            "price_cny": "po.price_cny",
            "observed_at": "po.observed_at",
        }
        operators = {"eq": "=", "lte": "<=", "gte": ">="}
        clauses: list[str] = []
        parameters: list[Any] = []
        for item in filters:
            field = str(item.get("field", ""))
            operator = str(item.get("operator", ""))
            value = item.get("value")
            if field not in mapping:
                continue
            if operator in operators:
                clauses.append(f"{mapping[field]} {operators[operator]} ?")
                parameters.append(value)
            elif operator in {"in", "not_in"} and isinstance(value, list) and value:
                placeholders = ", ".join("?" for _ in value)
                clauses.append(f"{mapping[field]} {'NOT IN' if operator == 'not_in' else 'IN'} ({placeholders})")
                parameters.extend(value)
        if clauses:
            select += " WHERE " + " AND ".join(clauses)
        select += " ORDER BY po.price_cny IS NULL, po.price_cny, p.model_id"
        return select, tuple(parameters), len(clauses)

    async def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        sql = str(arguments.get("sql", ""))
        filters = arguments.get("filters") if isinstance(arguments.get("filters"), list) else []
        filters = self._normalize_model_filters(filters)
        degraded = False
        executed_sql = sql
        try:
            rows, columns = self._execute(sql)
            if "model_id" not in columns:
                raise SQLValidationError("candidate query must return model_id")
            if not rows and filters:
                raise SQLValidationError("zero rows require controlled-filter confirmation")
        except (SQLValidationError, FileNotFoundError):
            degraded = True
            if not filters:
                return ToolResult(
                    tool=self.name,
                    status="failed",
                    summary="生成 SQL 未返回 model_id，且没有可用的结构化筛选条件。",
                    error_code="MODEL_ID_REQUIRED",
                    data={"executed": False, "row_count": 0},
                )
            executed_sql, parameters, applied_filter_count = self._template(filters)
            if applied_filter_count == 0:
                return ToolResult(
                    tool=self.name,
                    status="failed",
                    summary="结构化条件不属于治理字段，不能退化为全表查询。",
                    error_code="UNSUPPORTED_FILTERS",
                    data={"executed": False, "row_count": 0},
                )
            try:
                rows, columns = self._execute(executed_sql, parameters)
            except (SQLValidationError, FileNotFoundError):
                return ToolResult(
                    tool=self.name,
                    status="failed",
                    summary="只读 SQL 与受控模板均未能执行。",
                    error_code="SQL_EXECUTION_FAILED",
                    data={"executed": False, "row_count": 0},
                )
        missing_fields = {
            column: sum(row.get(column) is None for row in rows)
            for column in columns
            if any(row.get(column) is None for row in rows)
        }
        return ToolResult(
            tool=self.name,
            status="degraded" if degraded else "success",
            degraded=degraded,
            summary=f"只读查询返回 {len(rows)} 个候选；缺失字段 {len(missing_fields)} 类。",
            data={
                "executed": True,
                "sql": executed_sql,
                "rows": rows,
                "row_count": len(rows),
                "columns": columns,
                "missing_fields": missing_fields,
                "fallback_used": degraded,
            },
        )
