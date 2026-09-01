"""Provider interface for source discovery implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from smartbuy.source_search.models import SourceSearchRequest, SourceSearchResult


class SourceSearchProvider(ABC):
    @abstractmethod
    async def search(self, request: SourceSearchRequest) -> SourceSearchResult:
        """Discover source metadata without extracting or promoting page content."""

    async def aclose(self) -> None:
        """Close provider-owned resources when applicable."""
