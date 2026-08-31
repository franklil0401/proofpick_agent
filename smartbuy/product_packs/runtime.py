"""Default-off Product Pack runtime selection."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from smartbuy.data.loader import stable_json_hash
from smartbuy.product_packs.builder import ProductPackManager, PublishedProductSnapshot
from smartbuy.product_packs.live_index import ProductIndexManager, PublishedIndexSnapshot
from smartbuy.product_packs.loader import ProductPackValidationError


DEFAULT_PRODUCT_PACK_ROOT = Path("C:/ai/proofpick-v2/product-packs")


@dataclass(frozen=True)
class ResolvedProductSnapshot:
    data: PublishedProductSnapshot
    index: PublishedIndexSnapshot

    @property
    def data_version(self) -> str:
        return self.data.data_version

    @property
    def manifest_hash(self) -> str:
        return stable_json_hash(
            {
                "data_manifest_hash": self.data.manifest_hash,
                "index_manifest_hash": self.index.manifest_hash,
            }
        )

    @property
    def database_path(self) -> Path:
        return self.data.database_path

    @property
    def evidence_path(self) -> Path:
        return self.data.evidence_path

    @property
    def sources_path(self) -> Path:
        return self.data.sources_path

    @property
    def index_dir(self) -> Path:
        return self.index.chroma_path

    @property
    def collection_name(self) -> str:
        return self.index.collection_name


class ProductPackRuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    runtime_root: Path = DEFAULT_PRODUCT_PACK_ROOT

    @classmethod
    def from_environment(cls) -> ProductPackRuntimeSettings:
        raw = os.getenv("PROOFPICK_PRODUCT_PACK_ENABLED", "false").strip().casefold()
        if raw not in {"true", "false"}:
            raise ValueError("PROOFPICK_PRODUCT_PACK_ENABLED must be true or false")
        return cls(
            enabled=raw == "true",
            runtime_root=Path(
                os.getenv("PROOFPICK_PRODUCT_PACK_ROOT", str(DEFAULT_PRODUCT_PACK_ROOT))
            ),
        )


def resolve_product_snapshot(
    settings: ProductPackRuntimeSettings,
) -> ResolvedProductSnapshot | None:
    """Resolve only when explicitly enabled; disabled mode performs no filesystem access."""
    if not settings.enabled:
        return None
    data = ProductPackManager(settings.runtime_root).current()
    index = ProductIndexManager(settings.runtime_root).current()
    if index.data_version != data.data_version:
        raise ProductPackValidationError("current Product Pack data and index differ")
    return ResolvedProductSnapshot(data=data, index=index)
