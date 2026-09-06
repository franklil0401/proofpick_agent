"""Read-only parser/coverage contrast; no Agent execution or model calls."""

import json

from smartbuy.constraints import ConstraintNormalizer
from smartbuy.decision_core.requirements import audit_requirement_coverage
from smartbuy.domain_packs import DomainPackRegistry

from .freeze import BASE, ROOT, originals, save


def main():
    case = next(c for c in originals() if c["case_id"] == "rc3i-monitor-012")
    fixture = json.loads((ROOT / "smartbuy/eval/trusted_intent_exposed_v1.json").read_text(encoding="utf8"))
    reconstructed = next(c for c in fixture["cases"] if c.get("historical_case_id") == case["case_id"])
    pack = DomainPackRegistry(ROOT / "smartbuy/domain_packs").load("monitor")
    output = {"kind": "offline_parser_diagnostic_not_agent_replay", "model_calls": 0, "cases": []}
    for label, query in [("original_independent", case["query"]), ("developer_reconstructed", reconstructed["query"])]:
        constraints = ConstraintNormalizer().build(query, source_turn=1)
        coverage = audit_requirement_coverage(query, constraints, pack, purchase=True).public()
        output["cases"].append({"label": label, "query": query,
                                "constraints": constraints.model_dump(mode="json"), "coverage": coverage})
    assert output["cases"][0]["coverage"]["complete"] is False
    assert output["cases"][1]["coverage"]["complete"] is True
    save(BASE / "results/remaining_failure_diagnostic.json", output)
    print(json.dumps({"model_calls": 0, "coverage": [{"label": c["label"], "complete": c["coverage"]["complete"]}
                                                    for c in output["cases"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
