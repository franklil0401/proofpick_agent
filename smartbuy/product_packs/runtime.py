"""Default-off Product Pack runtime selection."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from smartbuy.product_packs.builder import ProductPackManager, PublishedProductSnapshot
from smartbuy.product_packs.loader import ProductPackValidationError


DEFAULT_PRODUCT_PACK_ROOT = Path("C:/ai/proofpick-v2/product-packs")


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
) -> PublishedProductSnapshot | None:
    """Resolve only when explicitly enabled; disabled mode performs no filesystem access."""
    if not settings.enabled:
        return None
    snapshot = ProductPackManager(settings.runtime_root).current()
    if snapshot.manifest["index"]["status"] != "completed":
        raise ProductPackValidationError(
            "published Product Pack index is not completed"
        )
    return snapshot
