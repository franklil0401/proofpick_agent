"""Fail-closed identity and evidence-closure checks shared by domain tools."""

from __future__ import annotations

from typing import Any

from .models import ResolvedProductScope


class ProductIdentityMismatch(ValueError):
    """Raised when a tool attempts to widen or cross a deterministic scope."""


def product_identity(
    product: dict[str, Any],
    *,
    data_version: str,
    index_version: str | None = None,
) -> dict[str, Any]:
    attributes = product.get("attributes", {})
    return {
        "domain_id": product.get("domain_id"),
        "family_id": attributes.get("family_id"),
        "product_id": product.get("product_id"),
        "configuration_id": attributes.get("configuration_id"),
        "region": product.get("region"),
        "data_version": data_version,
        "index_version": index_version,
    }


def require_product_in_scope(
    product: dict[str, Any],
    scope: ResolvedProductScope,
    *,
    data_version: str,
    index_version: str | None = None,
) -> None:
    scope.assert_runtime(
        domain_id=str(product.get("domain_id")),
        data_version=data_version,
        index_version=index_version,
    )
    product_id = str(product.get("product_id"))
    if not scope.permits(product_id):
        raise ProductIdentityMismatch("product is outside the resolved candidate scope")
    identity = product_identity(product, data_version=data_version, index_version=index_version)
    if identity["configuration_id"] not in scope.configuration_ids:
        raise ProductIdentityMismatch("configuration identity is outside candidate scope")
    if identity["region"] not in scope.regions:
        raise ProductIdentityMismatch("region identity is outside candidate scope")


def evidence_identity_status(
    product: dict[str, Any],
    evidence: dict[str, Any],
    *,
    field: str,
) -> tuple[bool, str]:
    """Verify the complete governed evidence binding before exposing a fact."""
    if evidence.get("field_id") != field:
        return False, "field_mismatch"
    if not evidence.get("evidence_id") or not evidence.get("source_id"):
        return False, "source_untraceable"
    if evidence.get("region") != product.get("region"):
        return False, "region_mismatch_only"
    if evidence.get("variant_key") != product.get("variant_key"):
        return False, "identity_mismatch"
    return True, "identity_bound"
