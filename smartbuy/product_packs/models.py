"""Strict, JSON-safe Product Pack and evidence-ledger contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from smartbuy.contracts import CONTRACT_VERSION


PRODUCT_PACK_SCHEMA_VERSION = "1.0.0"
EVIDENCE_LEDGER_SCHEMA_VERSION = "1.0.0"
NORMALIZER_VERSION = "proofpick-product-normalizer-v1"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PackCompatibility(FrozenModel):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    domain_pack_version: str
    embedding_model: Literal["text-embedding-v4"] = "text-embedding-v4"
    embedding_dimensions: Literal[1024] = 1024
    chunk_config_version: str


class PackLicense(FrozenModel):
    redistribution_status: Literal["redistributable", "metadata_and_summary_only"]
    data_license_note: str = Field(min_length=1, max_length=500)
    raw_content_included: Literal[False] = False


class ProductAttribute(FrozenModel):
    value: Any = None
    unit: str | None = None


class ProductInput(FrozenModel):
    product_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*-(?:[a-z]{2}|global)$")
    brand: str = Field(min_length=1, max_length=100)
    canonical_name: str = Field(min_length=1, max_length=200)
    market: str = Field(pattern=r"^(?:[A-Z]{2}|GLOBAL)$")
    variant_key: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    aliases: list[str] = Field(default_factory=list, max_length=30)
    attributes: dict[str, ProductAttribute]
    official_source_ids: list[str] = Field(min_length=1)
    status: Literal["active", "retired", "unknown"] = "active"

    @model_validator(mode="after")
    def validate_identity(self) -> ProductInput:
        suffix = self.product_id.rsplit("-", 1)[-1]
        if suffix != self.market.casefold():
            raise ValueError("product_id market suffix does not match market")
        normalized_aliases = [item.strip().casefold() for item in self.aliases]
        if any(not item for item in normalized_aliases) or len(normalized_aliases) != len(
            set(normalized_aliases)
        ):
            raise ValueError("product aliases must be non-empty and unique")
        return self


class SourceInput(FrozenModel):
    source_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    product_id: str
    source_type: Literal[
        "official_manual",
        "official_support",
        "official_product",
        "public_retail",
        "professional_review",
    ]
    title: str = Field(min_length=1, max_length=300)
    uri: HttpUrl
    publisher: str = Field(min_length=1, max_length=100)
    is_official: bool
    market: str = Field(pattern=r"^(?:[A-Z]{2}|GLOBAL)$")
    variant_key: str
    language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    source_version: str = Field(min_length=1, max_length=100)
    published_at: str | None = None
    accessed_at: str
    governed_summary: str = Field(min_length=1, max_length=1_000)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    redistribution_status: Literal["redistributable", "metadata_and_summary_only"]
    access_policy: Literal["public_no_login"]


class EvidenceInput(FrozenModel):
    evidence_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    source_id: str
    product_id: str
    field_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    raw_value: Any
    normalized_value: Any
    unit: str | None = None
    snippet: str = Field(min_length=1, max_length=500)
    evidence_location: str = Field(min_length=1, max_length=300)
    market: str = Field(pattern=r"^(?:[A-Z]{2}|GLOBAL)$")
    variant_key: str
    source_version: str = Field(min_length=1, max_length=100)
    effective_at: str | None = None
    observed_at: str
    confidence: Literal["high", "medium", "low"]
    conflict_group: str | None = None
    trust_state: Literal["governed"] = "governed"


class ObservationInput(FrozenModel):
    observation_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    product_id: str
    price_cny: float = Field(gt=0)
    seller: str = Field(min_length=1)
    market: str = Field(pattern=r"^(?:[A-Z]{2}|GLOBAL)$")
    stock_status: str = Field(min_length=1)
    uri: HttpUrl
    observed_at: str
    price_type: str = Field(min_length=1)
    source_id: str


class ProductPackDocument(FrozenModel):
    schema_version: Literal[PRODUCT_PACK_SCHEMA_VERSION] = PRODUCT_PACK_SCHEMA_VERSION
    pack_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    pack_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    domain_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    base_data_version: str
    data_version: str
    created_at: str
    compatibility: PackCompatibility
    license: PackLicense
    products: list[ProductInput] = Field(min_length=1)
    sources: list[SourceInput] = Field(min_length=1)
    evidence: list[EvidenceInput] = Field(min_length=1)
    observations: list[ObservationInput] = Field(default_factory=list)


class GovernedEvidenceRecord(FrozenModel):
    ledger_schema_version: Literal[EVIDENCE_LEDGER_SCHEMA_VERSION] = (
        EVIDENCE_LEDGER_SCHEMA_VERSION
    )
    evidence_id: str
    source_id: str
    product_id: str
    field_id: str
    raw_value: Any
    normalized_value: Any
    unit: str | None = None
    snippet: str = Field(min_length=1, max_length=1_000)
    evidence_location: str
    market: str = Field(pattern=r"^(?:[A-Z]{2}|GLOBAL)$")
    variant_key: str
    source_version: str
    effective_at: str | None = None
    observed_at: str
    confidence: Literal["high", "medium", "low"]
    conflict_group: str | None = None
    trust_state: Literal["governed"] = "governed"
    redistribution_status: Literal["redistributable", "metadata_and_summary_only"]
    source_uri: HttpUrl
    normalizer_version: str
    data_version: str
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    product_brand: str | None = None


class RequestEvidenceRecord(FrozenModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    evidence_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
    source_id: str
    product_id: str | None = None
    field_id: str
    raw_value: Any
    normalized_value: Any = None
    unit: str | None = None
    snippet: str = Field(min_length=1, max_length=500)
    source_uri: HttpUrl
    market: str = Field(pattern=r"^(?:[A-Z]{2}|GLOBAL)$")
    variant_key: str | None = None
    source_version: str
    observed_at: str
    trust_state: Literal["temporary"] = "temporary"
    promotion_status: Literal["not_reviewed"] = "not_reviewed"
    normalizer_version: Literal[NORMALIZER_VERSION] = NORMALIZER_VERSION
