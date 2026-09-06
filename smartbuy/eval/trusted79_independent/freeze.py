"""Create write-once phase artifacts before any paid execution."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from smartbuy.eval.fact_completion_independent.preflight import main as production_audit
from smartbuy.eval.v2_9i_independent.run import verify_freeze
from smartbuy.eval.v2_9i_independent.score_v2 import all_rows

BASE = Path(__file__).resolve().parent
OLD = BASE.with_name("v2_9i_independent")
ROOT = BASE.parents[2]
PRODUCTION = "02e97a2c793ba75dfad5ece15e5df665652808bf"


def stable(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def save(path, value):
    with path.open("x", encoding="utf8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main():
    verify_freeze()
    revision = json.loads((OLD / "adapter_revision_freeze.json").read_text(encoding="utf8"))
    for name, expected in revision["files"].items():
        assert file_hash(OLD / name) == expected
    cases = [json.loads(line) for line in (OLD / "trusted_cases.jsonl").read_text(encoding="utf8").splitlines()]
    used = {row["case_id"] for row in all_rows()}
    assert used == {f"rc3i-monitor-{i:03}" for i in range(1, 12)}
    selected = [case for case in cases if case["case_id"] not in used]
    assert len(cases) == 90 and len(selected) == 79
    domains = dict(Counter(case["domain"] for case in selected))
    assert domains == {"monitor": 19, "laptop": 30, "headphone": 30}
    selection = {"excluded_previously_run": sorted(used), "count": 79,
                 "domains": domains, "kinds": dict(Counter(case["kind"] for case in selected)),
                 "cases": [{"case_id": case["case_id"], "domain": case["domain"],
                            "kind": case["kind"], "case_sha256": stable(case),
                            "query_sha256": stable(case["query"]), "gold_sha256": stable(case["gold"])}
                           for case in selected]}
    audit = production_audit()
    audit.pop("members")  # Full unchanged member list is preserved in the prior preflight artifact.
    assert audit["git_blob_aggregate_sha256"] == "7bc167d9dd6744d8c9d9efaa76adad0f6402c0619dbbd18c6ef61bc5cf022816"
    save(BASE / "selection.json", selection)
    save(BASE / "preflight.json", audit)
    files = sorted(path for path in BASE.iterdir() if path.suffix in {".py", ".md", ".json"})
    frozen = {"schema": "trusted79-continuation-v1", "created_at": datetime.now(UTC).isoformat(),
              "production_commit": PRODUCTION, "production_tree": audit["production_tree"],
              "starting_evaluation_commit": "f0e8989c6667e3c1e7daa5bce296189416618910",
              "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
              "budget_cny": 3.0, "reserve_before_task_cny": 0.25, "timeout_seconds": 180,
              "planned_count": 79, "preflight_model_calls": 0,
              "original_freeze_sha256": file_hash(OLD / "freeze.json"),
              "adapter_freeze_sha256": file_hash(OLD / "adapter_revision_freeze.json"),
              "previous_full_production_preflight_sha256": file_hash(BASE.with_name("fact_completion_independent") / "preflight.json"),
              "files": {path.name: file_hash(path) for path in files},
              "gate": {"domain_pass_minimum": {"monitor": 16, "laptop": 24, "headphone": 24},
                       "micro_constraint_f1": 0.95, "recommendation_evidence": 0.95,
                       "safety_findings": 0, "all_planned_tasks_required": True}}
    save(BASE / "freeze.json", frozen)
    print(json.dumps({"selected": len(selected), "domains": domains, "kinds": selection["kinds"],
                      "freeze_sha256": file_hash(BASE / "freeze.json"), "production_check": "passed", "model_calls": 0}))


if __name__ == "__main__":
    main()
