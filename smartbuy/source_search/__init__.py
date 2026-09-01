"""Auditable V2 Source Search contracts and safety boundaries."""

from .cache import SourceSearchCachePolicy, TTLSourceSearchCache
from .models import (
    SourceCandidate,
    SourceCandidateStatus,
    SourceEngineOutcome,
    SourceIsolationError,
    SourceSearchAttempt,
    SourceSearchCacheStatus,
    SourceSearchRequest,
    SourceSearchResult,
    SourceSearchStatus,
    SourceSearchTriggerReason,
    SourceValidationStats,
    assert_source_candidates_isolated,
)
from .provider import SourceSearchProvider
from .settings import DEFAULT_OFFICIAL_DOMAINS, SourceSearchSettings
from .validator import (
    DeterministicSourceValidator,
    hostname_allowed,
    infer_region,
    model_matches_url,
    normalize_hostname,
    normalize_url,
)

__all__ = [
    "DEFAULT_OFFICIAL_DOMAINS",
    "DeterministicSourceValidator",
    "SourceCandidate",
    "SourceCandidateStatus",
    "SourceEngineOutcome",
    "SourceIsolationError",
    "SourceSearchAttempt",
    "SourceSearchCachePolicy",
    "SourceSearchCacheStatus",
    "SourceSearchProvider",
    "SourceSearchRequest",
    "SourceSearchResult",
    "SourceSearchSettings",
    "SourceSearchStatus",
    "SourceSearchTriggerReason",
    "SourceValidationStats",
    "TTLSourceSearchCache",
    "assert_source_candidates_isolated",
    "hostname_allowed",
    "infer_region",
    "model_matches_url",
    "normalize_hostname",
    "normalize_url",
]
