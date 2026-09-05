from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from smartbuy.reproducibility import (
    SemanticManifestError,
    assert_worktree_bytes_match_git,
    build_git_file_group,
    git_blob_bytes,
    git_tree_members,
)
from smartbuy.reproducibility.v2_9h_rc3_manifest import build_rc3_manifest


PRODUCTION_COMMIT = "ba6606ae249bafc89c18b320935c767a3f756c34"
PRODUCTION_TREE = "84766c5d8840b50a27c612e24379b6dd63736741"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EOL_PROBE = "smartbuy/data/processed/stage6_metrics_summary.csv"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _clone_with_eol_mode(
    destination: Path,
    *,
    autocrlf: str,
    eol: str | None = None,
    force_probe_crlf: bool = False,
) -> Path:
    subprocess.run(
        [
            "git",
            "clone",
            "--no-hardlinks",
            "--no-checkout",
            str(REPOSITORY_ROOT),
            str(destination),
        ],
        check=True,
        capture_output=True,
    )
    _git(destination, "config", "core.autocrlf", autocrlf)
    if eol is not None:
        _git(destination, "config", "core.eol", eol)
    _git(destination, "checkout", "--detach", PRODUCTION_COMMIT)
    if force_probe_crlf:
        probe = destination / EOL_PROBE
        probe.write_bytes(
            probe.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        )
    return destination


def test_git_group_uses_tree_members_and_raw_blob_bytes(tmp_path: Path) -> None:
    repository = _clone_with_eol_mode(
        tmp_path / "blob-source",
        autocrlf="true",
        force_probe_crlf=True,
    )
    members = git_tree_members(repository, PRODUCTION_COMMIT)
    group = build_git_file_group(
        repository,
        PRODUCTION_COMMIT,
        [EOL_PROBE],
        tree_members=members,
    )
    blob = git_blob_bytes(repository, PRODUCTION_COMMIT, EOL_PROBE)

    assert group["members"] == [
        {"path": EOL_PROBE, "sha256": hashlib.sha256(blob).hexdigest()}
    ]
    with pytest.raises(SemanticManifestError, match="immutable Git tree"):
        build_git_file_group(
            repository,
            PRODUCTION_COMMIT,
            ["not-in-production-tree.txt"],
            tree_members=members,
        )
    with pytest.raises(SemanticManifestError, match="at least one member"):
        build_git_file_group(
            repository,
            PRODUCTION_COMMIT,
            [],
            tree_members=members,
        )
    with pytest.raises(SemanticManifestError, match="group is empty"):
        assert_worktree_bytes_match_git(repository, PRODUCTION_COMMIT, [])
    with pytest.raises(SemanticManifestError, match="worktree bytes differ"):
        assert_worktree_bytes_match_git(repository, PRODUCTION_COMMIT, [EOL_PROBE])


def test_rc3_manifest_is_identical_across_autocrlf_and_lf_worktrees(
    tmp_path: Path,
) -> None:
    repositories = {
        "core.autocrlf=true": _clone_with_eol_mode(
            tmp_path / "autocrlf-true",
            autocrlf="true",
            force_probe_crlf=True,
        ),
        "core.autocrlf=false": _clone_with_eol_mode(
            tmp_path / "autocrlf-false",
            autocrlf="false",
        ),
        "LF-worktree": _clone_with_eol_mode(
            tmp_path / "lf-worktree",
            autocrlf="false",
            eol="lf",
        ),
    }
    manifests = {
        name: build_rc3_manifest(repository, PRODUCTION_COMMIT)
        for name, repository in repositories.items()
    }

    assert {
        manifest["semantic_contract"]["production_tree"]
        for manifest in manifests.values()
    } == {PRODUCTION_TREE}
    assert len({manifest["payload_sha256"] for manifest in manifests.values()}) == 1
    assert len(
        {
            tuple(
                (
                    group_name,
                    group["aggregate_sha256"],
                    tuple((item["path"], item["sha256"]) for item in group["members"]),
                )
                for group_name, group in manifest["semantic_contract"][
                    "file_groups"
                ].items()
            )
            for manifest in manifests.values()
        }
    ) == 1
