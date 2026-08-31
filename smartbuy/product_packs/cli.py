"""CLI for Product Pack import, validation, publication, inspection, and rollback."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from smartbuy.product_packs.builder import ProductPackManager
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manager = ProductPackManager(args.runtime_root)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
