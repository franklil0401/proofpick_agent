"""Generate all public Stage 3 derived data from one canonical catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from smartbuy.data.derive import evidence_rows, fact_card, jsonl, source_rows
from smartbuy.data.loader import CATALOG_PATH, load_catalog, stable_json_hash
from smartbuy.data.quality import validate_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "smartbuy" / "data" / "processed"
FACT_CARD_DIR = PROJECT_ROOT / "smartbuy" / "data" / "demo" / "fact_cards"
DEMO_MANIFEST = PROJECT_ROOT / "smartbuy" / "data" / "demo" / "manifest.json"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _normalized_text_sha256(path: Path) -> str:
    """Keep the catalog hash stable across Git LF/CRLF checkout policies."""

    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_assets(catalog_path: Path = CATALOG_PATH) -> dict[str, object]:
    catalog = load_catalog(catalog_path)
    quality = validate_catalog(catalog)
    if not quality.passed:
        details = "; ".join(f"{item.check}:{item.record_id}" for item in quality.errors)
        raise RuntimeError(f"catalog quality gate failed: {details}")

    sources = source_rows(catalog)
    evidence = evidence_rows(catalog)
    _write(PROCESSED_DIR / "products.jsonl", jsonl(catalog.products))
    _write(PROCESSED_DIR / "price_observations.jsonl", jsonl(catalog.price_observations))
    _write(PROCESSED_DIR / "source_records.jsonl", jsonl(sources))
    _write(PROCESSED_DIR / "evidence_records.jsonl", jsonl(evidence))

    sources_by_model: dict[str, list[dict[str, object]]] = {}
    for source in catalog.source_records:
        sources_by_model.setdefault(source["model_id"], []).append(source)
    prices_by_model = {item["model_id"]: item for item in catalog.price_observations}
    cards: list[dict[str, str]] = []
    for product in catalog.products:
        path = FACT_CARD_DIR / f"{product['model_id']}.md"
        _write(path, fact_card(product, sources_by_model[product["model_id"]], prices_by_model.get(product["model_id"])))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        cards.append({"model_id": product["model_id"], "path": path.relative_to(PROJECT_ROOT).as_posix(), "sha256": digest})

    manifest = {
        "schema_version": catalog.schema_version,
        "data_version": catalog.data_version,
        "catalog_sha256": _normalized_text_sha256(catalog_path),
        "logical_data_sha256": stable_json_hash(
            {
                "products": catalog.products,
                "prices": catalog.price_observations,
                "sources": sources,
                "evidence": evidence,
            }
        ),
        "counts": {
            "products": len(catalog.products),
            "brands": len({item["brand"] for item in catalog.products}),
            "sources": len(sources),
            "prices": len(catalog.price_observations),
            "evidence": len(evidence),
            "fact_cards": len(cards),
        },
        "fact_cards": cards,
        "quality": quality.metrics,
    }
    _write(DEMO_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    args = parser.parse_args()
    manifest = build_assets(args.catalog)
    print(json.dumps({"status": "completed", "counts": manifest["counts"], "quality": manifest["quality"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
