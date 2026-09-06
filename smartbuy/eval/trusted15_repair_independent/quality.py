"""Final file, runtime, credential and protected-ref checks; no providers."""

import json
import os
import re
import subprocess
from pathlib import Path

from .freeze import BASE, ROOT, file_hash, save
from .preflight import main as production_audit
from .run import verified_inputs


def main():
    verified_inputs()
    current = production_audit()
    assert current == json.loads((BASE / "preflight.json").read_text(encoding="utf8"))
    names = set(subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines())
    secrets = [os.getenv(key, "") for key in ["Qianwen_api_key", "Qianwen_workspace_id", "ZhiPu_api_key", "BoCha_api_key", "MINIO_ROOT_PASSWORD"]]
    checked = 0
    for name in sorted(names):
        path = ROOT / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        checked += 1
        assert not any(len(secret) >= 6 and secret.encode() in data for secret in secrets), "exact_credential_hit (suppressed)"
        assert not re.search(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|Bearer\s+[A-Za-z0-9_.-]{20,}", data), "credential_pattern (suppressed)"
    new_files = [name for name in names if name.startswith("smartbuy/eval/trusted15_repair_independent/")]
    assert not [name for name in new_files if Path(name).suffix.lower() in {".db", ".sqlite", ".sqlite3", ".pyc", ".bin", ".safetensors"}
                or Path(name).name == ".env" or "/__pycache__/" in name]
    old_diff = subprocess.check_output(["git", "diff", "--name-only", "faa1b108771959949a2f1a71937c03860685daeb", "--",
                                       "smartbuy/eval/v2_9i_independent", "smartbuy/eval/trusted79_independent",
                                       "smartbuy/eval/fact_completion_independent"], cwd=ROOT, text=True).strip()
    assert not old_diff
    expected_refs = {"refs/heads/main": "d51b6668a6a45c1b01ef4e64da3c4b9ac84ed10c",
                     "refs/tags/v1.0.0-portfolio^{}": "d51b6668a6a45c1b01ef4e64da3c4b9ac84ed10c",
                     "refs/heads/release/proofpick-v2-rc3": "033669d6c2d168dddbd712c2a54a105da53ffc1b",
                     "refs/heads/release/proofpick-v2-rc4": "e7ea993a6393c4c886be977a5eed2532d800fe26",
                     "refs/heads/fix/v2-trusted-intent-clarification": "1c7104bf8dbafd79945082200c6dc6cae9dbce5b",
                     "refs/heads/eval/v2-trusted79-continuation": "faa1b108771959949a2f1a71937c03860685daeb"}
    observed = subprocess.check_output(["git", "ls-remote", "origin", *expected_refs], cwd=ROOT, text=True)
    assert {line.split()[1]: line.split()[0] for line in observed.splitlines()} == expected_refs
    rows = [json.loads(line) for line in (BASE / "results/first.jsonl").read_text(encoding="utf8").splitlines()]
    usage = [u for r in rows for u in r["usage"]]
    output = {"production_runtime_unchanged": True, "production_member_count": current["member_count"],
              "git_blob_aggregate_sha256": current["git_blob_aggregate_sha256"], "files_scanned": checked,
              "exact_credentials_and_high_confidence_patterns": 0, "new_forbidden_artifacts": 0,
              "protected_refs": expected_refs, "old_evaluation_changes": 0,
              "raw_sha256": file_hash(BASE / "results/first.jsonl"), "phase_model_requests": len(usage),
              "phase_estimated_cost_cny": round(sum(u["estimated_cost_cny"] for u in usage), 9), "quality_model_calls": 0}
    save(BASE / "results/quality_audit.json", output)
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
