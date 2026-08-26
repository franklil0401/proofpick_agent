"""Load the Stage 3 canonical catalog without mutating source data."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).with_name("catalog") / "monitors_v1.json"


@dataclass(frozen=True)
class Catalog:
    schema_version: str
    data_version: str
    products: tuple[dict[str, Any], ...]
    price_observations: tuple[dict[str, Any], ...]
    source_records: tuple[dict[str, Any], ...]
    conflict_evidence: tuple[dict[str, Any], ...]

    def source_hash(self, source: dict[str, Any]) -> str:
        """Hash the governed source capture, not mutable remote response bytes."""
        capture = {
            "source_id": source["source_id"],
            "url": source["url"],
            "accessed_at": source["accessed_at"],
            "governed_summary": source["governed_summary"],
        }
        canonical = json.dumps(capture, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_catalog(path: Path | str = CATALOG_PATH) -> Catalog:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return Catalog(
        schema_version=payload["schema_version"],
        data_version=payload["data_version"],
        products=tuple(payload["products"]),
        price_observations=tuple(payload["price_observations"]),
        source_records=tuple(payload["source_records"]),
        conflict_evidence=tuple(payload.get("conflict_evidence", [])),
    )


def stable_json_hash(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
