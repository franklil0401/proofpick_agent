from __future__ import annotations

from pathlib import Path

import pytest

from smartbuy.reproducibility import (
    SemanticManifestError,
    build_file_group,
    build_semantic_manifest,
)


def _runtime(**audit):
    return {
        "production_commit": "a" * 40,
        "production_tree": "b" * 40,
        "domains": [
            {
                "domain_id": "fictional",
                "domain_pack_version": "1.2.3",
                "data_version": "fictional-data-v4",
                "index_version": "fictional-index-v5",
                "collection_name": "fictional-v5",
                "document_count": 17,
                "embedding_model": "text-embedding-v4",
                "embedding_dimensions": 1024,
                "data_logical_sha256": "c" * 64,
                "created_at": "ignored",
                "latency_ms": 999,
            }
        ],
        "scoring_contract_sha256": "d" * 64,
        "test_baseline_sha256": "e" * 64,
        "runtime_audit": audit,
    }


def test_semantic_hash_excludes_runtime_telemetry_and_machine_paths(tmp_path: Path) -> None:
    member = tmp_path / "contract.json"
    member.write_text("{}", encoding="utf-8")
    groups = {"contracts": build_file_group(tmp_path, ["contract.json"])}
    first = build_semantic_manifest(
        _runtime(created_at="one", latency_ms=10, tokens=20, machine_path="C:/one"),
        file_groups=groups,
    )
    second = build_semantic_manifest(
        _runtime(created_at="two", latency_ms=900, tokens=999, machine_path="D:/two"),
        file_groups=groups,
    )
    assert first["payload_sha256"] == second["payload_sha256"]
    assert first["runtime_audit"] != second["runtime_audit"]


def test_semantic_hash_changes_for_data_or_index_contract(tmp_path: Path) -> None:
    member = tmp_path / "contract.json"
    member.write_text("{}", encoding="utf-8")
    groups = {"contracts": build_file_group(tmp_path, ["contract.json"])}
    first_runtime = _runtime()
    second_runtime = _runtime()
    second_runtime["domains"][0]["index_version"] = "fictional-index-v6"
    assert build_semantic_manifest(first_runtime, file_groups=groups)[
        "payload_sha256"
    ] != build_semantic_manifest(second_runtime, file_groups=groups)["payload_sha256"]


def test_file_group_lists_members_and_rejects_opaque_or_unsafe_inputs(tmp_path: Path) -> None:
    member = tmp_path / "a.txt"
    member.write_text("safe", encoding="utf-8")
    group = build_file_group(tmp_path, ["a.txt"])
    assert group["members"][0]["path"] == "a.txt"
    with pytest.raises(SemanticManifestError, match="repository-relative"):
        build_file_group(tmp_path, ["../outside.txt"])
    with pytest.raises(SemanticManifestError, match="aggregate hash mismatch"):
        build_semantic_manifest(_runtime(), file_groups={"opaque": {"members": [{}], "aggregate_sha256": "0" * 64}})
