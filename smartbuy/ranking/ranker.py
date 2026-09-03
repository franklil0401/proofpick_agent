"""Pure deterministic ranking over an immutable Checker-eligible set."""

from __future__ import annotations

import json
from typing import Any

from smartbuy.ranking.models import (
    DimensionScore,
    RankedCandidate,
    RankingCandidateInput,
    RankingExplanation,
    RankingRequest,
)
from smartbuy.ranking.profile import LoadedRankingProfile, RankingDimension


class RankingInvariantError(RuntimeError):
    pass


def _round(value: float) -> float:
    return round(value + 0.0, 8)


def stable_fallback(request: RankingRequest, reason: str) -> RankingExplanation:
    candidates = sorted(request.eligible_candidates, key=lambda item: item.product_id)
    ranked = [
        RankedCandidate(
            product_id=item.product_id,
            configuration_id=item.configuration_id,
            region=item.region,
            total_score=0.0,
            dimension_scores=[],
            dimension_contributions={},
            evidence_coverage=0.0,
            unknown_dimensions=[],
            advantages=[],
            tradeoffs=["排名配置不可用；保留 Checker 合规集合并使用稳定 ID 顺序。"],
            rank=index,
            rank_change=0,
            evidence_ids=[],
        )
        for index, item in enumerate(candidates, start=1)
    ]
    if set(item.product_id for item in ranked) != set(request.checker_eligible_ids):
        raise RankingInvariantError("fallback output differs from Checker eligibility")
    return RankingExplanation(
        active_scenario=request.scenario or "fallback",
        weight_source="fallback",
        effective_weights={},
        candidate_contributions=ranked,
        degraded_reasons=[reason],
        deterministic_tie_breaker="product_id_ascending",
        ranking_profile_version=request.ranking_profile_version,
        domain_pack_version=request.domain_pack_version,
        data_version=request.data_version,
        memory_enabled=request.memory_enabled,
        ranking_degraded=True,
    )


class DeterministicDecisionRanker:
    """Score evidence-backed dimensions; never decide candidate eligibility."""

    def __init__(self, profile: LoadedRankingProfile) -> None:
        self.profile = profile

    @staticmethod
    def _weights(
        dimensions: list[RankingDimension], overrides: dict[str, float]
    ) -> tuple[dict[str, float], str]:
        base = {item.dimension_id: item.weight for item in dimensions}
        if not overrides:
            return base, "domain_profile"
        unknown = set(overrides) - set(base)
        if unknown or any(isinstance(value, bool) or value < 0 or value > 1 for value in overrides.values()):
            raise RankingInvariantError("weight override is invalid")
        supplied = sum(overrides.values())
        untouched = [key for key in base if key not in overrides]
        if supplied > 1.0 + 1e-9 or (not untouched and abs(supplied - 1.0) > 1e-9):
            raise RankingInvariantError("weight override total is invalid")
        output = dict(overrides)
        remainder = max(0.0, 1.0 - supplied)
        base_remainder = sum(base[key] for key in untouched)
        if untouched and base_remainder <= 0:
            raise RankingInvariantError("weight override cannot allocate remaining weight")
        for key in untouched:
            output[key] = remainder * base[key] / base_remainder
        if abs(sum(output.values()) - 1.0) > 1e-9:
            raise RankingInvariantError("effective weights must sum to 1")
        return {key: _round(value) for key, value in output.items()}, "explicit_what_if"

    @staticmethod
    def _score(dimension: RankingDimension, value: Any) -> float | None:
        if value is None:
            return None
        if dimension.normalization == "fixed_range":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            assert dimension.fixed_range is not None
            lower, upper = dimension.fixed_range
            score = min(1.0, max(0.0, (float(value) - lower) / (upper - lower)))
        elif dimension.normalization == "boolean":
            if not isinstance(value, bool):
                return None
            score = 1.0 if value else 0.0
        else:
            score = dimension.enum_scores.get(str(value).casefold())
            if score is None:
                return None
        return _round(1.0 - score if dimension.direction == "minimize" else score)

    @staticmethod
    def _evidence(
        candidate: RankingCandidateInput, dimension: RankingDimension, value: Any
    ) -> tuple[list[str], list[str]]:
        rows = [
            item
            for item in candidate.evidence
            if item.field_id == dimension.source_field
            and item.region == candidate.region
            and item.source_type in dimension.allowed_source_types
            and item.normalized_value == value
        ]
        return (
            sorted({item.evidence_id for item in rows}),
            sorted({item.source_id for item in rows}),
        )

    def rank(self, request: RankingRequest) -> RankingExplanation:
        if request.domain_id == "" or request.ranking_profile_version != self.profile.profile.profile_version:
            raise RankingInvariantError("ranking request profile is incompatible")
        if request.domain_pack_version not in self.profile.profile.compatible_domain_pack_versions:
            raise RankingInvariantError("ranking request Domain Pack is incompatible")
        scenario_id = self.profile.select_scenario(
            request.scenario,
            request.explicit_preferences,
            request.confirmed_memory_preferences if request.memory_enabled else {},
        )
        scenario = self.profile.scenarios[scenario_id]
        weights, weight_source = self._weights(scenario.dimensions, request.weight_overrides)
        if request.weight_overrides:
            weight_source = request.weight_override_source
        original_positions = {
            candidate.product_id: index + 1
            for index, candidate in enumerate(request.eligible_candidates)
        }
        scored: list[tuple[RankingCandidateInput, float, list[DimensionScore]]] = []
        for candidate in request.eligible_candidates:
            dimensions: list[DimensionScore] = []
            total = 0.0
            for dimension in scenario.dimensions:
                value = candidate.values.get(dimension.source_field)
                evidence_ids, source_ids = self._evidence(candidate, dimension, value)
                score = self._score(dimension, value) if evidence_ids else None
                contribution = _round((score or 0.0) * weights[dimension.dimension_id])
                total += contribution
                dimensions.append(
                    DimensionScore(
                        dimension_id=dimension.dimension_id,
                        source_field=dimension.source_field,
                        actual_value=value if evidence_ids else None,
                        normalized_score=score,
                        weight=weights[dimension.dimension_id],
                        contribution=contribution,
                        evidence_ids=evidence_ids,
                        source_ids=source_ids,
                        status="scored" if score is not None else "unknown",
                        reason=(
                            dimension.explanation_template
                            if score is not None
                            else "缺少目标地区允许来源的字段证据；不加分，也不推断负面事实。"
                        ),
                    )
                )
            scored.append((candidate, _round(total), dimensions))
        scored.sort(key=lambda item: (-item[1], item[0].product_id))
        ranked: list[RankedCandidate] = []
        for rank, (candidate, total, dimensions) in enumerate(scored, start=1):
            known = [item for item in dimensions if item.status == "scored"]
            advantages = [
                f"{item.dimension_id} 贡献 {item.contribution:.4f}"
                for item in sorted(known, key=lambda item: (-item.contribution, item.dimension_id))[:2]
                if item.contribution > 0
            ]
            unknown = [item.dimension_id for item in dimensions if item.status == "unknown"]
            tradeoffs = (
                [f"{item} 缺少可比较证据，未参与正向评分" for item in unknown[:2]]
                or ["当前 Profile 下未发现需要额外披露的未知评分维度"]
            )
            evidence_ids = sorted({value for item in known for value in item.evidence_ids})
            ranked.append(
                RankedCandidate(
                    product_id=candidate.product_id,
                    configuration_id=candidate.configuration_id,
                    region=candidate.region,
                    total_score=total,
                    dimension_scores=dimensions,
                    dimension_contributions={item.dimension_id: item.contribution for item in dimensions},
                    evidence_coverage=_round(len(known) / len(dimensions)),
                    unknown_dimensions=unknown,
                    advantages=advantages,
                    tradeoffs=tradeoffs,
                    rank=rank,
                    rank_change=original_positions[candidate.product_id] - rank,
                    evidence_ids=evidence_ids,
                )
            )
        ranked_ids = [item.product_id for item in ranked]
        if set(ranked_ids) != set(request.checker_eligible_ids):
            raise RankingInvariantError("ranker output differs from Checker eligibility")
        explicit_keys = sorted(set(request.explicit_preferences) | set(request.weight_overrides))
        memory_keys = sorted(request.confirmed_memory_preferences) if request.memory_enabled else []
        known_preference_keys = {
            self.profile.profile.scenario_preference_key,
            *(item.dimension_id for item in scenario.dimensions),
        }
        ignored = sorted(
            (set(request.explicit_preferences) | set(memory_keys)) - known_preference_keys
        )
        return RankingExplanation(
            active_scenario=scenario_id,
            weight_source=weight_source,
            effective_weights=weights,
            explicit_input_effects=explicit_keys,
            memory_effects=[
                f"{key}:{request.memory_preference_sources.get(key, 'confirmed_memory')}"
                for key in memory_keys
            ],
            candidate_contributions=ranked,
            ignored_preferences=ignored,
            deterministic_tie_breaker=self.profile.profile.deterministic_tie_breaker,
            ranking_profile_version=self.profile.profile.profile_version,
            domain_pack_version=request.domain_pack_version,
            data_version=request.data_version,
            memory_enabled=request.memory_enabled,
        )

    def fallback(self, request: RankingRequest, reason: str) -> RankingExplanation:
        return stable_fallback(request, reason)

    @staticmethod
    def canonical_bytes(explanation: RankingExplanation) -> bytes:
        return json.dumps(
            explanation.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
