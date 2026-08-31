"""Field-level governed ledger plus an external request-scoped temporary area."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from smartbuy.product_packs.models import (
    EVIDENCE_LEDGER_SCHEMA_VERSION,
    NORMALIZER_VERSION,
    GovernedEvidenceRecord,
    RequestEvidenceRecord,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def evidence_content_hash(record: dict[str, Any]) -> str:
    semantic = {
        "source_id": record["source_id"],
        "product_id": record["product_id"],
        "field_id": record["field_id"],
        "normalized_value": record["normalized_value"],
        "snippet": record["snippet"],
        "market": record["market"],
        "variant_key": record["variant_key"],
        "source_version": record["source_version"],
        "observed_at": record["observed_at"],
    }
    return hashlib.sha256(_canonical(semantic).encode("utf-8")).hexdigest()


def governed_ledger_rows(
    *,
    base_evidence: Iterable[dict[str, Any]],
    base_sources: dict[str, dict[str, Any]],
    base_products: dict[str, dict[str, Any]],
    pack_evidence: Iterable[dict[str, Any]],
    pack_sources: dict[str, dict[str, Any]],
    data_version: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in base_evidence:
        source = base_sources[item["source_id"]]
        product = base_products[item["model_id"]]
        row = {
            "ledger_schema_version": EVIDENCE_LEDGER_SCHEMA_VERSION,
            "evidence_id": item["evidence_id"],
            "source_id": item["source_id"],
            "product_id": item["model_id"],
            "field_id": item["normalized_field"],
            "raw_value": item["original_value"],
            "normalized_value": item["normalized_value"],
            "unit": None,
            "snippet": item["evidence_location"],
            "evidence_location": item["evidence_location"],
            "market": source["region"],
            "variant_key": f"{item['model_id']}-v1",
            "source_version": "v1-governed-capture",
            "effective_at": item["effective_time"],
            "observed_at": f"{source['accessed_at']}T00:00:00Z"
            if len(source["accessed_at"]) == 10
            else source["accessed_at"],
            "confidence": item["confidence_level"],
            "conflict_group": item["conflict_group"],
            "trust_state": "governed",
            "redistribution_status": source["redistribution_status"],
            "source_uri": source["url"],
            "normalizer_version": "v1-adapter",
            "data_version": data_version,
            "product_brand": product["brand"],
        }
        row["content_hash"] = evidence_content_hash(row)
        rows.append(GovernedEvidenceRecord.model_validate(row).model_dump(mode="json"))
    for item in pack_evidence:
        source = pack_sources[item["source_id"]]
        row = {
            "ledger_schema_version": EVIDENCE_LEDGER_SCHEMA_VERSION,
            **item,
            "redistribution_status": source["redistribution_status"],
            "source_uri": str(source["uri"]),
            "normalizer_version": NORMALIZER_VERSION,
            "data_version": data_version,
        }
        row["content_hash"] = evidence_content_hash(row)
        rows.append(GovernedEvidenceRecord.model_validate(row).model_dump(mode="json"))
    return sorted(rows, key=lambda item: item["evidence_id"])


class RequestEvidenceWorkspace:
    """External, non-promoting temporary ledger for one request at a time."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        try:
            self.root.relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("temporary evidence must stay outside the Git workspace")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, request_id: str) -> Path:
        if (
            not request_id
            or len(request_id) > 64
            or any(
                character
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                for character in request_id
            )
        ):
            raise ValueError("invalid request_id")
        return self.root / f"{request_id}.jsonl"

    def append(self, record: RequestEvidenceRecord) -> None:
        path = self._path(record.request_id)
        existing = self.read(record.request_id)
        if any(item.evidence_id == record.evidence_id for item in existing):
            raise ValueError("duplicate temporary evidence_id")
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def read(self, request_id: str) -> list[RequestEvidenceRecord]:
        path = self._path(request_id)
        if not path.exists():
            return []
        return [
            RequestEvidenceRecord.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def clear(self, request_id: str) -> bool:
        path = self._path(request_id)
        if not path.exists():
            return False
        path.unlink()
        return True
