"""Domain-neutral product identity and immutable candidate-scope contracts."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


IDENTITY_CONTRACT_VERSION = "proofpick-product-identity-v1"


class ProductScopeType(StrEnum):
    EXACT_CONFIGURATION = "exact_configuration"
    PRODUCT_FAMILY = "product_family"
    EXPLICIT_COMPARISON = "explicit_comparison"
    CATALOG_FILTER = "catalog_filter"
    OPEN_UNKNOWN_PRODUCT = "open_unknown_product"
    AMBIGUOUS_PRODUCT_SCOPE = "ambiguous_product_scope"


class ProductScopeResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    NEEDS_CLARIFICATION = "needs_clarification"
    OPEN_REQUIRED = "open_required"


class ProductMention(BaseModel):
    """An exact slice of user text associated with registry-owned identity data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quote: str = Field(min_length=1, max_length=300)
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    identity_kind: str
    canonical_value: str
    product_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_span(self) -> ProductMention:
        if self.span_end <= self.span_start:
            raise ValueError("identity mention span is invalid")
        return self


class ResolvedProductScope(BaseModel):
    """System-owned upper bound that no tool, model or report may expand."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: str = IDENTITY_CONTRACT_VERSION
    domain_id: str
    scope_type: ProductScopeType
    mentioned_quotes: list[str] = Field(default_factory=list)
    mentions: list[ProductMention] = Field(default_factory=list)
    family_ids: list[str] = Field(default_factory=list)
    product_ids: list[str] = Field(default_factory=list)
    configuration_ids: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    explicit_comparison: bool = False
    clarification_required: bool = False
    resolution_status: ProductScopeResolutionStatus
    resolution_reason: str
    data_version: str
    index_version: str | None = None
    owner: str = "deterministic"

    @model_validator(mode="after")
    def validate_scope(self) -> ResolvedProductScope:
        for values in (
            self.mentioned_quotes,
            self.family_ids,
            self.product_ids,
            self.configuration_ids,
            self.regions,
        ):
            if len(values) != len(set(values)):
                raise ValueError("candidate scope values must be unique")
        exact_quotes = list(dict.fromkeys(item.quote for item in self.mentions))
        if self.mentioned_quotes != exact_quotes:
            raise ValueError("mentioned quote list must mirror exact mention slices")
        if self.clarification_required != (
            self.resolution_status == ProductScopeResolutionStatus.NEEDS_CLARIFICATION
        ):
            raise ValueError("clarification state and resolution status differ")
        if self.scope_type == ProductScopeType.OPEN_UNKNOWN_PRODUCT and self.product_ids:
            raise ValueError("unknown product scope cannot grant local product identity")
        if self.resolution_status == ProductScopeResolutionStatus.RESOLVED and not self.product_ids:
            raise ValueError("resolved scope must contain at least one product")
        if self.scope_type == ProductScopeType.EXACT_CONFIGURATION and len(self.product_ids) != 1:
            raise ValueError("exact configuration scope must contain exactly one product")
        return self

    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"mentions", "mentioned_quotes"})
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def permits(self, product_id: str) -> bool:
        return (
            self.resolution_status == ProductScopeResolutionStatus.RESOLVED
            and product_id in self.product_ids
        )

    def assert_runtime(
        self,
        *,
        domain_id: str,
        data_version: str,
        index_version: str | None = None,
    ) -> None:
        if self.domain_id != domain_id or self.data_version != data_version:
            raise ValueError("candidate scope runtime identity mismatch")
        if (
            index_version is not None
            and self.index_version is not None
            and self.index_version != index_version
        ):
            raise ValueError("candidate scope index identity mismatch")
