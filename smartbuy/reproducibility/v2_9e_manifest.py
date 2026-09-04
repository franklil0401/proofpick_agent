"""Build the portable V2-9E semantic runtime contract from an immutable commit."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from smartbuy.reproducibility.semantic_manifest import (
    SemanticManifestError,
    build_file_group,
    build_semantic_manifest,
)


PRODUCTION_PREFIXES = (
    "smartbuy/agent/",
    "smartbuy/api/",
    "smartbuy/cache/",
    "smartbuy/config/",
    "smartbuy/constraint_proposals/",
    "smartbuy/constraints/",
    "smartbuy/contracts/",
    "smartbuy/db/",
    "smartbuy/decision_core/",
    "smartbuy/domain/",
    "smartbuy/identity/",
    "smartbuy/memory/",
    "smartbuy/observability/",
    "smartbuy/open_research/",
    "smartbuy/orchestration/",
    "smartbuy/portfolio/",
    "smartbuy/product_packs/",
    "smartbuy/providers/",
    "smartbuy/ranking/",
    "smartbuy/retrieval/",
    "smartbuy/source_search/",
    "smartbuy/tools/",
)
DATA_PREFIXES = (
    "smartbuy/data/catalog/",
    "smartbuy/data/demo/",
    "smartbuy/data/processed/",
    "smartbuy/data/laptop/",
    "smartbuy/data/headphone/",
    "smartbuy/product_packs/examples/",
)
SCORING_MEMBERS = (
    "smartbuy/eval/stage6_scoring.py",
    "smartbuy/eval/v2_6c_r2_laptop_scorer.py",
    "smartbuy/eval/v2_6c_r2_laptop_scoring_policy.json",
    "smartbuy/eval/v2_6c_r3_validation.schema.json",
    "smartbuy/eval/v2_6c_r3_validation_scorer.py",
    "smartbuy/eval/v2_8_headphone_engineering.schema.json",
    "smartbuy/eval/v2_8_headphone_engineering_policy.json",
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _members_at(root: Path, commit: str) -> list[str]:
    return _git(root, "ls-tree", "-r", "--name-only", commit).splitlines()


def _select(
    files: list[str],
    *,
    prefixes: tuple[str, ...] = (),
    exact: tuple[str, ...] = (),
    suffixes: tuple[str, ...] = (),
) -> list[str]:
    exact_set = set(exact)
    return sorted(
        path
        for path in files
        if (
            path in exact_set
            or any(path.startswith(prefix) for prefix in prefixes)
        )
        and (not suffixes or path.endswith(suffixes))
    )


def _assert_worktree_matches(root: Path, commit: str, members: list[str]) -> None:
    if not members:
        raise SemanticManifestError("semantic manifest group is empty")
    result = subprocess.run(
        ["git", "diff", "--quiet", commit, "--", *members],
        cwd=root,
        check=False,
    )
    if result.returncode != 0:
        raise SemanticManifestError(
            "worktree member bytes differ from the requested production commit"
        )


def build_v2_9e_manifest(root: Path, production_commit: str) -> dict[str, object]:
    root = root.resolve()
    commit = _git(root, "rev-parse", f"{production_commit}^{{commit}}")
    tree = _git(root, "rev-parse", f"{commit}^{{tree}}")
    files = _members_at(root, commit)
    production = _select(files, prefixes=PRODUCTION_PREFIXES, suffixes=(".py",))
    domain_config = _select(
        files,
        prefixes=("smartbuy/domain_packs/",),
        suffixes=(".json",),
    )
    governed_data = _select(files, prefixes=DATA_PREFIXES)
    scoring = _select(files, exact=SCORING_MEMBERS)
    tests = _select(
        files,
        prefixes=("smartbuy/tests/",),
        exact=(".github/workflows/ci.yml",),
    )
    windows_scripts = _select(
        files,
        prefixes=("smartbuy/scripts/",),
        suffixes=(".ps1",),
    )
    dependency = _select(
        files,
        exact=("vendor/youtu-rag/pyproject.toml", "vendor/youtu-rag/uv.lock"),
    )
    selected = {
        "dependency_lock": dependency,
        "production_python": production,
        "domain_pack_config": domain_config,
        "governed_data": governed_data,
        "scoring_interface": scoring,
        "test_baseline": tests,
        "windows_scripts": windows_scripts,
    }
    groups = {}
    for name, members in selected.items():
        _assert_worktree_matches(root, commit, members)
        groups[name] = build_file_group(root, members)
    runtime = {
        "production_commit": commit,
        "production_tree": tree,
        "domains": [
            {
                "domain_id": "monitor",
                "domain_pack_version": "1.0.0",
                "data_version": "monitor-cn-2026-08-26-v1",
                "index_version": "monitor-fact-card-h2-v1",
                "collection_name": "smartbuy_monitors_v1",
                "document_count": 60,
                "embedding_model": "text-embedding-v4",
                "embedding_dimensions": 1024,
                "data_logical_sha256": "079c4f745e8dbbb538fe7cdacf5479f4e25ebc38972ef2175edf8876a35e8ffe",
            },
            {
                "domain_id": "laptop",
                "domain_pack_version": "1.0.0",
                "data_version": "laptop-governed-2026-09-02-v1",
                "index_version": "laptop-governed-2026-09-02-v1-embedding1024-v1",
                "collection_name": "proofpick_laptop_v2_4e6d332c11bf8f7c",
                "document_count": 12,
                "embedding_model": "text-embedding-v4",
                "embedding_dimensions": 1024,
                "data_logical_sha256": "13cf9fffa9383921ed29a1e426da6a199edb699ec346aee985ecf21c9918f8b1",
            },
            {
                "domain_id": "headphone",
                "domain_pack_version": "1.0.0",
                "data_version": "headphone-governed-2026-09-03-v1",
                "index_version": "headphone-governed-2026-09-03-v1-embedding1024-v1",
                "collection_name": "proofpick_headphone_v2_cae477364b46ccae",
                "document_count": 12,
                "embedding_model": "text-embedding-v4",
                "embedding_dimensions": 1024,
                "data_logical_sha256": "c1edf981e00f6ad15b409d1d4ea37b2c8e2dc6dd36b95ce4be99ac57693fc40a",
            },
        ],
        "scoring_contract_sha256": groups["scoring_interface"]["aggregate_sha256"],
        "test_baseline_sha256": groups["test_baseline"]["aggregate_sha256"],
        "runtime_audit": {
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "machine_path": "excluded_from_semantic_contract",
            "latency_and_token_usage": "preserved_in_run_results_only",
            "rc2_raw_audit": "origin/eval/v2-9d-independent-rc2:smartbuy/eval/results/v2_9d_runtime_manifest_audit.json",
        },
    }
    return build_semantic_manifest(runtime, file_groups=groups)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--production-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_v2_9e_manifest(args.root, args.production_commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(payload["payload_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
