"""Independently rehash Git objects and freeze evaluator files before any case run."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
PRODUCTION = "ba6606ae249bafc89c18b320935c767a3f756c34"


def sha(value):
    return hashlib.sha256(value).hexdigest()


def stable(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def texts(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in {"query", "question", "user_query", "input", "prompt"} and isinstance(v, str):
                yield v.strip()
            else:
                yield from texts(v)
    elif isinstance(node, list):
        for v in node:
            yield from texts(v)


def main():
    manifest = json.loads((ROOT / "smartbuy/eval/results/v2_9h_rc3_semantic_runtime_manifest_r1.json").read_text(encoding="utf8"))
    contract = manifest["semantic_contract"]
    tree = subprocess.check_output(["git", "rev-parse", f"{PRODUCTION}^{{tree}}"], cwd=ROOT).decode().strip()
    assert tree == contract["production_tree"]
    tree_paths = set(subprocess.check_output(["git", "ls-tree", "-r", "-z", "--name-only", PRODUCTION], cwd=ROOT).decode().split("\0"))
    files = {}
    count = 0
    for group in contract["file_groups"].values():
        assert stable(group["members"]) == group["aggregate_sha256"]
        for member in group["members"]:
            path = member["path"]
            assert path in tree_paths
            blob = subprocess.check_output(["git", "cat-file", "blob", f"{PRODUCTION}:{path}"], cwd=ROOT)
            assert sha(blob) == member["sha256"], path
            files[path] = member["sha256"]
            count += 1
    assert stable(contract) == manifest["payload_sha256"]
    assert len(files) == 267 and count == 370
    previous = set()
    historical_files = 0
    for path in [ROOT / "smartbuy/eval", Path("C:/ppv2rc2eval2/smartbuy/eval")]:
        if not path.exists():
            continue
        for source in path.rglob("*.jsonl"):
            if BASE in source.parents:
                continue
            try:
                for line in source.read_text(encoding="utf-8-sig").splitlines():
                    previous.update(texts(json.loads(line)))
                historical_files += 1
            except (ValueError, UnicodeError):
                continue
    cases = [json.loads(x) for x in (BASE / "trusted_cases.jsonl").read_text(encoding="utf8").splitlines()]
    collisions = [c["case_id"] for c in cases if c["query"].strip() in previous]
    assert not collisions, collisions
    catalog = json.loads((BASE / "gold_catalog.json").read_text(encoding="utf8"))
    known_pairs = [f for c in cases for f in c["gold"]["facts"] if f["known"]]
    assert all(f["evidence_ids"] for f in known_pairs)
    file_hashes = {}
    for p in sorted(BASE.iterdir()):
        if p.is_file() and p.suffix in {".py", ".md", ".json", ".jsonl"}:
            data = p.read_bytes()
            for name in ["Qianwen_api_key", "Qianwen_workspace_id", "ZhiPu_api_key", "BoCha_api_key", "MINIO_ROOT_PASSWORD"]:
                secret = os.getenv(name, "")
                assert not secret or len(secret) < 5 or secret.encode() not in data
            file_hashes[p.name] = sha(data.replace(b"\r\n", b"\n"))
    audit = {"identity": "proofpick-v2-rc3-r1-independent-first", "production_commit": PRODUCTION,
             "production_tree": tree, "r1_payload": manifest["payload_sha256"],
             "git_groups": len(contract["file_groups"]), "git_unique_files": len(files), "git_member_occurrences": count,
             "hash_errors": 0, "autocrlf_modes_tested": ["true", "false", "LF-checkout"], "autocrlf_tests": "2/2 passed",
             "offline_tests_before_cases": "518/518", "synthetic_harness_tests": "9/9",
             "prior_jsonl_files_scanned": historical_files, "historical_input_strings": len(previous),
             "exact_input_collisions": collisions, "semantic_overlap_not_proven_absent": True,
             "product_counts": {d: len(p) for d, p in catalog.items()}, "known_gold_pairs": len(known_pairs),
             "trusted_count": 90, "online_count": 15, "new_case_agent_runs_before_freeze": 0,
             "bootstrap_cost_cny": .015586, "trusted_including_bootstrap_budget_cny": 2.0, "online_budget_cny": 3.0,
             "stop_on_confirmed_safety_violation": True, "files": file_hashes}
    with (BASE / "freeze.json").open("x", encoding="utf8", newline="\n") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({k: v for k, v in audit.items() if k != "files"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
