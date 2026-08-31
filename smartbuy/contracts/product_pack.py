"""Read-only Product Pack interface boundary; importing is intentionally deferred."""

from __future__ import annotations

from typing import Iterable, Protocol

from smartbuy.contracts.models import EvidenceRecord, Product, ProductPack, SourceRecord


class ProductPackReader(Protocol):
    @property
    def descriptor(self) -> ProductPack: ...

    def products(self) -> Iterable[Product]: ...

    def sources(self) -> Iterable[SourceRecord]: ...

    def evidence(self) -> Iterable[EvidenceRecord]: ...
