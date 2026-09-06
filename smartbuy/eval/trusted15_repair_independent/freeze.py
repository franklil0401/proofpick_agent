"""Freeze original exposed cases and unchanged scorer before any paid retest."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from smartbuy.eval.v2_9i_independent.run import verify_freeze
from smartbuy.eval.v2_9k_independent.audit import stable

from .preflight import PRODUCTION, ROOT, TREE, main as production_audit

BASE = Path(__file__).resolve().parent
OLD = BASE.with_name("v2_9i_independent")
PRIOR = BASE.with_name("trusted79_independent")


def file_hash(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def save(path, value):
    with path.open("x", encoding="utf8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def originals():
    verify_freeze()
    for name, expected in json.loads((OLD / "adapter_revision_freeze.json").read_text(encoding="utf8"))["files"].items():
        assert file_hash(OLD / name) == expected
    assert file_hash(PRIOR / "results/first.jsonl") == "87cd927c50d09d5c65de5f452340dd0991c81d7fa972315cd116ca9e46d276d8"
    assert file_hash(PRIOR / "results/first_scores.json") == "c0fb79cf106fea2820aa7c2d459bdc1633bb685545991cad015aa941b37ae0a2"
    prior = [json.loads(line) for line in (PRIOR / "results/first.jsonl").read_text(encoding="utf8").splitlines()]
    ids = [row["case_id"] for row in prior]
    assert ids == [f"rc3i-monitor-{i:03}" for i in range(12, 27)]
    selected = []
    for line in (OLD / "trusted_cases.jsonl").read_text(encoding="utf8").splitlines():
        case = json.loads(line)
        if case["case_id"] in ids:
            selected.append(case)
    assert [case["case_id"] for case in selected] == ids
    return selected


def main():
    cases = originals()
    selection = {"status": "exposed_regression", "count": 15,
                 "kinds": dict(Counter(c["kind"] for c in cases)),
                 "cases": [{"case_id": c["case_id"], "case_sha256": stable(c),
                            "query_sha256": stable(c["query"]), "gold_sha256": stable(c["gold"])} for c in cases],
                 "remaining64_execution_authorized": False}
    save(BASE / "selection.json", selection)
    save(BASE / "preflight.json", production_audit())
    frozen = {"schema": "original-exposed15-repair-v1", "production_commit": PRODUCTION,
              "production_tree": TREE, "created_at": datetime.now(UTC).isoformat(), "planned": 15,
              "budget_cny": 1.0, "reserve_before_task_cny": 0.2, "timeout_seconds": 180,
              "files": {p.name: file_hash(p) for p in sorted(BASE.iterdir()) if p.suffix in {".py", ".md", ".json"}},
              "scorer_files": {name: file_hash(OLD / name) for name in ["freeze.json", "adapter_revision_freeze.json", "score.py", "score_v2.py"]},
              "prior_raw_sha256": file_hash(PRIOR / "results/first.jsonl"),
              "original_case_file_sha256": file_hash(OLD / "trusted_cases.jsonl"),
              "all15_pass_and_zero_safety_required": True, "model_calls_before_freeze": 0}
    save(BASE / "freeze.json", frozen)
    print(json.dumps({"freeze_sha256": file_hash(BASE / "freeze.json"), "selected": len(cases),
                      "kinds": selection["kinds"], "production": PRODUCTION, "root": ROOT.name, "model_calls": 0}))


if __name__ == "__main__":
    main()
