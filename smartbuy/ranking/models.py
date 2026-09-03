"""Domain-neutral, immutable contracts for deterministic V2 ranking."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenRankingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RankingEvidence(FrozenRankingModel):
    evidence_id: str
    source_id: str
    source_type: str
    field_id: str
    normalized_value: Any = None
    region: str


class RankingCandidateInput(FrozenRankingModel):
    product_id: str
    configuration_id: str | None = None
    region: str
    values: dict[str, Any]
    evidence: list[RankingEvidence] = Field(default_factory=list)


class RankingRequest(FrozenRankingModel):
    domain_id: str
    scenario: str | None = None
    eligible_candidates: list[RankingCandidateInput]
    checker_eligible_ids: list[str]
    explicit_preferences: dict[str, Any] = Field(default_factory=dict)
    confirmed_memory_preferences: dict[str, Any] = Field(default_factory=dict)
    memory_preference_sources: dict[str, str] = Field(default_factory=dict)
    weight_overrides: dict[str, float] = Field(default_factory=dict)
    weight_override_source: Literal["explicit", "category_memory", "global_memory"] = "explicit"
    ranking_profile_version: str
    data_version: str
    domain_pack_version: str
    memory_enabled: bool = False
    what_if: bool = False

    @model_validator(mode="after")
    def enforce_checker_subset(self) -> RankingRequest:
        candidate_ids = [item.product_id for item in self.eligible_candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("ranking candidates must be unique")
        if not set(candidate_ids) <= set(self.checker_eligible_ids):
            raise ValueError("ranker input exceeds Checker eligibility")
        if not set(self.memory_preference_sources) <= set(
            self.confirmed_memory_preferences
        ):
            raise ValueError("memory source metadata has no matching preference")
        return self


class DimensionScore(FrozenRankingModel):
    dimension_id: str
    source_field: str
    actual_value: Any = None
    normalized_score: float | None = Field(default=None, ge=0.0, le=1.0)
    weight: float = Field(ge=0.0, le=1.0)
    contribution: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    status: Literal["scored", "unknown"]
    reason: str


class RankedCandidate(FrozenRankingModel):
    product_id: str
    configuration_id: str | None = None
    region: str
    total_score: float = Field(ge=0.0, le=1.0)
    dimension_scores: list[DimensionScore]
    dimension_contributions: dict[str, float]
    evidence_coverage: float = Field(ge=0.0, le=1.0)
    unknown_dimensions: list[str] = Field(default_factory=list)
    advantages: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    rank: int = Field(ge=1)
    rank_change: int = 0
    evidence_ids: list[str] = Field(default_factory=list)


class RankingExplanation(FrozenRankingModel):
    active_scenario: str
    weight_source: str
    effective_weights: dict[str, float]
    explicit_input_effects: list[str] = Field(default_factory=list)
    memory_effects: list[str] = Field(default_factory=list)
    candidate_contributions: list[RankedCandidate]
    ignored_preferences: list[str] = Field(default_factory=list)
    degraded_reasons: list[str] = Field(default_factory=list)
    deterministic_tie_breaker: str
    ranking_profile_version: str
    domain_pack_version: str
    data_version: str
    memory_enabled: bool = False
    ranking_degraded: bool = False
    score_disclaimer: str = (
        "该分数用于当前用途和偏好下的相对排序，不代表商品的绝对质量。"
    )

    @property
    def ranked_ids(self) -> list[str]:
        return [item.product_id for item in self.candidate_contributions]
