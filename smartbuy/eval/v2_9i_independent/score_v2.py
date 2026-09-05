"""Authorized additive V1 citation adapter; original scorer remains immutable."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from .score import score_case, summarize, walk

BASE = Path(__file__).resolve().parent


def compatible_type(actual, expected):
    if isinstance(expected, bool):
        return isinstance(actual, bool)
    if isinstance(expected, (int, float)):
        return isinstance(actual, (int, float)) and not isinstance(actual, bool)
    return type(actual) is type(expected)


def adapt(result, catalog, domain):
    copied = copy.deepcopy(result)
    refs = {e["id"]: (p, e) for p in catalog[domain] for e in p["evidence"]}
    audit = {"json_scalar_decodes": 0, "citation_only_refs": 0, "binding_errors": []}
    for node in walk(copied.get("response", {}).get("report", {})):
        eid = node.get("evidence_id")
        if not eid or "field" not in node or "value" not in node:
            continue
        if eid not in refs:
            # Keep unrecognized IDs for separate fact-coverage failure. Never create support.
            continue
        product, ref = refs[eid]
        identity_ok = ((node.get("model_id") or node.get("product_id")) == product["id"]
                       and node.get("field") == ref["field"] and node.get("source_id") == ref["source_id"]
                       and node.get("source_url") == ref["url"]
                       and (not node.get("region") or node["region"] == ref["region"]))
        if not identity_ok:
            audit["binding_errors"].append(eid)
        raw = node["value"]
        if raw is None:
            audit["citation_only_refs"] += 1
            node.pop("value")  # Absence of an assertion contributes no factual coverage.
            continue
        if isinstance(raw, str):
            try:
                decoded = json.loads(raw)
            except (ValueError, TypeError):
                decoded = raw
            if compatible_type(decoded, ref["value"]) and decoded != raw:
                node["value"] = decoded
                audit["json_scalar_decodes"] += 1
        if not compatible_type(node["value"], ref["value"]):
            audit["binding_errors"].append(eid)
    return copied, audit


def score_case_v2(case, result, catalog):
    adapted, audit = adapt(result, catalog, case["domain"])
    score = score_case(case, adapted, catalog)
    if audit["binding_errors"]:
        score["safety"] = sorted(set(score["safety"]) | {"invalid_evidence_binding"})
        score["reasons"] = sorted(set(score["reasons"]) | {"invalid_evidence_binding"})
        score["passed"] = False
    score["adapter_audit"] = audit
    return score


def all_rows():
    rows = []
    for name in ["trusted_first.jsonl", "trusted_continuation_first.jsonl"]:
        path = BASE / "results" / name
        if path.exists():
            rows.extend(json.loads(x) for x in path.read_text(encoding="utf8").splitlines())
    assert len({r["case_id"] for r in rows}) == len(rows), "Paid case replay is prohibited"
    return rows


def main():
    cases = [json.loads(x) for x in (BASE / "trusted_cases.jsonl").read_text(encoding="utf8").splitlines()]
    catalog = json.loads((BASE / "gold_catalog.json").read_text(encoding="utf8"))
    by_id = {r["case_id"]: r for r in all_rows()}
    scores = [score_case_v2(c, by_id[c["case_id"]], catalog) for c in cases if c["case_id"] in by_id]
    output = {"scorer_revision": "v2-citation-compatibility", "summary": summarize(scores), "cases": scores}
    with (BASE / "results/trusted_scores_v2.json").open("x", encoding="utf8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(json.dumps(output["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
