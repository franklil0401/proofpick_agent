"""Strict public schemas for the V2 portfolio UI and redacted replay."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class PortfolioTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int = Field(ge=1)
    category: Literal[
        "Category Router",
        "Constraint Resolution",
        "Product Scope",
        "Product Query/Text2SQL",
        "KB Search",
        "Reranker",
        "Source Search",
        "Web Extractor",
        "Evidence Check",
        "Constraint Checker",
        "Decision Ranker",
        "Memory",
        "Report",
    ]
    status: Literal["success", "blocked", "degraded", "unavailable"]
    duration_ms: float = Field(ge=0)
    degraded: bool = False
    input_summary: str
    output_summary: str
    version: str


class PortfolioEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    field: str
    value: Any = None
    source_url: HttpUrl
    region: str
    configuration: str
    observed_at: str
    status: Literal["matched", "not_matched", "unknown", "conflict", "open"]


class PortfolioCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    label: str
    region: str
    configuration: str
    checker_status: Literal["eligible", "eliminated", "unknown", "conflict", "open_only"]
    reason: str
    rank: int | None = Field(default=None, ge=1)
    score: float | None = Field(default=None, ge=0, le=1)
    dimensions: list[dict[str, Any]] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)


class DynamicObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    region: str
    currency: str
    price: float | None = Field(default=None, ge=0)
    availability: str | None = None
    source_url: HttpUrl
    observed_at: str
    ttl_seconds: int = Field(gt=0)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expired: bool
    status: Literal["verified_observation", "unknown"]
    reason: str
    eligible_for_trusted_checker: bool = False
    saved_to_long_term_memory: bool = False


class PortfolioDemo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    demo_id: str
    title: str
    domain_id: Literal["monitor", "laptop", "headphone"]
    mode: Literal["trusted", "open"]
    query: str
    query_intent: str
    hard_constraints: list[str] = Field(default_factory=list)
    soft_preferences: list[str] = Field(default_factory=list)
    clarification: list[str] = Field(default_factory=list)
    constraint_sources: list[str] = Field(default_factory=list)
    complete_candidate_pool_size: int = Field(ge=0)
    candidates: list[PortfolioCandidate] = Field(default_factory=list)
    evidence: list[PortfolioEvidence] = Field(default_factory=list)
    trace: list[PortfolioTrace]
    degraded_states: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    stop_reason: str
    data_version: str
    index_version: str
    run_evidence: str
    real_run_command: str
    dynamic_observation: DynamicObservation | None = None
    memory_story: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_public_boundaries(self) -> "PortfolioDemo":
        if self.mode == "open" and any(
            item.checker_status == "eligible" for item in self.candidates
        ):
            raise ValueError("Open replay cannot expose Trusted eligibility")
        if self.dynamic_observation and self.dynamic_observation.eligible_for_trusted_checker:
            raise ValueError("portfolio dynamic observation cannot enter Trusted Checker")
        if [item.step for item in self.trace] != list(range(1, len(self.trace) + 1)):
            raise ValueError("trace steps must be consecutive")
        return self


class PortfolioDemoBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["proofpick-v2-portfolio-replay-v1"]
    disclosure: Literal["这是固定的脱敏结果回放，不是实时模型调用。"]
    generated_from: str
    demos: list[PortfolioDemo] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_demo_set(self) -> "PortfolioDemoBundle":
        identifiers = [item.demo_id for item in self.demos]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("demo identifiers must be unique")
        if {item.domain_id for item in self.demos} != {"monitor", "laptop", "headphone"}:
            raise ValueError("portfolio replay must cover all three domains")
        if {item.mode for item in self.demos} != {"trusted", "open"}:
            raise ValueError("portfolio replay must cover Trusted and Open modes")
        return self
