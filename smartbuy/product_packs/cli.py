"""CLI for Product Pack import, validation, publication, inspection, and rollback."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Sequence

from smartbuy.product_packs.builder import ProductPackManager
from smartbuy.product_packs.live_index import ProductIndexManager
from smartbuy.product_packs.runtime import DEFAULT_PRODUCT_PACK_ROOT


def _result(command: str, **values: object) -> None:
    print(json.dumps({"command": command, "status": "completed", **values}, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_PRODUCT_PACK_ROOT)
    subcommands = parser.add_subparsers(dest="command", required=True)
    import_parser = subcommands.add_parser("import", help="load, normalize, and stage a pack")
    import_parser.add_argument("--pack", type=Path, required=True)
    validate_parser = subcommands.add_parser("validate", help="validate staged or published data")
    validate_parser.add_argument("--data-version", required=True)
    validate_parser.add_argument("--published", action="store_true")
    publish_parser = subcommands.add_parser("publish", help="atomically publish a staged version")
    publish_parser.add_argument("--data-version", required=True)
    subcommands.add_parser("versions", help="list immutable published versions")
    subcommands.add_parser("current", help="show the current published version")
    rollback_parser = subcommands.add_parser("rollback", help="move the pointer to an older version")
    rollback_parser.add_argument("--data-version", required=True)
    build_index = subcommands.add_parser(
        "build-index", help="build and validate a live Chroma index without selecting it"
    )
    build_index.add_argument("--data-version", required=True)
    build_index.add_argument("--index-version", required=True)
    build_index.add_argument("--batch-size", type=int, default=10)
    build_index.add_argument("--cost-limit-cny", type=float, default=1.0)
    validate_index = subcommands.add_parser("validate-index", help="validate a live index")
    validate_index.add_argument("--index-version", required=True)
    activate_index = subcommands.add_parser(
        "activate-index", help="atomically select a fully validated live index"
    )
    activate_index.add_argument("--index-version", required=True)
    subcommands.add_parser("index-versions", help="list immutable live index versions")
    subcommands.add_parser("current-index", help="show the selected live index")
    rollback_index = subcommands.add_parser("rollback-index", help="select an older live index")
    rollback_index.add_argument("--index-version", required=True)
    return parser


async def _build_live_index(args: argparse.Namespace, manager: ProductIndexManager) -> None:
    from smartbuy.config import load_bailian_settings
    from smartbuy.providers import BailianProvider

    settings = load_bailian_settings()
    async with BailianProvider(settings, timeout_seconds=30.0) as provider:
        snapshot = await manager.build(
            args.data_version,
            args.index_version,
            provider,
            batch_size=args.batch_size,
            cost_limit_cny=args.cost_limit_cny,
        )
    _result(
        "build-index",
        data_version=snapshot.data_version,
        index_version=snapshot.index_version,
        collection_name=snapshot.collection_name,
        manifest_hash=snapshot.manifest_hash,
        document_count=snapshot.manifest["document_count"],
        chunk_count=snapshot.manifest["chunk_count"],
        embedding_dimensions=snapshot.manifest["embedding_dimensions"],
        embedding_call_count=snapshot.manifest["embedding_call_count"],
        embedding_input_tokens=snapshot.manifest["embedding_input_tokens"],
        embedding_estimated_cost_cny=snapshot.manifest[
            "embedding_estimated_cost_cny"
        ],
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manager = ProductPackManager(args.runtime_root)
    index_manager = ProductIndexManager(args.runtime_root)
    if args.command == "import":
        snapshot = manager.stage(args.pack)
        _result(
            "import",
            data_version=snapshot.data_version,
            manifest_hash=snapshot.manifest_hash,
        )
    elif args.command == "validate":
        snapshot = manager.validate(args.data_version, published=args.published)
        _result(
            "validate",
            data_version=snapshot.data_version,
            manifest_hash=snapshot.manifest_hash,
            counts=snapshot.manifest["counts"],
        )
    elif args.command == "publish":
        snapshot = manager.publish(args.data_version)
        _result(
            "publish",
            data_version=snapshot.data_version,
            manifest_hash=snapshot.manifest_hash,
        )
    elif args.command == "versions":
        _result("versions", versions=manager.list_versions())
    elif args.command == "current":
        snapshot = manager.current()
        _result(
            "current",
            data_version=snapshot.data_version,
            manifest_hash=snapshot.manifest_hash,
        )
    elif args.command == "rollback":
        snapshot = manager.rollback(args.data_version)
        _result(
            "rollback",
            data_version=snapshot.data_version,
            manifest_hash=snapshot.manifest_hash,
        )
    elif args.command == "build-index":
        asyncio.run(_build_live_index(args, index_manager))
    elif args.command == "validate-index":
        snapshot = index_manager.validate(args.index_version)
        _result(
            "validate-index",
            data_version=snapshot.data_version,
            index_version=snapshot.index_version,
            collection_name=snapshot.collection_name,
            manifest_hash=snapshot.manifest_hash,
            chunk_count=snapshot.manifest["chunk_count"],
        )
    elif args.command == "activate-index":
        snapshot = index_manager.activate(args.index_version)
        _result(
            "activate-index",
            data_version=snapshot.data_version,
            index_version=snapshot.index_version,
            collection_name=snapshot.collection_name,
            manifest_hash=snapshot.manifest_hash,
        )
    elif args.command == "index-versions":
        _result("index-versions", versions=index_manager.list_versions())
    elif args.command == "current-index":
        snapshot = index_manager.current()
        _result(
            "current-index",
            data_version=snapshot.data_version,
            index_version=snapshot.index_version,
            collection_name=snapshot.collection_name,
            manifest_hash=snapshot.manifest_hash,
        )
    elif args.command == "rollback-index":
        snapshot = index_manager.rollback(args.index_version)
        _result(
            "rollback-index",
            data_version=snapshot.data_version,
            index_version=snapshot.index_version,
            collection_name=snapshot.collection_name,
            manifest_hash=snapshot.manifest_hash,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
