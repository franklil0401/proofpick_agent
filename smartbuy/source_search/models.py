"""Versioned contracts for auditable source discovery without evidence promotion."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceCandidateStatus(StrEnum):
    REGION_MATCHED = "region_matched"
    REGION_MISMATCH = "region_mismatch"
    REGION_UNKNOWN = "region_unknown"
    MODEL_MISMATCH = "model_mismatch"
    DOMAIN_REJECTED = "domain_rejected"
    INVALID_URL = "invalid_url"


class SourceSearchStatus(StrEnum):
    SUCCESS = "success"
    NO_REGION_MATCHED_SOURCE = "no_region_matched_source"
    NO_OFFICIAL_SOURCE = "no_official_source"
    PROVIDER_ERROR = "provider_error"
    DISABLED = "disabled"


class SourceSearchTriggerReason(StrEnum):
    EXPLICIT_USER_REQUEST = "explicit_user_request"
    OUT_OF_CATALOG_MODEL = "out_of_catalog_model"
    MISSING_LOCAL_EVIDENCE = "missing_local_evidence"
    DYNAMIC_INFORMATION = "dynamic_information"


class SourceSearchCacheStatus(StrEnum):
    HIT = "hit"
    MISS = "miss"
    MIXED = "mixed"
    BYPASS = "bypass"


class SourceIsolationError(RuntimeError):
    """Raised when discovery-only metadata is offered to Evidence or Checker."""


class SourceSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=200)
    product_category: str = Field(min_length=1, max_length=64)
    target_model: str = Field(min_length=1, max_length=100)
    target_fields: list[str] = Field(min_length=1, max_length=20)
    region: str = Field(pattern=r"^[A-Z]{2}$")
    freshness: Literal["oneDay", "oneWeek", "oneMonth", "oneYear", "noLimit"] = "noLimit"
    allowed_domains: list[str] = Field(min_length=1, max_length=10)
    max_results: int = Field(default=10, ge=1, le=10)
    trigger_reason: SourceSearchTriggerReason

    @field_validator("target_fields", "allowed_domains")
    @classmethod
    def unique_nonempty(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            item = value.strip().lower().rstrip(".")
            if not item:
                raise ValueError("list values must not be empty")
            if item not in normalized:
                normalized.append(item)
        return normalized


class SourceCandidate(BaseModel):
    """URL metadata only; even matched candidates are not field evidence in V2-3."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str | None = Field(default=None, max_length=500)
    url: str = Field(max_length=2_048)
    hostname: str | None = Field(default=None, max_length=253)
    site_name: str | None = Field(default=None, max_length=300)
    date_published: str | None = Field(default=None, max_length=100)
    queried_at: str
    local_request_id: str = Field(min_length=6, max_length=64)
    provider_request_id: str | None = Field(default=None, max_length=128)
    provider: str
    engine: str
    target_model: str
    target_region: str
    observed_region: str
    status: SourceCandidateStatus
    model_match_source: Literal["url", "title"] | None = None
    usable_for_evidence: Literal[False] = False
    usable_for_checker: Literal[False] = False

    def to_evidence_record(self) -> None:
        raise SourceIsolationError(
            "Source Candidate has no extracted field evidence and cannot become EvidenceRecord"
        )

    def to_checker_input(self) -> None:
        raise SourceIsolationError(
            "Source Candidate is not a catalog candidate and cannot enter Constraint Checker"
        )


class SourceValidationStats(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_result_count: int = Field(ge=0)
    scanned_result_count: int = Field(ge=0, le=50)
    valid_url_count: int = Field(ge=0)
    domain_matched_count: int = Field(ge=0)
    model_matched_count: int = Field(ge=0)
    region_matched_count: int = Field(ge=0)
    required_metadata_count: int = Field(ge=0)
    site_name_missing_count: int = Field(ge=0)
    date_published_missing_count: int = Field(ge=0)
    metadata_incomplete_count: int = Field(ge=0)


class SourceEngineOutcome(BaseModel):
    """One engine call after deterministic filtering; safe for bounded TTL caching."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    provider_version: str
    engine: str
    query_strategy: str = "original"
    query_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    requested_count: int = Field(ge=1, le=10)
    requested_at: str
    local_request_id: str
    provider_request_id: str | None = None
    http_status: int | None = None
    attempts: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0)
    network_executed: bool = False
    cache_status: SourceSearchCacheStatus = SourceSearchCacheStatus.MISS
    estimated_cost_cny: float = Field(default=0.0, ge=0)
    usable_candidates: list[SourceCandidate] = Field(default_factory=list, max_length=10)
    navigation_candidates: list[SourceCandidate] = Field(default_factory=list, max_length=10)
    rejected_candidates: list[SourceCandidate] = Field(default_factory=list, max_length=10)
    stats: SourceValidationStats
    error: str | None = None

    @property
    def complete_and_cacheable(self) -> bool:
        return (
            self.error is None
            and self.stats.raw_result_count > 0
            and bool(self.usable_candidates or self.navigation_candidates)
        )


class SourceSearchAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    engine: str
    query_strategy: str = "original"
    query_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    requested_count: int
    raw_result_count: int
    scanned_result_count: int
    usable_result_count: int
    navigation_result_count: int
    rejected_result_count: int
    requested_at: str
    latency_ms: float
    local_request_id: str
    provider_request_id: str | None = None
    attempts: int
    retries: int
    network_executed: bool
    cache_status: SourceSearchCacheStatus
    estimated_cost_cny: float
    http_status: int | None = None
    error: str | None = None


class SourceSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    provider_version: str
    engine: str
    status: SourceSearchStatus
    search_executed: bool
    network_executed: bool
    requested_count: int
    raw_result_count: int
    scanned_result_count: int
    usable_result_count: int
    usable_candidates: list[SourceCandidate] = Field(default_factory=list, max_length=10)
    navigation_candidates: list[SourceCandidate] = Field(default_factory=list, max_length=10)
    rejected_candidates: list[SourceCandidate] = Field(default_factory=list, max_length=10)
    attempts: list[SourceSearchAttempt] = Field(default_factory=list, max_length=2)
    requested_at: str
    latency_ms: float = Field(ge=0)
    request_id: str
    retries: int = Field(ge=0)
    cache_status: SourceSearchCacheStatus
    degraded: bool
    error: str | None = None
    estimated_cost_cny: float = Field(ge=0)
    trigger_reason: SourceSearchTriggerReason

    @model_validator(mode="after")
    def enforce_candidate_boundaries(self) -> SourceSearchResult:
        if any(item.status != SourceCandidateStatus.REGION_MATCHED for item in self.usable_candidates):
            raise ValueError("usable_candidates may contain only region_matched items")
        navigation_statuses = {
            SourceCandidateStatus.REGION_MISMATCH,
            SourceCandidateStatus.REGION_UNKNOWN,
        }
        if any(item.status not in navigation_statuses for item in self.navigation_candidates):
            raise ValueError("navigation_candidates may contain only region mismatch/unknown items")
        rejected_statuses = {
            SourceCandidateStatus.MODEL_MISMATCH,
            SourceCandidateStatus.DOMAIN_REJECTED,
            SourceCandidateStatus.INVALID_URL,
        }
        if any(item.status not in rejected_statuses for item in self.rejected_candidates):
            raise ValueError("rejected_candidates contains a non-rejected status")
        if any(item.usable_for_evidence or item.usable_for_checker for item in (
            *self.usable_candidates,
            *self.navigation_candidates,
            *self.rejected_candidates,
        )):
            raise ValueError("Source Candidates must remain isolated from Evidence and Checker")
        if self.usable_result_count != len(self.usable_candidates):
            raise ValueError("usable_result_count does not match candidates")
        return self


def assert_source_candidates_isolated(candidates: list[SourceCandidate]) -> None:
    if candidates:
        raise SourceIsolationError(
            "Source Candidate collections cannot be passed to Evidence Ledger or Constraint Checker"
        )
