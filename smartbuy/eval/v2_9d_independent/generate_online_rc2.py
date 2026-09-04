"""Create the evaluator-only Online RC2 after the documented length-contract abort."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "online_cases.jsonl"
TARGET = HERE / "online_cases_rc2.jsonl"
MANIFEST = HERE / "online_case_manifest_rc2.json"
CHANGES = {
    "web2-lap-004": "Lenovo Yoga Pro 9i 16IAH10 official US display memory weight",
    "web2-hph-002": "Bose QC Ultra Headphones 2nd Gen official US battery Bluetooth ANC",
}
COMPLETED_PREFIX = 8


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    source: list[dict[str, Any]] = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line]
    target = json.loads(json.dumps(source))
    changed: list[str] = []
    for index, row in enumerate(target):
        if row["case_id"] in CHANGES:
            if index < COMPLETED_PREFIX:
                raise RuntimeError("cannot modify a completed Online case")
            row["query"] = CHANGES[row["case_id"]]
            changed.append(row["case_id"])
    if set(changed) != set(CHANGES):
        raise RuntimeError("expected RC2 edits were not applied")
    if target[:COMPLETED_PREFIX] != source[:COMPLETED_PREFIX]:
        raise RuntimeError("completed Online prefix changed")
    for old, new in zip(source, target, strict=True):
        old_copy, new_copy = dict(old), dict(new)
        old_query, new_query = old_copy.pop("query"), new_copy.pop("query")
        if old_copy != new_copy:
            raise RuntimeError(f"non-query definition changed: {old['case_id']}")
        if old["case_id"] not in CHANGES and old_query != new_query:
            raise RuntimeError(f"unexpected query edit: {old['case_id']}")
        if len(new_query) > 70:
            raise RuntimeError(f"query still exceeds production contract: {old['case_id']}")
    TARGET.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in target),
        encoding="utf-8", newline="\n",
    )
    manifest = {
        "schema_version": "proofpick-v2-9d-independent-online-rc2-freeze-v1",
        "classification": "evaluator-only correction after immutable harness failure",
        "case_count": len(target), "domain_counts": {domain: sum(row["domain_id"] == domain for row in target) for domain in ("monitor", "laptop", "headphone")},
        "base_case_sha256": _sha(SOURCE), "case_sha256": _sha(TARGET),
        "completed_prefix_count": COMPLETED_PREFIX, "completed_prefix_unchanged": True,
        "changed_unreached_case_ids": sorted(changed), "gold_fields_changed": 0,
        "evaluation_state": "frozen_partially_executed_after_harness_abort",
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
