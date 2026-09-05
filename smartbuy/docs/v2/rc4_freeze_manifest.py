"""Offline RC4 document tooling; never imported by the production runtime.

Reuse the frozen R1 Git blob method. The recipe is copied into the semantic
payload, so member selectors and runtime-profile values are independently
auditable. No environment credentials, model calls or evaluation tasks are read.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from smartbuy.reproducibility.semantic_manifest import (
    build_git_file_group,
    git_tree_members,
    stable_sha256,
)
from smartbuy.reproducibility.v2_9h_rc3_manifest import build_rc3_manifest


PRODUCTION = "99c7bccc523addc7e8904571dbe8e20a24615c66"
TREE = "6b6e98009cefe5aa13f64cf8fe1b24d001fbadb1"


def build(root: Path, recipe: dict) -> dict:
    if recipe["production_commit"] != PRODUCTION or recipe["production_tree"] != TREE:
        raise ValueError("RC4 production identity mismatch")
    manifest = build_rc3_manifest(root, PRODUCTION)
    contract = manifest["semantic_contract"]
    if contract["production_tree"] != TREE:
        raise ValueError("RC4 Git tree mismatch")
    members = git_tree_members(root, PRODUCTION)
    groups = contract["file_groups"]
    for name, selector in recipe["extra_groups"].items():
        selected = [path for path in members if (
            any(path.startswith(prefix) for prefix in selector["prefixes"])
            and (not selector.get("suffixes") or path.endswith(tuple(selector["suffixes"])))
        )]
        groups[name] = build_git_file_group(root, PRODUCTION, selected, tree_members=members)
    groups["test_baseline"] = build_git_file_group(
        root, PRODUCTION,
        [row["path"] for row in groups["test_baseline"]["members"]]
        + recipe["test_baseline_extra_members"], tree_members=members,
    )
    contract["file_groups"] = dict(sorted(groups.items()))
    contract["test_baseline_sha256"] = groups["test_baseline"]["aggregate_sha256"]
    contract["release_contract"]["release_candidate"] = recipe["release_candidate"]
    contract["release_contract"]["manifest_revision"] = "initial_git_blob_freeze"
    contract["freeze_recipe"] = recipe
    manifest["payload_sha256"] = stable_sha256(contract)
    manifest["runtime_audit"] = {
        "release_candidate": recipe["release_candidate"],
        "evidence_kind": "code_profile_freeze_and_prior_offline_validation_not_live_model_evaluation",
        "services_started_this_freeze": False,
        "api_calls_this_freeze": 0,
        "estimated_cost_cny_this_freeze": 0,
        "runtime_indices": "semantic versions inherited from validated baseline; not rebuilt or live-probed during this freeze",
        "validation_evidence_commit": PRODUCTION,
        "validation_record": "smartbuy/eval/results/v2_9j_development_regression.json",
        "windows_ci_run": "https://github.com/franklil0401/proofpick_agent/actions/runs/33966853197",
    }
    return manifest


def check(root: Path, expected: dict, actual: dict) -> None:
    if expected["semantic_contract"] != actual["semantic_contract"]:
        raise ValueError("semantic contract does not reproduce")
    if actual["payload_sha256"] != stable_sha256(actual["semantic_contract"]):
        raise ValueError("payload hash mismatch")
    # Recompute every member directly, independently of the group builder.
    import hashlib

    available = set(git_tree_members(root, PRODUCTION))
    seen: dict[str, str] = {}
    for group in actual["semantic_contract"]["file_groups"].values():
        if group["aggregate_sha256"] != stable_sha256(group["members"]):
            raise ValueError("aggregate mismatch")
        for row in group["members"]:
            if row["path"] not in available:
                raise ValueError("member outside production tree")
            if row["path"] not in seen:
                blob = subprocess.check_output(
                    ["git", "cat-file", "blob", f"{PRODUCTION}:{row['path']}"], cwd=root,
                )
                seen[row["path"]] = hashlib.sha256(blob).hexdigest()
            if row["sha256"] != seen[row["path"]]:
                raise ValueError("Git blob member mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--recipe", type=Path, default=Path(__file__).with_name("rc4_freeze_recipe.json"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--check", type=Path)
    args = parser.parse_args()
    recipe = json.loads(args.recipe.read_text(encoding="utf-8"))
    manifest = build(args.root, recipe)
    if args.check:
        check(args.root, manifest, json.loads(args.check.read_text(encoding="utf-8")))
    else:
        # Refuse to overwrite any first freeze artifact.
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    print(json.dumps({
        "payload_sha256": manifest["payload_sha256"],
        "groups": len(manifest["semantic_contract"]["file_groups"]),
        "unique_members": len({row["path"] for group in manifest["semantic_contract"]["file_groups"].values() for row in group["members"]}),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
