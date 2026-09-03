"""Load and validate pack-owned ranking profiles without category constants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from smartbuy.domain_packs.loader import LoadedDomainPack


class RankingProfileError(ValueError):
    """Safe public error for invalid or incompatible ranking policy."""


class RankingDimension(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension_id: str
    source_field: str
    direction: Literal["maximize", "minimize"]
    normalization: Literal["fixed_range", "enum", "boolean"]
    fixed_range: tuple[float, float] | None = None
    enum_scores: dict[str, float] = Field(default_factory=dict)
    weight: float = Field(ge=0.0, le=1.0)
    evidence_requirement: Literal["required"] = "required"
    allowed_source_types: list[str]
    missing_value_policy: Literal["zero_no_assumption"] = "zero_no_assumption"
    explanation_template: str

    @model_validator(mode="after")
    def validate_normalization(self) -> RankingDimension:
        if self.normalization == "fixed_range":
            if self.fixed_range is None or self.fixed_range[0] >= self.fixed_range[1]:
                raise ValueError("fixed_range normalization requires increasing bounds")
            if self.enum_scores:
                raise ValueError("fixed_range dimension cannot define enum scores")
        elif self.normalization == "enum":
            if not self.enum_scores or any(not 0.0 <= value <= 1.0 for value in self.enum_scores.values()):
                raise ValueError("enum normalization requires scores in [0,1]")
            if self.fixed_range is not None:
                raise ValueError("enum dimension cannot define fixed range")
        elif self.fixed_range is not None or self.enum_scores:
            raise ValueError("boolean dimension cannot define range or enum scores")
        if not self.allowed_source_types:
            raise ValueError("ranking dimension must declare evidence source types")
        return self


class ScenarioProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    dimensions: list[RankingDimension]

    @model_validator(mode="after")
    def validate_dimensions(self) -> ScenarioProfile:
        ids = [item.dimension_id for item in self.dimensions]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("scenario dimension ids must be non-empty and unique")
        if abs(sum(item.weight for item in self.dimensions) - 1.0) > 1e-9:
            raise ValueError("scenario weights must sum to 1")
        return self


class RankingProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_version: str
    compatible_domain_pack_versions: list[str]
    default_scenario: str
    scenario_preference_key: str
    scenario_aliases: dict[str, str] = Field(default_factory=dict)
    deterministic_tie_breaker: Literal["product_id_ascending"]
    scenarios: list[ScenarioProfile]

    @model_validator(mode="after")
    def validate_scenarios(self) -> RankingProfile:
        ids = [item.scenario_id for item in self.scenarios]
        if len(ids) != len(set(ids)) or self.default_scenario not in ids:
            raise ValueError("ranking scenarios are duplicate or default is missing")
        if not set(self.scenario_aliases.values()) <= set(ids):
            raise ValueError("scenario alias references unknown scenario")
        return self


@dataclass(frozen=True)
class LoadedRankingProfile:
    profile: RankingProfile
    scenarios: dict[str, ScenarioProfile]

    def select_scenario(
        self,
        requested: str | None,
        explicit_preferences: dict[str, Any],
        memory_preferences: dict[str, Any],
    ) -> str:
        value: Any = requested
        if value is None:
            value = explicit_preferences.get(self.profile.scenario_preference_key)
        if value is None:
            value = memory_preferences.get(self.profile.scenario_preference_key)
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, str):
            folded = value.strip().casefold()
            mapped = self.profile.scenario_aliases.get(folded, folded)
            if mapped in self.scenarios:
                return mapped
        return self.profile.default_scenario


class RankingProfileLoader:
    """Validate profile fields, source permissions and pack compatibility."""

    @staticmethod
    def load(pack: LoadedDomainPack) -> LoadedRankingProfile:
        try:
            raw = pack.pack.policies["ranking"]["profile"]
            profile = RankingProfile.model_validate(raw)
        except Exception as exc:
            raise RankingProfileError("ranking profile is invalid") from exc
        if pack.version not in profile.compatible_domain_pack_versions:
            raise RankingProfileError("ranking profile is incompatible with Domain Pack")
        source_types = set(pack.pack.policies["source_priority"])
        field_permissions = pack.pack.policies["product_pack"].get(
            "source_field_permissions", {}
        )
        for scenario in profile.scenarios:
            for dimension in scenario.dimensions:
                definition = pack.fields.get(dimension.source_field)
                if definition is None:
                    raise RankingProfileError("ranking profile references an unknown field")
                if not set(dimension.allowed_source_types) <= source_types:
                    raise RankingProfileError("ranking profile references an unknown source type")
                if field_permissions:
                    for source_type in dimension.allowed_source_types:
                        if dimension.source_field not in field_permissions.get(source_type, []):
                            raise RankingProfileError("ranking evidence source is not permitted for field")
                if dimension.normalization == "fixed_range" and definition.data_type.value not in {
                    "number", "integer"
                }:
                    raise RankingProfileError("numeric ranking requires a numeric field")
                if dimension.normalization == "boolean" and definition.data_type.value != "boolean":
                    raise RankingProfileError("boolean ranking requires a boolean field")
        return LoadedRankingProfile(
            profile=profile,
            scenarios={item.scenario_id: item for item in profile.scenarios},
        )

