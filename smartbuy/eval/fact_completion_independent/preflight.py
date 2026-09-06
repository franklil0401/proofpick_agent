"""Verify the full fixed production tree and existing external index contracts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from smartbuy.eval.v2_9k_independent.audit import runtime_audit, stable

ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = "02e97a2c793ba75dfad5ece15e5df665652808bf"
TREE = "7e6b036bc3255714cd378e887ae8b9779a5ef98a"


def main():
    tree = subprocess.check_output(["git", "rev-parse", PRODUCTION + "^{tree}"], cwd=ROOT, text=True).strip()
    assert tree == TREE
    paths = sorted(p for p in subprocess.check_output(
        ["git", "ls-tree", "-rz", "--name-only", PRODUCTION], cwd=ROOT).decode().split("\0") if p)
    payload = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT, input=(
        "\n".join(PRODUCTION + ":" + path for path in paths) + "\n").encode(),
        capture_output=True, check=True).stdout
    position = 0
    members = []
    for path in paths:
        end = payload.index(b"\n", position)
        _, kind, size = payload[position:end].split()
        assert kind == b"blob"
        position = end + 1
        blob = payload[position:position + int(size)]
        position += int(size) + 1
        assert (ROOT / path).read_bytes().replace(b"\r\n", b"\n") == blob.replace(b"\r\n", b"\n"), path
        members.append({"path": path, "sha256": hashlib.sha256(blob).hexdigest()})
    return {"production_commit": PRODUCTION, "production_tree": tree,
            "production_member_count": len(members), "members": members,
            "git_blob_aggregate_sha256": stable(members), "checkout_mismatches": 0,
            "runtime": runtime_audit(), "model_calls": 0,
            "not_a_new_release_candidate_manifest": True}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
