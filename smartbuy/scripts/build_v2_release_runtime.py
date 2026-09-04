"""Build the Laptop and Headphone V2 runtime outside the repository.

Product Pack publication is offline and idempotent.  Index construction is
explicit because it calls text-embedding-v4; every activated index remains
domain/data/version bound and fixed at 1024 dimensions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from smartbuy.config import load_bailian_settings
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.providers import BailianProvider
from smartbuy.retrieval.domain_index import DomainIndexManager


ROOT = Path(__file__).resolve().parents[2]
DOMAINS = {
    "laptop": {
        "product_pack": ROOT / "smartbuy/product_packs/examples/laptop-v1/pack.json",
        "index_version": "laptop-governed-2026-09-02-v1-embedding1024-v1",
    },
    "headphone": {
        "product_pack": ROOT / "smartbuy/product_packs/examples/headphone-v1/pack.json",
        "index_version": "headphone-governed-2026-09-03-v1-embedding1024-v1",
    },
}


async def build(runtime_root: Path, *, build_indices: bool) -> dict:
    output: dict[str, dict] = {}
    provider = BailianProvider(load_bailian_settings()) if build_indices else None
    try:
        for domain_id, config in DOMAINS.items():
            domain_path = ROOT / "smartbuy/domain_packs" / domain_id
            pack = DomainPackLoader().load(domain_path)
            domain_root = runtime_root / domain_id
            data_manager = DomainProductPackManager(
                domain_root / "data", domain_pack_path=domain_path
            )
            staged = data_manager.stage(config["product_pack"])
            published = data_manager.publish(staged.data_version)
            row = {
                "domain_pack_version": pack.version,
                "data_version": published.data_version,
                "data_manifest_hash": published.manifest_hash,
                "counts": published.manifest["counts"],
                "index": "not_built",
            }
            if build_indices:
                assert provider is not None
                manager = DomainIndexManager(
                    domain_root / "index",
                    data_manager=data_manager,
                    domain_id=domain_id,
                    domain_pack_version=pack.version,
                )
                index = await manager.build(
                    published.data_version,
                    config["index_version"],
                    provider,
                    batch_size=10,
                    cost_limit_cny=0.5,
                )
                manager.activate(index.index_version)
                row["index"] = {
                    "index_version": index.index_version,
                    "collection_name": index.collection_name,
                    "document_count": index.manifest["document_count"],
                    "embedding_model": index.manifest["embedding_model"],
                    "embedding_dimensions": index.manifest["embedding_dimensions"],
                    "estimated_cost_cny": index.manifest["embedding_estimated_cost_cny"],
                }
            output[domain_id] = row
    finally:
        if provider is not None:
            await provider.aclose()
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--build-indices", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(build(args.runtime_root.resolve(), build_indices=args.build_indices))
    print(json.dumps({"status": "completed", "domains": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
