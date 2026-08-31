"""Adapter-first mapping between frozen V1 objects and V2 contracts.

The adapter reads V1 output; it does not reimplement comparison, evidence, or
eligibility rules.  Returning to V1 requires exact agreement with the existing
Constraint Checker result.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from smartbuy.constraints.models import (
    ConstraintOperator as V1ConstraintOperator,
    ConstraintProvenance as V1ConstraintProvenance,
    ConstraintStrength as V1ConstraintStrength,
    NormalizedConstraint,
    VerificationStatus,
)
from smartbuy.contracts import (
    Candidate,
    Constraint,
    ConstraintOperator,
    ConstraintProvenance,
    ConstraintStrength,
    FieldState,
    Product,
)
from smartbuy.contracts.models import CandidateFieldDecision
from smartbuy.data.loader import CATALOG_PATH, load_catalog
from smartbuy.domain import DecisionReport
from smartbuy.domain_packs.loader import DomainPackValidationError, LoadedDomainPack
from smartbuy.orchestration import OrchestratorRequest
from smartbuy.orchestration.safety import validate_checker_terminal


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class GenericRequestSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    domain_id: str
    data_version: str
    query: str
    session_id: str | None = None
    user_id: str | None = None
    thread_id: str | None = None
    use_long_term_memory: bool = False


class GenericDecisionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    domain_id: str
    data_version: str
    report_version: str
    constraints: list[Constraint] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    recommended_product_ids: list[str] = Field(default_factory=list)
    abstained: bool


_STATE = {
    VerificationStatus.PASSED: FieldState.MATCHED,
    VerificationStatus.FAILED: FieldState.NOT_MATCHED,
    VerificationStatus.UNKNOWN: FieldState.UNKNOWN,
    VerificationStatus.CONFLICT: FieldState.CONFLICT,
}


class V1CompatibilityAdapter:
    def __init__(self, pack: LoadedDomainPack, *, catalog_path: Path = CATALOG_PATH) -> None:
        self.pack = pack
        self.catalog_path = catalog_path
        self.catalog = load_catalog(catalog_path)
        self._validate_frozen_product_pack()

    def _validate_frozen_product_pack(self) -> None:
        policy = self.pack.pack.policies["product_pack"]
        if self.catalog.data_version != policy["data_version"]:
            raise DomainPackValidationError("V1 catalog data version is not compatible")
        digest = hashlib.sha256(self.catalog_path.read_bytes()).hexdigest()
        if digest != policy["catalog_sha256"]:
            raise DomainPackValidationError("V1 catalog hash does not match the Domain Pack")
        counts = policy["counts"]
        if len(self.catalog.products) != counts["products"]:
            raise DomainPackValidationError("V1 product count does not match the Domain Pack")
        if len({item["brand"] for item in self.catalog.products}) != counts["brands"]:
            raise DomainPackValidationError("V1 brand count does not match the Domain Pack")
        if len(self.catalog.source_records) != counts["sources"]:
            raise DomainPackValidationError("V1 source count does not match the Domain Pack")
        demo_manifest = json.loads(
            (PROJECT_ROOT / "smartbuy/data/demo/manifest.json").read_text(encoding="utf-8")
        )
        if demo_manifest.get("counts", {}).get("evidence") != counts["evidence"]:
            raise DomainPackValidationError("V1 evidence count does not match the Domain Pack")

    def from_v1_request(self, request: OrchestratorRequest) -> GenericRequestSnapshot:
        return GenericRequestSnapshot(
            domain_id=self.pack.domain_id,
            data_version=self.catalog.data_version,
            query=request.query,
            session_id=request.session_id,
            user_id=request.user_id,
            thread_id=request.thread_id,
            use_long_term_memory=request.use_long_term_memory,
        )

    def product_from_v1(self, row: dict[str, Any]) -> Product:
        core = {"model_id", "brand", "model_name", "region", "official_source_id"}
        attributes = {key: value for key, value in row.items() if key not in core}
        for field_id, value in attributes.items():
            if field_id in self.pack.fields and value is not None:
                self.pack.normalize_value(field_id, value)
        return Product(
            product_id=row["model_id"],
            domain_id=self.pack.domain_id,
            brand=row["brand"],
            model_name=row["model_name"],
            region=row["region"],
            attributes=attributes,
            source_ids=[row["official_source_id"]],
            data_version=self.catalog.data_version,
        )

    def products_from_v1(self) -> list[Product]:
        return [self.product_from_v1(dict(row)) for row in self.catalog.products]

    def constraint_from_v1(self, value: NormalizedConstraint) -> Constraint:
        operator = ConstraintOperator(V1ConstraintOperator(value.operator).value)
        supported = bool(value.supported and not value.ambiguous)
        if supported:
            self.pack.validate_operator(value.field, operator)
            if operator in {
                ConstraintOperator.IN,
                ConstraintOperator.NOT_IN,
                ConstraintOperator.CONTAINS_ALL,
                ConstraintOperator.RANGE,
            } and isinstance(value.normalized_value, list):
                normalized = [
                    self.pack.normalize_value(value.field, item, unit=value.unit)
                    for item in value.normalized_value
                ]
            else:
                normalized = self.pack.normalize_value(
                    value.field,
                    value.normalized_value,
                    unit=value.unit,
                )
        else:
            normalized = value.normalized_value
        return Constraint(
            field=value.field,
            operator=operator,
            normalized_value=normalized,
            unit=value.unit,
            strength=ConstraintStrength(V1ConstraintStrength(value.hard_or_soft).value),
            provenance=ConstraintProvenance(V1ConstraintProvenance(value.provenance).value),
            source_text=value.source_text,
            source_turn=value.source_turn,
            confidence=value.confidence,
            proposed_by="deterministic",
            supported=supported,
            active=value.active,
            ambiguous=value.ambiguous,
        )

    def from_v1_report(self, report: DecisionReport) -> GenericDecisionSnapshot:
        validate_checker_terminal(report)
        assert report.constraint_verification is not None
        candidates: list[Candidate] = []
        for value in report.constraint_verification.candidates:
            decisions = [
                CandidateFieldDecision(
                    field_id=item.constraint.field,
                    required_value=item.constraint.normalized_value,
                    actual_value=item.actual_value,
                    state=_STATE[item.status],
                    reason=item.reason,
                    evidence_ids=[item.evidence_id] if item.evidence_id else [],
                    source_ids=[item.source_id] if item.source_id else [],
                )
                for item in value.constraint_results
            ]
            candidates.append(
                Candidate(
                    product_id=value.model_id,
                    field_decisions=decisions,
                    overall_state=_STATE[value.overall_status],
                    eligible=value.eligible,
                    violated_fields=value.violated_fields,
                    unknown_fields=value.unknown_fields,
                    conflict_fields=value.conflict_fields,
                    unsupported_constraints=value.unsupported_constraints,
                    evidence_ids=value.evidence_ids,
                    checker_version=value.verifier_version,
                )
            )
        return GenericDecisionSnapshot(
            domain_id=self.pack.domain_id,
            data_version=self.catalog.data_version,
            report_version=report.report_version,
            constraints=[self.constraint_from_v1(item) for item in report.constraint_set.constraints],
            candidates=candidates,
            recommended_product_ids=report.recommended_model_ids,
            abstained=report.abstained,
        )

    def to_v1_report(
        self,
        snapshot: GenericDecisionSnapshot,
        original: DecisionReport,
    ) -> DecisionReport:
        """Return an exact V1 response only after deterministic consistency checks."""
        validate_checker_terminal(original)
        assert original.constraint_verification is not None
        expected = {item.model_id: item for item in original.constraint_verification.candidates}
        actual = {item.product_id: item for item in snapshot.candidates}
        if set(actual) != set(expected):
            raise DomainPackValidationError("generic candidate pool differs from V1 Checker")
        for product_id, value in expected.items():
            mapped = actual[product_id]
            if mapped.eligible != value.eligible or mapped.overall_state != _STATE[value.overall_status]:
                raise DomainPackValidationError("generic candidate status differs from V1 Checker")
        if snapshot.recommended_product_ids != original.recommended_model_ids:
            raise DomainPackValidationError("generic recommendations differ from V1 response")
        return original.model_copy(deep=True)

    def round_trip_report(self, report: DecisionReport) -> DecisionReport:
        return self.to_v1_report(self.from_v1_report(report), report)
