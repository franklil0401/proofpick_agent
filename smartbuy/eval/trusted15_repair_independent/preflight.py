"""Complete Git-blob and runtime audit of the new fixed production."""

import hashlib
import subprocess
from pathlib import Path

from smartbuy.eval.v2_9k_independent.audit import runtime_audit, stable

ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = "bad83ea7512e6b53ae554bbd4a1f80f0c3f4f715"
TREE = "5f3bdc6f50ec4ad71636ac745d31881f4323f7ed"


def main():
    assert subprocess.check_output(["git", "rev-parse", PRODUCTION + "^{tree}"], cwd=ROOT, text=True).strip() == TREE
    paths = sorted(path for path in subprocess.check_output(
        ["git", "ls-tree", "-rz", "--name-only", PRODUCTION], cwd=ROOT).decode().split("\0") if path)
    blobs = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT, input=(
        "\n".join(PRODUCTION + ":" + path for path in paths) + "\n").encode(), capture_output=True, check=True).stdout
    position, members = 0, []
    for path in paths:
        end = blobs.index(b"\n", position)
        _, kind, size = blobs[position:end].split()
        assert kind == b"blob"
        position = end + 1
        blob = blobs[position:position + int(size)]
        position += int(size) + 1
        assert (ROOT / path).read_bytes().replace(b"\r\n", b"\n") == blob.replace(b"\r\n", b"\n"), path
        members.append({"path": path, "sha256": hashlib.sha256(blob).hexdigest()})
    return {"production_commit": PRODUCTION, "production_tree": TREE, "member_count": len(members),
            "members": members, "git_blob_aggregate_sha256": stable(members),
            "checkout_mismatches": 0, "runtime": runtime_audit(), "model_calls": 0}
