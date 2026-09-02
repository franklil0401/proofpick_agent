"""Build the deterministic Laptop Product Pack from governed compact input."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from smartbuy.domain_packs import DomainPackLoader
from smartbuy.product_packs.loader import source_content_hash


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "smartbuy" / "data" / "laptop" / "laptop_configurations_v1.json"
DEFAULT_DOMAIN = ROOT / "smartbuy" / "domain_packs" / "laptop"
DEFAULT_OUTPUT = ROOT / "smartbuy" / "product_packs" / "examples" / "laptop-v1" / "pack.json"


def build_payload(source_path: Path = DEFAULT_INPUT) -> dict:
    compact = json.loads(source_path.read_text(encoding="utf-8"))
    domain = DomainPackLoader().load(DEFAULT_DOMAIN)
    policy = domain.pack.policies["product_pack"]
    field_definitions = domain.fields
    products = []
    sources = []
    evidence = []
    accessed_at = compact["accessed_at"]
    for row in compact["products"]:
        product_id = row["product_id"]
        variant_key = row["configuration_id"].casefold()
        source_id = f"src-{product_id}"
        source_version = f"official-capture-{accessed_at[:10]}"
        attributes = {field_id: None for field_id in policy["attribute_fields"]}
        attributes.update(row["attributes"])
        attributes["configuration_id"] = row["configuration_id"]
        attributes["source_version"] = source_version
        product = {
            "product_id": product_id,
            "brand": row["brand"],
            "canonical_name": row["model_name"],
            "market": row["market"],
            "variant_key": variant_key,
            "aliases": row["aliases"],
            "attributes": {
                field_id: {"value": value, "unit": field_definitions[field_id].unit}
                for field_id, value in attributes.items()
            },
            "official_source_ids": [source_id],
            "status": "active",
        }
        products.append(product)
        summary = (
            f"ProofPick 自制结构化摘要：{row['model_name']}，地区 {row['market']}，"
            f"配置号 {row['configuration_id']}。只保留官方页面可核验字段；缺失值为 null。"
        )
        source = {
            "source_id": source_id,
            "product_id": product_id,
            "source_type": "official_product",
            "title": row["source"]["title"],
            "uri": row["source"]["url"],
            "publisher": row["source"]["publisher"],
            "is_official": True,
            "market": row["market"],
            "variant_key": variant_key,
            "language": row["source"]["language"],
            "source_version": source_version,
            "published_at": None,
            "accessed_at": accessed_at,
            "governed_summary": summary,
            "content_hash": "",
            "redistribution_status": "metadata_and_summary_only",
            "access_policy": "public_no_login",
        }
        source["content_hash"] = source_content_hash(source)
        sources.append(source)
        identity_values = {
            "product_id": product_id,
            "brand": row["brand"],
            "model_name": row["model_name"],
            "region": row["market"],
        }
        values = {**identity_values, **attributes}
        for field_id, value in values.items():
            if value is None or field_id == "primary_use":
                continue
            evidence.append(
                {
                    "evidence_id": f"ev-{product_id}-{field_id.replace('_', '-')}",
                    "source_id": source_id,
                    "product_id": product_id,
                    "field_id": field_id,
                    "raw_value": value,
                    "normalized_value": value,
                    "unit": field_definitions[field_id].unit,
                    "snippet": f"自制事实摘要：{field_definitions[field_id].label}={value}",
                    "evidence_location": f"governed summary / {field_id}",
                    "market": row["market"],
                    "variant_key": variant_key,
                    "source_version": source_version,
                    "effective_at": None,
                    "observed_at": accessed_at,
                    "confidence": "high",
                    "conflict_group": None,
                    "trust_state": "governed",
                }
            )
    return {
        "schema_version": "1.0.0",
        "pack_id": "laptop-governed-v1",
        "pack_version": "1.0.0",
        "domain_id": "laptop",
        "base_data_version": "laptop-empty-v0",
        "data_version": "laptop-governed-2026-09-02-v1",
        "created_at": compact["created_at"],
        "compatibility": {
            "contract_version": "proofpick-domain-contract-v1",
            "domain_pack_version": "1.0.0",
            "embedding_model": "text-embedding-v4",
            "embedding_dimensions": 1024,
            "chunk_config_version": "laptop-fact-card-v1",
        },
        "license": {
            "redistribution_status": "metadata_and_summary_only",
            "data_license_note": "Official-page metadata and self-authored factual summaries; source terms remain controlling.",
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
    print(
        json.dumps(
            {
                "status": "completed",
                "products": len(payload["products"]),
                "sources": len(payload["sources"]),
                "evidence": len(payload["evidence"]),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
