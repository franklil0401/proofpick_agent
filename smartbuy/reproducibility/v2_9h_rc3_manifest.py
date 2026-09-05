"""Build the RC3 semantic freeze from an immutable production commit.

The manifest deliberately separates stable release-contract bytes from runtime
telemetry.  Every aggregate includes its complete sorted member list so an
independent evaluator can reproduce the payload without knowing this machine.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from smartbuy.reproducibility.semantic_manifest import (
    build_file_group,
    build_semantic_manifest,
    stable_sha256,
)
from smartbuy.reproducibility.v2_9e_manifest import (
    DATA_PREFIXES,
    PRODUCTION_PREFIXES,
    _assert_worktree_matches,
    _git,
    _members_at,
    _select,
)


SCORING_MEMBERS = (
    "smartbuy/eval/audit_v2_9g_online_funnel.py",
    "smartbuy/eval/run_v2_9e_exposed_regression.py",
    "smartbuy/eval/run_v2_9f_online_regression.py",
    "smartbuy/eval/stage6_scoring.py",
    "smartbuy/eval/v2_6c_r2_laptop_scorer.py",
    "smartbuy/eval/v2_6c_r2_laptop_scoring_policy.json",
    "smartbuy/eval/v2_6c_r3_validation.schema.json",
    "smartbuy/eval/v2_6c_r3_validation_scorer.py",
    "smartbuy/eval/v2_8_headphone_engineering.schema.json",
    "smartbuy/eval/v2_8_headphone_engineering_policy.json",
)

EXACT_GROUPS = {
    "dependency_lock": (
        "vendor/youtu-rag/pyproject.toml",
        "vendor/youtu-rag/uv.lock",
    ),
    "prompt_contract": (
        "smartbuy/agent/ranking.py",
        "smartbuy/agent/react.py",
        "smartbuy/constraint_proposals/provider.py",
    ),
    "product_ui_and_demo_contract": (
        "smartbuy/portfolio/demos.py",
        "smartbuy/scripts/verify_v2_9a_demos.py",
        "vendor/youtu-rag/frontend/rag_webui/app.html",
        "vendor/youtu-rag/frontend/rag_webui/assets/css/portfolio.css",
        "vendor/youtu-rag/frontend/rag_webui/assets/data/proofpick-demos.json",
        "vendor/youtu-rag/frontend/rag_webui/assets/js/components/portfolio.js",
    ),
}

PREFIX_GROUPS = {
    "all_production_python": PRODUCTION_PREFIXES,
    "query_intent_product_reference_candidate_scope": (
        "smartbuy/decision_core/",
        "smartbuy/identity/",
    ),
    "constraint_resolution_clarification": (
        "smartbuy/constraint_proposals/",
    ),
    "agent_tool_orchestration": (
        "smartbuy/agent/",
        "smartbuy/orchestration/",
    ),
    "tool_schema_and_contracts": (
        "smartbuy/contracts/",
        "smartbuy/domain/",
        "smartbuy/tools/",
    ),
    "evidence_check": (
        "smartbuy/open_research/evidence_check.py",
        "smartbuy/product_packs/ledger.py",
        "smartbuy/tools/evidence_check.py",
    ),
    "constraint_checker": (
        "smartbuy/constraints/",
    ),
    "ranker": (
        "smartbuy/ranking/",
    ),
    "memory": (
        "smartbuy/memory/",
    ),
    "product_pack_contract_and_runtime": (
        "smartbuy/product_packs/",
    ),
}


def _group(
    root: Path,
    commit: str,
    files: list[str],
    *,
    prefixes: tuple[str, ...] = (),
    exact: tuple[str, ...] = (),
    suffixes: tuple[str, ...] = (),
) -> dict[str, object]:
    members = _select(files, prefixes=prefixes, exact=exact, suffixes=suffixes)
    _assert_worktree_matches(root, commit, members)
    return build_file_group(root, members)


def build_rc3_manifest(root: Path, production_commit: str) -> dict[str, object]:
    root = root.resolve()
    commit = _git(root, "rev-parse", f"{production_commit}^{{commit}}")
    tree = _git(root, "rev-parse", f"{commit}^{{tree}}")
    files = _members_at(root, commit)

    groups: dict[str, dict[str, object]] = {}
    for name, members in EXACT_GROUPS.items():
        groups[name] = _group(root, commit, files, exact=members)
    for name, prefixes in PREFIX_GROUPS.items():
        groups[name] = _group(
            root,
            commit,
            files,
            prefixes=prefixes,
            suffixes=(".py", ".json"),
        )
    groups["open_research_source_search_beta"] = _group(
        root,
        commit,
        files,
        prefixes=("smartbuy/open_research/", "smartbuy/source_search/"),
        exact=(
            "smartbuy/api/portfolio_runtime.py",
            "smartbuy/providers/zhipu_search.py",
            "smartbuy/tools/source_search.py",
            "smartbuy/tools/web_extractor.py",
            "smartbuy/tools/web_search.py",
        ),
        suffixes=(".py", ".json"),
    )
    groups["domain_pack_config"] = _group(
        root,
        commit,
        files,
        prefixes=("smartbuy/domain_packs/",),
        suffixes=(".json",),
    )
    groups["governed_data"] = _group(
        root,
        commit,
        files,
        prefixes=DATA_PREFIXES,
    )
    groups["scoring_interface"] = _group(
        root,
        commit,
        files,
        exact=SCORING_MEMBERS,
    )
    groups["test_baseline"] = _group(
        root,
        commit,
        files,
        prefixes=("smartbuy/tests/",),
        exact=(".github/workflows/ci.yml",),
    )
    groups["windows_scripts"] = _group(
        root,
        commit,
        files,
        prefixes=("smartbuy/scripts/",),
        suffixes=(".ps1",),
    )

    runtime = {
        "production_commit": commit,
        "production_tree": tree,
        "domains": [
            {
                "domain_id": "monitor",
                "domain_pack_version": "1.0.0",
                "data_version": "monitor-cn-2026-08-26-v1",
                "index_version": "monitor-fact-card-h2-v1",
                "collection_name": "smartbuy_monitors_v1",
                "document_count": 60,
                "embedding_model": "text-embedding-v4",
                "embedding_dimensions": 1024,
                "data_logical_sha256": "079c4f745e8dbbb538fe7cdacf5479f4e25ebc38972ef2175edf8876a35e8ffe",
            },
            {
                "domain_id": "laptop",
                "domain_pack_version": "1.0.0",
                "data_version": "laptop-governed-2026-09-02-v1",
                "index_version": "laptop-governed-2026-09-02-v1-embedding1024-v1",
                "collection_name": "proofpick_laptop_v2_4e6d332c11bf8f7c",
                "document_count": 12,
                "embedding_model": "text-embedding-v4",
                "embedding_dimensions": 1024,
                "data_logical_sha256": "13cf9fffa9383921ed29a1e426da6a199edb699ec346aee985ecf21c9918f8b1",
            },
            {
                "domain_id": "headphone",
                "domain_pack_version": "1.0.0",
                "data_version": "headphone-governed-2026-09-03-v1",
                "index_version": "headphone-governed-2026-09-03-v1-embedding1024-v1",
                "collection_name": "proofpick_headphone_v2_cae477364b46ccae",
                "document_count": 12,
                "embedding_model": "text-embedding-v4",
                "embedding_dimensions": 1024,
                "data_logical_sha256": "c1edf981e00f6ad15b409d1d4ea37b2c8e2dc6dd36b95ce4be99ac57693fc40a",
            },
        ],
        "scoring_contract_sha256": groups["scoring_interface"]["aggregate_sha256"],
        "test_baseline_sha256": groups["test_baseline"]["aggregate_sha256"],
        "runtime_audit": {
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "release_candidate": "proofpick-v2-rc3",
            "release_scope": "Trusted Multi-domain Decision Core + Experimental/Beta Online Research",
            "default_mode": "trusted",
            "machine_path": "excluded_from_semantic_contract",
            "latency_token_cost": "excluded_from_semantic_contract",
        },
    }
    manifest = build_semantic_manifest(runtime, file_groups=groups)
    manifest["semantic_contract"]["release_contract"] = {
        "release_candidate": "proofpick-v2-rc3",
        "positioning": "Trusted Multi-domain Decision Core + Experimental/Beta Online Research",
        "default_mode": "trusted",
        "trusted_capabilities": [
            "domain_and_product_packs",
            "agent_tool_orchestration",
            "product_query_and_text2sql",
            "kb_embedding_reranker",
            "multi_hop_evidence_retrieval",
            "four_state_evidence",
            "constraint_checker",
            "deterministic_ranker",
            "layered_memory",
            "active_clarification",
            "monotonic_candidate_scope",
            "windows_local_reproduction",
        ],
        "experimental_capabilities": [
            "source_search",
            "web_extractor",
            "request_scoped_open_evidence",
            "online_research",
        ],
        "trusted_release_gates": {
            "per_domain_task_accuracy_min": 0.80,
            "hard_constraint_f1_min": 0.95,
            "recommended_fact_evidence_coverage_min": 0.95,
            "wrong_configuration_recommendations_max": 0,
            "wrong_region_recommendations_max": 0,
            "scope_checker_report_leakage_max": 0,
            "unknown_overclaim_max": 0,
            "clarification_bypass_max": 0,
            "open_evidence_in_trusted_checker_max": 0,
        },
        "online_safety_gates": {
            "invalid_domain_model_configuration_region_usable_max": 0,
            "search_snippet_to_evidence_max": 0,
            "open_evidence_in_trusted_checker_max": 0,
            "unknown_presented_as_verified_max": 0,
            "ssrf_or_off_allowlist_redirect_accepted_max": 0,
        },
        "online_completion_metrics_release_blocking": False,
    }
    manifest["payload_sha256"] = stable_sha256(manifest["semantic_contract"])
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--production-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_rc3_manifest(args.root, args.production_commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(payload["payload_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
