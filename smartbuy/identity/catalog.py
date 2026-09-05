"""Map trusted legacy catalog rows to the shared product identity contract."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from .models import ResolvedProductScope
from .resolver import ProductIdentityResolver


def resolve_catalog_identity(
    query: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    domain_id: str = "monitor",
    data_version: str = "v1-catalog",
) -> ResolvedProductScope:
    """Use catalog-owned names/IDs; short model tokens never infer a region."""
    products: dict[str, dict[str, Any]] = {}
    for row in rows:
        source = dict(row)
        product_id = source.get("product_id") or source.get("model_id")
        model_name = source.get("model_name")
        region = source.get("region")
        if not product_id or not model_name or not region or product_id in products:
            raise ValueError("legacy catalog identity is missing or duplicated")
        aliases = set(source.get("aliases") or [])
        # A full catalog token is a model reference, not a prefix guess.
        # Shared names across regions remain a multi-product reference.
        aliases.update(
            token for token in re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", model_name)
            if len(token) >= 4 and re.search(r"[A-Za-z]", token) and re.search(r"\d", token)
        )
        products[product_id] = {
            **source,
            "product_id": product_id,
            "domain_id": domain_id,
            "model_name": model_name,
            "region": region,
            "aliases": sorted(aliases),
            "attributes": dict(source.get("attributes") or {}),
        }
    return ProductIdentityResolver(domain_id=domain_id, data_version=data_version).resolve(
        query, products
    )
