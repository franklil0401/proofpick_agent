"""CLI for domain-neutral Product Pack staging, publication, and rollback."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from smartbuy.product_packs.domain_builder import DomainProductPackManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--domain-pack", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("stage")
    stage.add_argument("--pack", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--data-version", required=True)
    validate.add_argument("--published", action="store_true")
    publish = commands.add_parser("publish")
    publish.add_argument("--data-version", required=True)
    commands.add_parser("versions")
    commands.add_parser("current")
    rollback = commands.add_parser("rollback")
    rollback.add_argument("--data-version", required=True)
    return parser


def _print(command: str, **payload: object) -> None:
    print(json.dumps({"command": command, "status": "completed", **payload}, ensure_ascii=False))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manager = DomainProductPackManager(args.runtime_root, domain_pack_path=args.domain_pack)
    if args.command == "stage":
        snapshot = manager.stage(args.pack)
        _print("stage", data_version=snapshot.data_version, manifest_hash=snapshot.manifest_hash)
    elif args.command == "validate":
        snapshot = manager.validate(args.data_version, published=args.published)
        _print("validate", data_version=snapshot.data_version, counts=snapshot.manifest["counts"])
    elif args.command == "publish":
        snapshot = manager.publish(args.data_version)
        _print("publish", data_version=snapshot.data_version, manifest_hash=snapshot.manifest_hash)
    elif args.command == "versions":
        _print("versions", versions=manager.list_versions())
    elif args.command == "current":
        snapshot = manager.current()
        _print("current", data_version=snapshot.data_version, manifest_hash=snapshot.manifest_hash)
    elif args.command == "rollback":
        snapshot = manager.rollback(args.data_version)
        _print("rollback", data_version=snapshot.data_version, manifest_hash=snapshot.manifest_hash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
