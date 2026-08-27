"""Run the Stage 3 catalog, generated-asset and reproducibility quality gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from smartbuy.data.derive import evidence_rows, source_rows
from smartbuy.data.loader import CATALOG_PATH, load_catalog, stable_json_hash
from smartbuy.data.quality import validate_catalog
from smartbuy.scripts.build_stage3_data import DEMO_MANIFEST, _normalized_text_sha256


def main() -> int:
    catalog = load_catalog()
    report = validate_catalog(catalog)
    manifest = json.loads(DEMO_MANIFEST.read_text(encoding="utf-8"))
    expected_logical_hash = stable_json_hash(
        {
            "products": catalog.products,
            "prices": catalog.price_observations,
            "sources": source_rows(catalog),
            "evidence": evidence_rows(catalog),
        }
    )
    generated_errors: list[str] = []
    if manifest["catalog_sha256"] != _normalized_text_sha256(CATALOG_PATH):
        generated_errors.append("catalog hash mismatch")
    if manifest["logical_data_sha256"] != expected_logical_hash:
        generated_errors.append("logical data hash mismatch")
    for item in manifest["fact_cards"]:
        path = Path(__file__).resolve().parents[2] / item["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            generated_errors.append(f"fact-card hash mismatch: {item['model_id']}")

    payload = {
        "status": "completed" if report.passed and not generated_errors else "failed",
        "metrics": report.metrics,
        "generated_asset_errors": generated_errors,
        "issues": [issue.__dict__ for issue in report.issues],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
