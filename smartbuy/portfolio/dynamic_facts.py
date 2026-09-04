"""Fail-closed assessment for bounded price/availability observations.

This module never searches the web.  It validates a supplied extractive
observation and makes its freshness explicit; observations are not product
specifications, long-term preferences, or Trusted Checker inputs.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from .models import DynamicObservation


def assess_dynamic_observation(
    record: dict[str, Any],
    *,
    as_of: datetime,
    ttl: timedelta = timedelta(hours=24),
) -> DynamicObservation:
    """Validate a governed observation and return an explicit current/unknown state."""

    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    url = str(record.get("url", ""))
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("dynamic observation requires a valid HTTP(S) source")
    currency = str(record.get("currency", "CNY")).upper()
    if currency != "CNY":
        raise ValueError("cross-currency comparison is not supported")
    observed_at = datetime.fromisoformat(
        str(record["observed_at"]).replace("Z", "+00:00")
    ).astimezone(UTC)
    expired = as_of.astimezone(UTC) > observed_at + ttl
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    content_hash = str(record.get("content_hash") or hashlib.sha256(canonical.encode()).hexdigest())
    price = record.get("price_cny")
    availability = record.get("stock_status")
    usable = not expired and (price is not None or availability is not None)
    return DynamicObservation(
        product_id=str(record["model_id"]),
        region=str(record["region"]),
        currency=currency,
        price=float(price) if usable and price is not None else None,
        availability=str(availability) if usable and availability is not None else None,
        source_url=url,
        observed_at=observed_at.isoformat().replace("+00:00", "Z"),
        ttl_seconds=int(ttl.total_seconds()),
        content_hash=content_hash,
        expired=expired,
        status="verified_observation" if usable else "unknown",
        reason="extractive_observation_within_ttl" if usable else "observation_expired",
    )
