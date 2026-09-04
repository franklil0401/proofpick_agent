"""Canonical semantic manifest whose hash excludes run-specific telemetry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SEMANTIC_MANIFEST_VERSION = "proofpick-semantic-runtime-manifest-v1"
_DOMAIN_KEYS = (
    "domain_id",
    "domain_pack_version",
    "data_version",
    "index_version",
    "collection_name",
    "document_count",
    "embedding_model",
    "embedding_dimensions",
    "data_logical_sha256",
)
_SHA_KEYS = {"data_logical_sha256"}


class SemanticManifestError(ValueError):
    """The stable runtime contract is incomplete or unsafe to fingerprint."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_file_group(root: Path, members: Sequence[str]) -> dict[str, Any]:
    """Hash an explicit, sorted member set; aggregate hashes are never opaque."""
    resolved_root = root.resolve()
    output: list[dict[str, str]] = []
    for raw in sorted(set(members)):
        relative = Path(raw)
        if relative.is_absolute() or ".." in relative.parts:
            raise SemanticManifestError("manifest members must be repository-relative")
        path = (resolved_root / relative).resolve()
        if resolved_root not in path.parents or not path.is_file():
            raise SemanticManifestError(f"manifest member is missing or outside root: {raw}")
        output.append({"path": relative.as_posix(), "sha256": _file_sha256(path)})
    if not output:
        raise SemanticManifestError("manifest group must contain at least one member")
    return {"members": output, "aggregate_sha256": stable_sha256(output)}


def _domain_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    missing = [key for key in _DOMAIN_KEYS if key not in value]
    if missing:
        raise SemanticManifestError(
            "domain runtime contract is missing: " + ", ".join(missing)
        )
    contract = {key: value[key] for key in _DOMAIN_KEYS}
    if not isinstance(contract["document_count"], int) or contract["document_count"] < 0:
        raise SemanticManifestError("document_count must be a non-negative integer")
    if (
        not isinstance(contract["embedding_dimensions"], int)
        or contract["embedding_dimensions"] <= 0
    ):
        raise SemanticManifestError("embedding_dimensions must be positive")
    for key in _SHA_KEYS:
        digest = contract[key]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise SemanticManifestError(f"{key} must be a lowercase SHA-256")
    return contract


def build_semantic_manifest(
    runtime: Mapping[str, Any],
    *,
    file_groups: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return stable contract plus a separate, unhashed audit envelope.

    Callers provide explicit domain contracts and member-bearing file groups.
    Timing, token/cost telemetry, creation timestamps and machine paths may be
    retained under ``runtime_audit`` but can never influence ``payload_sha256``.
    """
    raw_domains = runtime.get("domains")
    if not isinstance(raw_domains, list) or not raw_domains:
        raise SemanticManifestError("runtime.domains must be a non-empty list")
    domains = sorted(
        (_domain_contract(item) for item in raw_domains),
        key=lambda item: item["domain_id"],
    )
    groups: dict[str, Any] = {}
    for name, group in sorted(file_groups.items()):
        members = group.get("members")
        aggregate = group.get("aggregate_sha256")
        if not isinstance(members, list) or not members:
            raise SemanticManifestError(f"file group {name} has no member list")
        if aggregate != stable_sha256(members):
            raise SemanticManifestError(f"file group {name} aggregate hash mismatch")
        groups[name] = {"members": members, "aggregate_sha256": aggregate}
    payload = {
        "schema_version": SEMANTIC_MANIFEST_VERSION,
        "production_commit": runtime.get("production_commit"),
        "production_tree": runtime.get("production_tree"),
        "domains": domains,
        "file_groups": groups,
        "scoring_contract_sha256": runtime.get("scoring_contract_sha256"),
        "test_baseline_sha256": runtime.get("test_baseline_sha256"),
    }
    if not payload["production_commit"] or not payload["production_tree"]:
        raise SemanticManifestError("production commit and tree are required")
    manifest = {
        "semantic_contract": payload,
        "payload_sha256": stable_sha256(payload),
        "runtime_audit": dict(runtime.get("runtime_audit", {})),
    }
    return manifest
