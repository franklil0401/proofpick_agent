"""Read-only deterministic safety gate for complete tool-produced candidate pools."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import (
    CandidateVerification,
    ConstraintOperator,
    ConstraintProvenance,
    ConstraintResult,
    ConstraintSet,
    ConstraintStrength,
    NormalizedConstraint,
    VerificationBatch,
    VerificationStatus,
)
from .normalize import normalize_resolution


VERIFIER_VERSION = "smartbuy-constraint-checker-v1"
PRODUCT_FIELDS = frozenset(
    {
        "brand",
        "region",
        "display_size_inch",
        "resolution",
        "refresh_rate_hz",
        "is_oled",
        "has_usb_c",
        "usb_c_video",
        "usb_c_power_delivery_w",
        "stand_adjustment",
        "width_mm",
        "weight_kg",
        "panel_type",
    }
)
PRICE_FIELDS = frozenset({"price_cny"})
STABLE_MODEL_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")


def _authorizer(action: int, _arg1: str | None, _arg2: str | None, _db: str | None, _trigger: str | None) -> int:
    if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _parse_evidence_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _signature(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.8f}".rstrip("0").rstrip(".")
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip().lower()


def _resolution_pixels(value: Any) -> int | None:
    normalized = normalize_resolution(value)
    match = re.fullmatch(r"(\d{3,5})x(\d{3,5})", normalized)
    return int(match.group(1)) * int(match.group(2)) if match else None


def _equivalent_field_value(field: str, left: Any, right: Any) -> bool:
    if field in {"is_oled", "has_usb_c", "usb_c_video"}:
        return bool(left) is bool(right)
    if field in {
        "display_size_inch", "refresh_rate_hz", "usb_c_power_delivery_w", "width_mm"
    }:
        try:
            return float(left) == float(right)
        except (TypeError, ValueError):
            return False
    if field == "resolution":
        return normalize_resolution(left) == normalize_resolution(right)
    return _signature(left) == _signature(right)


def _matches(actual: Any, constraint: NormalizedConstraint) -> bool:
    expected = constraint.normalized_value
    operator = constraint.operator
    if constraint.field == "resolution":
        actual_normalized = normalize_resolution(actual)
        expected_normalized = normalize_resolution(expected)
        if operator == ConstraintOperator.EQ:
            return actual_normalized == expected_normalized
        if operator == ConstraintOperator.GTE:
            actual_pixels = _resolution_pixels(actual_normalized)
            expected_pixels = _resolution_pixels(expected_normalized)
            return actual_pixels is not None and expected_pixels is not None and actual_pixels >= expected_pixels
    if operator == ConstraintOperator.CONTAINS_ALL:
        required = expected if isinstance(expected, list) else [expected]
        actual_text = str(actual).lower()
        return all(str(item).lower() in actual_text for item in required)
    if operator in {ConstraintOperator.IN, ConstraintOperator.NOT_IN}:
        choices = expected if isinstance(expected, list) else [expected]
        contained = _signature(actual) in {_signature(item) for item in choices}
        return not contained if operator == ConstraintOperator.NOT_IN else contained
    if operator == ConstraintOperator.RANGE:
        if not isinstance(expected, list) or len(expected) != 2:
            return False
        return float(expected[0]) <= float(actual) <= float(expected[1])
    if operator == ConstraintOperator.LTE:
        return float(actual) <= float(expected)
    if operator == ConstraintOperator.GTE:
        return float(actual) >= float(expected)
    if operator == ConstraintOperator.EQ:
        if expected is None:
            return actual is None
        if isinstance(expected, bool):
            return bool(actual) is expected
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            return float(actual) == float(expected)
        return _signature(actual) == _signature(expected)
    return False


class CandidateConstraintVerifier:
    """Verify every member of a complete candidate pool without model input."""

    def __init__(
        self,
        database_path: Path | str,
        *,
        price_max_age_days: int = 30,
        as_of: datetime | None = None,
    ) -> None:
        self.database_path = Path(database_path).resolve()
        self.price_max_age_days = price_max_age_days
        self.as_of = (as_of or datetime.now(UTC)).astimezone(UTC)

    @property
    def checked_at(self) -> str:
        return self.as_of.isoformat().replace("+00:00", "Z")

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise FileNotFoundError("governed product database is unavailable")
        connection = sqlite3.connect(
            f"file:{self.database_path.as_posix()}?mode=ro", uri=True, timeout=2.0
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.set_authorizer(_authorizer)
        return connection

    @staticmethod
    def _identity_constraint(model_id: str, *, note: str) -> NormalizedConstraint:
        return NormalizedConstraint(
            field="model_id",
            operator=ConstraintOperator.EQ,
            normalized_value=model_id,
            hard_or_soft=ConstraintStrength.HARD,
            provenance=ConstraintProvenance.SYSTEM_DEFAULT,
            source_text="工具候选池完整性检查",
            source_turn=1,
            confidence=1.0,
            supported=True,
            note=note,
        )

    def _invalid_candidate(self, model_id: str, reason: str) -> CandidateVerification:
        return CandidateVerification(
            model_id=model_id,
            overall_status=VerificationStatus.FAILED,
            constraint_results=[
                ConstraintResult(
                    constraint=self._identity_constraint(model_id, note=reason),
                    actual_value=None,
                    status=VerificationStatus.FAILED,
                    reason=reason,
                )
            ],
            eligible=False,
            violated_fields=["model_id"],
            checked_at=self.checked_at,
            verifier_version=VERIFIER_VERSION,
        )

    def _evidence(
        self, connection: sqlite3.Connection, model_id: str, region: str, field: str
    ) -> tuple[list[sqlite3.Row], bool]:
        rows = connection.execute(
            "SELECT e.evidence_id, e.source_id, e.normalized_value, e.conflict_group, "
            "s.region AS source_region FROM evidence_records e "
            "JOIN source_records s ON s.source_id=e.source_id "
            "WHERE e.model_id=? AND e.normalized_field=? ORDER BY e.evidence_id",
            (model_id, field),
        ).fetchall()
        correct = [row for row in rows if row["source_region"] == region]
        values = {_signature(_parse_evidence_value(row["normalized_value"])) for row in correct}
        conflict = len(values) > 1 or any(row["conflict_group"] for row in correct)
        return correct, conflict

    def _price(
        self, connection: sqlite3.Connection, product: sqlite3.Row, constraint: NormalizedConstraint
    ) -> tuple[ConstraintResult, str | None]:
        row = connection.execute(
            "SELECT observation_id, price_cny, seller, region, url, observed_at "
            "FROM price_observations WHERE model_id=? "
            "ORDER BY observed_at DESC, observation_id DESC LIMIT 1",
            (product["model_id"],),
        ).fetchone()
        if row is None:
            return (
                ConstraintResult(
                    constraint=constraint,
                    status=VerificationStatus.UNKNOWN,
                    reason="没有价格观测，不能判定为预算内。",
                ),
                None,
            )
        evidence_id = str(row["observation_id"])
        source_id = f"price_observation:{evidence_id}"
        observed_at = datetime.fromisoformat(str(row["observed_at"]).replace("Z", "+00:00"))
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        observed_at = observed_at.astimezone(UTC)
        actual = float(row["price_cny"])
        if str(row["region"]) != str(product["region"]):
            status = VerificationStatus.CONFLICT
            reason = "最新价格观测地区与商品版本不一致。"
        elif observed_at > self.as_of:
            status = VerificationStatus.UNKNOWN
            reason = "价格观测时间晚于本次复核时间，不能使用。"
        elif (self.as_of - observed_at).days > self.price_max_age_days:
            status = VerificationStatus.UNKNOWN
            reason = f"价格观测已超过 {self.price_max_age_days} 天，只能作为历史参考。"
        else:
            passed = _matches(actual, constraint)
            status = VerificationStatus.PASSED if passed else VerificationStatus.FAILED
            reason = (
                f"最新可用价格观测满足约束；observed_at={row['observed_at']}。"
                if passed
                else f"最新可用价格观测不满足约束；observed_at={row['observed_at']}。"
            )
        return (
            ConstraintResult(
                constraint=constraint,
                actual_value=actual,
                status=status,
                reason=reason,
                evidence_id=evidence_id,
                source_id=source_id,
            ),
            str(row["observed_at"]),
        )

    def _product_field(
        self, connection: sqlite3.Connection, product: sqlite3.Row, constraint: NormalizedConstraint
    ) -> ConstraintResult:
        field = constraint.field
        actual = product[field]
        rows, evidence_conflict = self._evidence(
            connection, str(product["model_id"]), str(product["region"]), field
        )
        evidence_id = str(rows[0]["evidence_id"]) if rows else None
        source_id = str(rows[0]["source_id"]) if rows else None
        if actual is None:
            return ConstraintResult(
                constraint=constraint,
                actual_value=None,
                status=VerificationStatus.UNKNOWN,
                reason="结构化字段为 null，未知值不能用 0 代替。",
                evidence_id=evidence_id,
                source_id=source_id,
            )
        if not rows:
            return ConstraintResult(
                constraint=constraint,
                actual_value=actual,
                status=VerificationStatus.UNKNOWN,
                reason="结构化字段存在，但没有同型号、同地区的 evidence_record。",
            )
        evidence_values = [_parse_evidence_value(row["normalized_value"]) for row in rows]
        evidence_disagrees = any(
            not _equivalent_field_value(field, value, actual) for value in evidence_values
        )
        if evidence_conflict or evidence_disagrees:
            return ConstraintResult(
                constraint=constraint,
                actual_value=actual,
                status=VerificationStatus.CONFLICT,
                reason="产品字段与证据值不一致，或同型号同地区证据存在冲突。",
                evidence_id=evidence_id,
                source_id=source_id,
            )
        passed = _matches(actual, constraint)
        return ConstraintResult(
            constraint=constraint,
            actual_value=actual,
            status=VerificationStatus.PASSED if passed else VerificationStatus.FAILED,
            reason="字段值及同地区证据满足约束。" if passed else "字段值有证据，但不满足用户约束。",
            evidence_id=evidence_id,
            source_id=source_id,
        )

    def _verify_one(
        self,
        connection: sqlite3.Connection,
        model_id: str,
        constraints: list[NormalizedConstraint],
    ) -> CandidateVerification:
        if not STABLE_MODEL_ID.fullmatch(model_id):
            return self._invalid_candidate(model_id, "候选不是稳定 model_id，已 fail closed。")
        product = connection.execute(
            "SELECT * FROM products WHERE model_id=?", (model_id,)
        ).fetchone()
        if product is None:
            return self._invalid_candidate(model_id, "候选型号不在治理数据库中，已 fail closed。")

        results: list[ConstraintResult] = []
        price_observed_at: str | None = None
        for constraint in constraints:
            if not constraint.supported or constraint.ambiguous:
                results.append(
                    ConstraintResult(
                        constraint=constraint,
                        status=VerificationStatus.UNKNOWN,
                        reason=constraint.note or "约束不在当前支持范围或表达有歧义。",
                    )
                )
            elif constraint.field in PRICE_FIELDS:
                result, observed_at = self._price(connection, product, constraint)
                results.append(result)
                price_observed_at = observed_at or price_observed_at
            elif constraint.field in PRODUCT_FIELDS:
                results.append(self._product_field(connection, product, constraint))
            else:
                results.append(
                    ConstraintResult(
                        constraint=constraint,
                        status=VerificationStatus.UNKNOWN,
                        reason="约束字段不在确定性读取白名单。",
                    )
                )

        hard_results = [
            result
            for result in results
            if result.constraint.active and result.constraint.hard_or_soft == ConstraintStrength.HARD
        ]
        hard_statuses = {result.status for result in hard_results}
        # Active ambiguous/unsupported requests are clarification gates even
        # when deliberately classified as soft preferences. They must not be
        # silently treated as fully verified recommendations.
        clarification_required = any(
            result.constraint.active
            and (not result.constraint.supported or result.constraint.ambiguous)
            for result in results
        )
        if VerificationStatus.FAILED in hard_statuses:
            overall = VerificationStatus.FAILED
        elif VerificationStatus.CONFLICT in hard_statuses:
            overall = VerificationStatus.CONFLICT
        elif VerificationStatus.UNKNOWN in hard_statuses:
            overall = VerificationStatus.UNKNOWN
        elif clarification_required:
            overall = VerificationStatus.UNKNOWN
        else:
            overall = VerificationStatus.PASSED
        eligible = overall == VerificationStatus.PASSED
        violated = [result.constraint.field for result in hard_results if result.status == VerificationStatus.FAILED]
        unknown = [result.constraint.field for result in hard_results if result.status == VerificationStatus.UNKNOWN]
        conflicts = [result.constraint.field for result in hard_results if result.status == VerificationStatus.CONFLICT]
        unsupported = [
            result.constraint.field
            for result in results
            if not result.constraint.supported or result.constraint.ambiguous
        ]
        evidence_ids = list(dict.fromkeys(result.evidence_id for result in results if result.evidence_id))
        source_ids = list(dict.fromkeys(result.source_id for result in results if result.source_id))
        return CandidateVerification(
            model_id=model_id,
            overall_status=overall,
            constraint_results=results,
            eligible=eligible,
            violated_fields=list(dict.fromkeys(violated)),
            unknown_fields=list(dict.fromkeys(unknown)),
            conflict_fields=list(dict.fromkeys(conflicts)),
            unsupported_constraints=list(dict.fromkeys(unsupported)),
            evidence_ids=evidence_ids,
            source_ids=source_ids,
            checked_at=self.checked_at,
            verifier_version=VERIFIER_VERSION,
            price_observed_at=price_observed_at,
        )

    def verify_candidates(
        self, constraint_set: ConstraintSet, candidate_pool_model_ids: list[str]
    ) -> VerificationBatch:
        pool = [str(item).strip() for item in candidate_pool_model_ids if str(item).strip()]
        counts = Counter(pool)
        unique_pool = list(dict.fromkeys(pool))
        active_constraints = constraint_set.active()
        try:
            connection = self._connect()
        except FileNotFoundError:
            return self.fail_closed(constraint_set, unique_pool, "治理数据库不可用。")
        candidates: list[CandidateVerification] = []
        try:
            for model_id in unique_pool:
                if counts[model_id] > 1:
                    candidates.append(self._invalid_candidate(model_id, "工具候选池包含重复 model_id，已 fail closed。"))
                else:
                    candidates.append(self._verify_one(connection, model_id, active_constraints))
        finally:
            connection.close()
        unsupported = [item for item in active_constraints if not item.supported or item.ambiguous]
        eligible = [item.model_id for item in candidates if item.eligible]
        rejected = [item.model_id for item in candidates if not item.eligible]
        semantic = {
            "version": VERIFIER_VERSION,
            "constraints": [item.model_dump(mode="json") for item in active_constraints],
            "pool": pool,
            "candidates": [
                {
                    "model_id": item.model_id,
                    "overall_status": item.overall_status.value,
                    "eligible": item.eligible,
                    "results": [
                        {
                            "field": result.constraint.field,
                            "status": result.status.value,
                            "actual": result.actual_value,
                            "evidence_id": result.evidence_id,
                            "source_id": result.source_id,
                        }
                        for result in item.constraint_results
                    ],
                }
                for item in candidates
            ],
        }
        fingerprint = hashlib.sha256(
            json.dumps(semantic, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return VerificationBatch(
            verifier_version=VERIFIER_VERSION,
            checked_at=self.checked_at,
            constraint_set_version=constraint_set.version,
            candidate_pool_model_ids=pool,
            candidates=candidates,
            unsupported_constraints=unsupported,
            eligible_model_ids=eligible,
            rejected_model_ids=rejected,
            semantic_fingerprint=fingerprint,
        )

    def fail_closed(
        self, constraint_set: ConstraintSet, candidate_pool_model_ids: list[str], reason: str
    ) -> VerificationBatch:
        candidates = [self._invalid_candidate(model_id, reason) for model_id in candidate_pool_model_ids]
        fingerprint = hashlib.sha256(
            json.dumps(
                {"version": VERIFIER_VERSION, "pool": candidate_pool_model_ids, "reason": reason},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return VerificationBatch(
            verifier_version=VERIFIER_VERSION,
            checked_at=self.checked_at,
            constraint_set_version=constraint_set.version,
            candidate_pool_model_ids=candidate_pool_model_ids,
            candidates=candidates,
            unsupported_constraints=[
                item for item in constraint_set.active() if not item.supported or item.ambiguous
            ],
            eligible_model_ids=[],
            rejected_model_ids=list(candidate_pool_model_ids),
            semantic_fingerprint=fingerprint,
            degraded=True,
            degrade_reason=reason,
        )


def verify_candidates(
    constraint_set: ConstraintSet,
    candidate_pool_model_ids: list[str],
    database_path: Path | str,
    *,
    price_max_age_days: int = 30,
    as_of: datetime | None = None,
) -> VerificationBatch:
    """Functional entry point for scripts and callers that do not retain a verifier instance."""
    return CandidateConstraintVerifier(
        database_path, price_max_age_days=price_max_age_days, as_of=as_of
    ).verify_candidates(constraint_set, candidate_pool_model_ids)
