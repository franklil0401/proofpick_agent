"""Run the bounded Stage 3 pilot or full knowledge-base build."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from smartbuy.config import load_bailian_settings
from smartbuy.retrieval.knowledge_base import (
    DEFAULT_INDEX_DIR,
    INDEX_MANIFEST_PATH,
    build_knowledge_base,
    write_index_manifest,
)


PILOT_MODELS = {"dell-u2723qe-cn", "dell-u2724d-cn", "asus-pg27aqdm-cn"}


async def _run(mode: str, index_dir: Path, manifest_output: Path) -> dict[str, object]:
    settings = load_bailian_settings()
    if mode == "pilot":
        manifest, _ = await build_knowledge_base(
            settings,
            index_dir=index_dir,
            collection_name="smartbuy_monitors_v1_pilot",
            model_ids=PILOT_MODELS,
            rebuild=True,
        )
    else:
        manifest, _ = await build_knowledge_base(settings, index_dir=index_dir, rebuild=True)
        write_index_manifest(manifest, manifest_output)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("pilot", "full"), required=True)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--manifest-output", type=Path, default=INDEX_MANIFEST_PATH)
    args = parser.parse_args()
    manifest = asyncio.run(_run(args.mode, args.index_dir, args.manifest_output))
    safe = {
        "status": manifest["status"],
        "collection_name": manifest["collection_name"],
        "document_count": manifest["document_count"],
        "builder_chunk_count": manifest["builder_chunk_count"],
        "chroma_chunk_count": manifest["chroma_chunk_count"],
        "embedding_call_count": manifest["embedding_call_count"],
        "embedding_input_tokens": manifest["embedding_input_tokens"],
        "embedding_estimated_cost_cny": manifest["embedding_estimated_cost_cny"],
    }
    print(json.dumps(safe, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
