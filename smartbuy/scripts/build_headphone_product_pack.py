"""Build the deterministic Headphone Product Pack from governed compact input."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from smartbuy.domain_packs import DomainPackLoader
from smartbuy.product_packs.loader import source_content_hash


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "smartbuy" / "data" / "headphone" / "headphone_configurations_v1.json"
DEFAULT_DOMAIN = ROOT / "smartbuy" / "domain_packs" / "headphone"
DEFAULT_OUTPUT = ROOT / "smartbuy" / "product_packs" / "examples" / "headphone-v1" / "pack.json"


def _source_record(
    row: dict[str, Any], source: dict[str, Any], accessed_at: str
) -> dict[str, Any]:
    product_id = row["product_id"]
    tier = source["tier"]
    source_id = f"src-{product_id}-{tier}"
    version = f"{tier}-capture-{accessed_at[:10]}"
    payload = {
        "source_id": source_id,
        "product_id": product_id,
        "source_type": source["source_type"],
        "title": source["title"],
        "uri": source["url"],
        "publisher": source["publisher"],
        "is_official": source["source_type"] == "official_spec",
        "market": row["market"],
        "variant_key": row["configuration_id"].casefold().replace("/", "-").replace("_", "-"),
        "language": source.get("language", "en-US"),
        "source_version": version,
        "published_at": source.get("published_at"),
        "accessed_at": accessed_at,
        "governed_summary": source["summary"],
        "content_hash": "",
        "redistribution_status": "metadata_and_summary_only",
        "access_policy": "public_no_login",
        "testing_organization": source.get("testing_organization"),
        "method_uri": source.get("method_uri"),
        "tested_at": source.get("tested_at"),
        "firmware_version": source.get("firmware_version"),
    }
    payload["content_hash"] = source_content_hash(payload)
    return payload


def build_payload(source_path: Path = DEFAULT_INPUT) -> dict[str, Any]:
    compact = json.loads(source_path.read_text(encoding="utf-8"))
    domain = DomainPackLoader().load(DEFAULT_DOMAIN)
    policy = domain.pack.policies["product_pack"]
    fields = domain.fields
    products: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    accessed_at = compact["accessed_at"]

    for row in compact["products"]:
        product_id = row["product_id"]
        variant_key = row["configuration_id"].casefold().replace("/", "-").replace("_", "-")
        row_sources = {
            item["tier"]: _source_record(row, item, accessed_at)
            for item in row["sources"]
        }
        if "official" not in row_sources:
            raise ValueError("each headphone needs an official source")
        sources.extend(row_sources.values())
        official = row_sources["official"]
        attributes = {field_id: None for field_id in policy["attribute_fields"]}
        attributes.update(row["attributes"])
        attributes["configuration_id"] = row["configuration_id"]
        attributes["source_version"] = official["source_version"]
        products.append(
            {
                "product_id": product_id,
                "brand": row["brand"],
                "canonical_name": row["model_name"],
                "market": row["market"],
                "variant_key": variant_key,
                "aliases": row["aliases"],
                "attributes": {
                    field_id: {"value": value, "unit": fields[field_id].unit}
                    for field_id, value in attributes.items()
                },
                "official_source_ids": [official["source_id"]],
                "status": "active",
            }
        )
        values = {
            "product_id": product_id,
            "brand": row["brand"],
            "model_name": row["model_name"],
            "region": row["market"],
            **attributes,
        }
        field_tiers = row.get("field_tiers", {})
        for field_id, value in values.items():
            if value is None or field_id == "primary_use":
                continue
            tier = field_tiers.get(field_id, "official")
            source = row_sources.get(tier)
            if source is None:
                raise ValueError(f"missing {tier} source for {product_id}/{field_id}")
            evidence.append(
                {
                    "evidence_id": f"ev-{product_id}-{field_id.replace('_', '-')}",
                    "source_id": source["source_id"],
                    "product_id": product_id,
                    "field_id": field_id,
                    "raw_value": value,
                    "normalized_value": value,
                    "unit": fields[field_id].unit,
                    "snippet": f"ProofPick 自制事实摘要：{fields[field_id].label}={value}",
                    "evidence_location": f"governed summary / {field_id}",
                    "market": row["market"],
                    "variant_key": variant_key,
                    "source_version": source["source_version"],
                    "effective_at": None,
                    "observed_at": accessed_at,
                    "confidence": "high" if tier == "official" else "medium",
                    "conflict_group": None,
                    "trust_state": "governed",
                }
            )
    return {
        "schema_version": "1.0.0",
        "pack_id": "headphone-governed-v1",
        "pack_version": "1.0.0",
        "domain_id": "headphone",
        "base_data_version": "headphone-empty-v0",
        "data_version": "headphone-governed-2026-09-03-v1",
        "created_at": compact["created_at"],
        "compatibility": {
            "contract_version": "proofpick-domain-contract-v1",
            "domain_pack_version": "1.0.0",
            "embedding_model": "text-embedding-v4",
            "embedding_dimensions": 1024,
            "chunk_config_version": "headphone-fact-card-v1",
        },
        "license": {
            "redistribution_status": "metadata_and_summary_only",
            "data_license_note": "Official/professional metadata and self-authored short summaries; source terms remain controlling.",
            "raw_content_included": False,
        },
        "products": products,
        "sources": sources,
        "evidence": evidence,
        "observations": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_payload(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"status":"completed","products":len(payload["products"]),"sources":len(payload["sources"]),"evidence":len(payload["evidence"]),"output":str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
