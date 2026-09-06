"""Final independent file, runtime and credential audit; no model calls."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from smartbuy.eval.fact_completion_independent.preflight import main as production_audit

from .freeze import BASE, ROOT, file_hash, save
from .run import verified_inputs


def main():
    verified_inputs()
    production = production_audit()
    production.pop("members")
    previous = json.loads((BASE / "preflight.json").read_text(encoding="utf8"))
    assert production == previous
    names = set(subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines())
    secrets = [os.getenv(key, "") for key in ["Qianwen_api_key", "Qianwen_workspace_id", "ZhiPu_api_key", "BoCha_api_key", "MINIO_ROOT_PASSWORD"]]
    exact_hits, pattern_hits = [], []
    checked = 0
    for name in sorted(names):
        path = ROOT / name
        if not path.is_file():
            continue
        blob = path.read_bytes()
        checked += 1
        if any(len(secret) >= 6 and secret.encode() in blob for secret in secrets):
            exact_hits.append(name)
        if re.search(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|Bearer\s+[A-Za-z0-9_.-]{20,}", blob):
            pattern_hits.append(name)
    assert not exact_hits and not pattern_hits, "credential audit failed (values suppressed)"
    new_paths = [name for name in names if name.startswith("smartbuy/eval/trusted79_independent/")]
    forbidden = [name for name in new_paths if Path(name).suffix.lower() in {".db", ".sqlite", ".sqlite3", ".pyc", ".bin", ".safetensors"}
                 or "/__pycache__/" in name or Path(name).name == ".env"]
    assert not forbidden
    old_diffs = subprocess.check_output(["git", "diff", "--name-only", "f0e8989c6667e3c1e7daa5bce296189416618910", "--",
                                        "smartbuy/eval/v2_9i_independent", "smartbuy/eval/fact_completion_independent"], cwd=ROOT, text=True).splitlines()
    assert not old_diffs
    protected = subprocess.check_output(["git", "ls-remote", "origin", "refs/heads/main", "refs/heads/release/proofpick-v2-rc3",
                                         "refs/heads/release/proofpick-v2-rc4", "refs/heads/fix/v2-fact-completion", "refs/tags/v1.0.0-portfolio^{}"], cwd=ROOT, text=True)
    refs = {line.split()[1]: line.split()[0] for line in protected.splitlines()}
    assert refs == {"refs/heads/main": "d51b6668a6a45c1b01ef4e64da3c4b9ac84ed10c",
                    "refs/heads/release/proofpick-v2-rc3": "033669d6c2d168dddbd712c2a54a105da53ffc1b",
                    "refs/heads/release/proofpick-v2-rc4": "e7ea993a6393c4c886be977a5eed2532d800fe26",
                    "refs/heads/fix/v2-fact-completion": "02e97a2c793ba75dfad5ece15e5df665652808bf",
                    "refs/tags/v1.0.0-portfolio^{}": "d51b6668a6a45c1b01ef4e64da3c4b9ac84ed10c"}
    rows = [json.loads(line) for line in (BASE / "results/first.jsonl").read_text(encoding="utf8").splitlines()]
    usage = [item for row in rows for item in row["usage"]]
    output = {"production_and_runtime_unchanged": production == previous, "production_audit": production,
              "checked_files": checked, "exact_secret_hits": len(exact_hits), "credential_pattern_hits": len(pattern_hits),
              "new_forbidden_artifacts": forbidden, "old_evaluation_changes": old_diffs, "protected_refs": refs,
              "raw_sha256": file_hash(BASE / "results/first.jsonl"), "phase_model_requests": len(usage),
              "phase_model_cost_cny": round(sum(item["estimated_cost_cny"] for item in usage), 9),
              "new_model_calls_in_quality_audit": 0}
    save(BASE / "results/quality_audit.json", output)
    print(json.dumps({key: value for key, value in output.items() if key not in {"production_audit", "protected_refs"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
