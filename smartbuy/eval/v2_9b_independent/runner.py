"""Freeze and execute the independent ProofPick V2-9B release evaluation.

The runner never modifies production code, prompts, Domain/Product Packs,
indices, or historical results.  Journals live outside Git; first aggregate
results are immutable once written.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import jsonschema

from smartbuy.agent import DomainDecisionAgent, PurchaseDecisionAgent
from smartbuy.config import load_bailian_settings
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.constraints import ConstraintProvenance
from smartbuy.constraints.verifier import CandidateConstraintVerifier
from smartbuy.domain_packs import DomainPackLoader
from smartbuy.memory import DomainPreferenceMemoryStore, LongTermPreferenceStore, SessionMemoryStore
from smartbuy.open_research import OpenResearchService, OpenResearchSettings, StaticHTMLExtractor, TemporaryEvidenceStore
from smartbuy.orchestration import ReactOrchestrator
from smartbuy.orchestration.contracts import OrchestratorRequest
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.providers import BailianProvider, RetryPolicy, ZhipuSourceSearchProvider
from smartbuy.retrieval.domain_index import DomainIndexManager
from smartbuy.source_search import SourceSearchRequest, SourceSearchSettings, SourceSearchTriggerReason
from smartbuy.tools import EvidenceCheckTool, KBSearchTool, Text2SQLTool, WebSearchTool
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainKBSearchTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)

from .scorer import score_online, score_trusted


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CASES = HERE / "trusted_cases.jsonl"
ONLINE_CASES = HERE / "online_cases.jsonl"
CASE_MANIFEST = HERE / "case_manifest.json"
TRUSTED_SCHEMA = HERE / "trusted_case.schema.json"
ONLINE_SCHEMA = HERE / "online_case.schema.json"
POLICY = HERE / "scoring_policy.json"
SCORER = HERE / "scorer.py"
RUNNER = HERE / "runner.py"
RC_MANIFEST = ROOT / "smartbuy/docs/v2/v2_release_candidate_manifest.md"
PRODUCTION_COMMIT = "dac24123b82683c6708f0d487d9ab9753b172aed"
RC_COMMIT = "383df1783328ad6859729c6770fb1a8cea3f648b"
V1_COMMIT = "d51b6668a6a45c1b01ef4e64da3c4b9ac84ed10c"
MAX_TRUSTED_PROVIDER_REQUESTS = 500
MAX_TRUSTED_COST_CNY = 10.0
MAX_ONLINE_SEARCH_REQUESTS = 30
MAX_ONLINE_COST_CNY = 2.0


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _validate_cases() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    manifest = json.loads(CASE_MANIFEST.read_text(encoding="utf-8"))
    trusted = _load_jsonl(CASES)
    online = _load_jsonl(ONLINE_CASES)
    trusted_schema = json.loads(TRUSTED_SCHEMA.read_text(encoding="utf-8"))
    online_schema = json.loads(ONLINE_SCHEMA.read_text(encoding="utf-8"))
    for row in trusted:
        jsonschema.validate(row, trusted_schema)
    for row in online:
        jsonschema.validate(row, online_schema)
    if (
        len(trusted) != 90
        or len(online) != 15
        or _sha(CASES) != manifest["trusted_case_sha256"]
        or _sha(ONLINE_CASES) != manifest["online_case_sha256"]
        or manifest["first_run_completed"] is not False
        or any(row["evaluation_state"] != "frozen_unrun" or row["run_count"] != 0 for row in [*trusted, *online])
    ):
        raise RuntimeError("independent evaluation freeze is invalid")
    for domain in ("monitor", "laptop", "headphone"):
        if sum(row["domain_id"] == domain for row in trusted) != 30:
            raise RuntimeError(f"trusted domain count changed: {domain}")
        if sum(row["domain_id"] == domain for row in online) != 5:
            raise RuntimeError(f"online domain count changed: {domain}")
    return trusted, online, manifest


def _outside_repo(path: Path) -> Path:
    value = path.resolve()
    try:
        value.relative_to(ROOT.resolve())
    except ValueError:
        return value
    raise ValueError("runtime and journal paths must remain outside Git")


def _runtime_contract(runtime_root: Path) -> dict[str, Any]:
    monitor_root = runtime_root / "monitor"
    monitor_db = monitor_root / "smartbuy_monitors_v1.sqlite"
    monitor_index = monitor_root / "vector_store_text_embedding_v4_1024"
    if not monitor_db.is_file() or not (monitor_index / "chroma.sqlite3").is_file():
        raise RuntimeError("Monitor runtime is incomplete")
    domains: dict[str, Any] = {}
    for domain in ("laptop", "headphone"):
        pack_path = ROOT / "smartbuy/domain_packs" / domain
        pack = DomainPackLoader().load(pack_path)
        manager = DomainProductPackManager(runtime_root / "v2" / domain / "data", domain_pack_path=pack_path)
        snapshot = manager.current()
        index = DomainIndexManager(
            runtime_root / "v2" / domain / "index",
            data_manager=manager,
            domain_id=domain,
            domain_pack_version=pack.version,
        ).current()
        if index.data_version != snapshot.data_version or index.manifest.get("embedding_dimensions") != 1024:
            raise RuntimeError(f"{domain} Data/Index contract mismatch")
        domains[domain] = {
            "domain_pack_version": pack.version,
            "domain_pack_fingerprint": pack.fingerprint,
            "data_version": snapshot.data_version,
            "data_manifest_hash": snapshot.manifest_hash,
            "data_counts": snapshot.manifest["counts"],
            "index_version": index.index_version,
            "index_manifest_hash": index.manifest_hash,
            "collection_name": index.collection_name,
            "document_count": index.manifest["document_count"],
            "chunk_count": index.manifest["chunk_count"],
        }
    return {
        "monitor": {
            "database_sha256": _sha(monitor_db),
            "index_manifest_sha256": _sha(monitor_root / "index_manifest.json"),
        },
        **domains,
    }


def _definition_hashes() -> dict[str, str]:
    files = (CASES, ONLINE_CASES, CASE_MANIFEST, TRUSTED_SCHEMA, ONLINE_SCHEMA, POLICY, SCORER, RUNNER)
    return {path.relative_to(ROOT).as_posix(): _sha(path) for path in files}


def _rc_payload(runtime_root: Path) -> dict[str, Any]:
    _validate_cases()
    if _git("rev-parse", f"{RC_COMMIT}^{{commit}}") != RC_COMMIT:
        raise RuntimeError("V2-9A RC commit is unavailable")
    if _git("rev-parse", "v1.0.0-portfolio^{commit}") != V1_COMMIT:
        raise RuntimeError("V1 tag moved")
    production_tree = _git("rev-parse", f"{PRODUCTION_COMMIT}^{{tree}}")
    return {
        "schema_version": "proofpick-v2-9b-independent-rc-v1",
        "release_candidate": "proofpick-v2-9a-rc1",
        "production_commit": PRODUCTION_COMMIT,
        "production_tree": production_tree,
        "rc_manifest_commit": RC_COMMIT,
        "rc_manifest_sha256": _sha(RC_MANIFEST),
        "v1_commit": V1_COMMIT,
        "definitions": _definition_hashes(),
        "runtime": _runtime_contract(runtime_root),
        "orchestrator": "react",
        "cache": "cold_disabled",
        "limits": {
            "trusted_provider_requests": MAX_TRUSTED_PROVIDER_REQUESTS,
            "trusted_cost_cny": MAX_TRUSTED_COST_CNY,
            "online_search_requests": MAX_ONLINE_SEARCH_REQUESTS,
            "online_cost_cny": MAX_ONLINE_COST_CNY,
        },
    }


def _atomic(path: Path, payload: Any) -> None:
    if path.exists():
        raise RuntimeError(f"immutable output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)


def freeze_rc(runtime_root: Path, output: Path) -> dict[str, Any]:
    payload = _rc_payload(runtime_root)
    payload["run_id"] = f"v2-9b-independent-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    payload["frozen_at"] = _now()
    payload["config_sha256"] = _stable_hash(payload)
    _atomic(output, payload)
    return payload


def _assert_rc(runtime_root: Path, rc_path: Path) -> dict[str, Any]:
    rc = json.loads(rc_path.read_text(encoding="utf-8"))
    current = _rc_payload(runtime_root)
    comparable = {key: value for key, value in rc.items() if key not in {"run_id", "frozen_at", "config_sha256"}}
    if current != comparable:
        raise RuntimeError("evaluation definitions, production RC, or runtime changed after freeze")
    check_payload = {**comparable, "run_id": rc["run_id"], "frozen_at": rc["frozen_at"]}
    if _stable_hash(check_payload) != rc["config_sha256"]:
        raise RuntimeError("independent RC hash is invalid")
    return rc


def _active_constraints(report: Any) -> list[dict[str, Any]]:
    return [
        {
            "field": item.field,
            "operator": item.operator.value,
            "value": item.normalized_value,
            "unit": item.unit,
        }
        for item in report.constraint_set.active(hard_only=True, supported_only=True)
        if item.provenance != ConstraintProvenance.SYSTEM_DEFAULT
    ]


def _row(case: dict[str, Any], report: Any, wall_ms: float, api_events: list[dict[str, Any]]) -> dict[str, Any]:
    scope = report.product_scope
    checker = report.constraint_verification
    candidates = [
        {
            "product_id": item.model_id,
            "eligible": item.eligible,
            "unknown_fields": item.unknown_fields,
            "conflict_fields": item.conflict_fields,
            "region": item.region,
            "configuration_id": item.configuration_id,
        }
        for item in report.candidates
    ]
    evidence = [
        {
            "evidence_id": item.evidence_id,
            "product_id": item.model_id,
            "field_id": item.field,
            "status": "matched",
            "source_id": item.source_id,
            "region": item.region,
            "configuration_id": item.configuration_id,
        }
        for item in report.evidence
    ]
    public_ids = sorted({
        *report.recommended_model_ids,
        *report.eliminated_model_ids,
        *(item.model_id for item in report.candidates),
        *(item.model_id for item in report.evidence),
    })
    return {
        "case_id": case["case_id"],
        "domain_id": case["domain_id"],
        "recommended_product_ids": report.recommended_model_ids,
        "active_hard_constraints": _active_constraints(report),
        "evidence": evidence,
        "candidates": candidates,
        "scope_product_ids": scope.product_ids if scope else [],
        "scope_envelope_present": scope is not None,
        "checker_candidate_product_ids": checker.candidate_pool_model_ids if checker else [],
        "checker_eligible_product_ids": checker.eligible_model_ids if checker else [],
        "checker_degraded": checker.degraded if checker else True,
        "public_product_ids": public_ids,
        "clarification_state": report.clarification_state.value,
        "abstained": report.abstained,
        "tools_used": report.tools_used,
        "tool_call_count": report.tool_call_count,
        "degraded_states": report.degraded_states,
        "wall_latency_ms": wall_ms,
        "api_events": api_events,
        "report": report.model_dump(mode="json"),
    }


def _append_journal(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _journal(path: Path, run_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = _load_jsonl(path)
    if any(row.get("run_id") != run_id for row in rows):
        raise RuntimeError("journal belongs to a different run")
    ids = [row["case_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("journal contains duplicate completed cases")
    return rows


def _monitor_agent(runtime_root: Path, provider: BailianProvider) -> PurchaseDecisionAgent:
    monitor_root = runtime_root / "monitor"
    database = monitor_root / "smartbuy_monitors_v1.sqlite"
    settings = load_bailian_settings()
    tools = {
        "text2sql": Text2SQLTool(database),
        "kb_search": KBSearchTool(settings, provider, index_dir=monitor_root / "vector_store_text_embedding_v4_1024"),
        "evidence_check": EvidenceCheckTool(database),
        "web_search": WebSearchTool(),
    }
    return PurchaseDecisionAgent(
        provider,
        tools,
        session_memory=SessionMemoryStore(),
        preference_memory=LongTermPreferenceStore(runtime_root / "evaluation" / "monitor-preferences.json"),
        constraint_verifier=CandidateConstraintVerifier(database),
        enable_constraint_checker=True,
    )


def _domain_agent(domain: str, runtime_root: Path, provider: BailianProvider) -> DomainDecisionAgent:
    pack_path = ROOT / "smartbuy/domain_packs" / domain
    pack = DomainPackLoader().load(pack_path)
    manager = DomainProductPackManager(runtime_root / "v2" / domain / "data", domain_pack_path=pack_path)
    snapshot = manager.current()
    index = DomainIndexManager(
        runtime_root / "v2" / domain / "index",
        data_manager=manager,
        domain_id=domain,
        domain_pack_version=pack.version,
    )
    repository = DomainReadonlyRepository(snapshot, pack)
    return DomainDecisionAgent(
        pack,
        repository,
        DomainProductQueryTool(repository),
        DomainEvidenceCheckTool(repository),
        DomainConstraintCheckerTool(repository),
        NaturalConstraintEngine(pack),
        DomainPreferenceMemoryStore(runtime_root / "evaluation" / f"{domain}-memory", pack),
        kb_search=DomainKBSearchTool(index, provider),
        max_steps=8,
        max_tool_calls=12,
    )


async def run_trusted(runtime_root: Path, rc_path: Path, journal_path: Path, output: Path) -> dict[str, Any]:
    cases, _, _ = _validate_cases()
    rc = _assert_rc(runtime_root, rc_path)
    completed = _journal(journal_path, rc["run_id"])
    expected_prefix = [row["case_id"] for row in cases[:len(completed)]]
    if [row["case_id"] for row in completed] != expected_prefix:
        raise RuntimeError("journal is not a prefix of the frozen case order")
    rows = [row["result"] for row in completed]
    retry = RetryPolicy(max_retries=2, base_delay_seconds=0.25, max_delay_seconds=2.0)
    async with BailianProvider(load_bailian_settings(), timeout_seconds=30, retry_policy=retry) as provider:
        monitor = ReactOrchestrator(_monitor_agent(runtime_root, provider))
        domain_agents = {
            domain: ReactOrchestrator(_domain_agent(domain, runtime_root, provider))
            for domain in ("laptop", "headphone")
        }
        for sequence, case in enumerate(cases[len(rows):], start=len(rows) + 1):
            before = len(provider.ledger.snapshot())
            total_cost = sum(float(item["estimated_cost_cny"]) for item in provider.ledger.snapshot())
            if before >= MAX_TRUSTED_PROVIDER_REQUESTS or total_cost >= MAX_TRUSTED_COST_CNY:
                raise RuntimeError("trusted evaluation provider budget exhausted")
            orchestrator = monitor if case["domain_id"] == "monitor" else domain_agents[case["domain_id"]]
            prefix = {"monitor": "显示器：", "laptop": "笔记本：", "headphone": "耳机："}[case["domain_id"]]
            started = time.perf_counter()
            result = await orchestrator.run(OrchestratorRequest(
                query=prefix + case["question"],
                session_id=f"{rc['run_id']}-{case['case_id']}",
                user_id=f"independent-{case['case_id']}",
                thread_id=f"{rc['run_id']}-{case['case_id']}",
            ))
            if result.report is None:
                raise RuntimeError(f"no report for {case['case_id']}")
            api_events = provider.ledger.snapshot()[before:]
            row = _row(case, result.report, (time.perf_counter() - started) * 1000, api_events)
            _append_journal(journal_path, {
                "run_id": rc["run_id"], "sequence": sequence,
                "case_id": case["case_id"], "completed_at": _now(), "result": row,
            })
            rows.append(row)
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    scoring = score_trusted(cases, rows, policy)
    events = [event for row in rows for event in row["api_events"]]
    latencies = [float(row["wall_latency_ms"]) for row in rows]
    payload = {
        "schema_version": "proofpick-v2-9b-independent-trusted-first-v1",
        "classification": "immutable first run on independently frozen cases",
        "run_id": rc["run_id"],
        "run_number": 1,
        "created_at": _now(),
        "rc_config_sha256": rc["config_sha256"],
        "case_sha256": _sha(CASES),
        "checkpoint_resumed": bool(completed),
        "completed_cases_replayed": 0,
        "scoring": scoring,
        "latency": {
            "average_ms": statistics.mean(latencies),
            "p95_ms": sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)],
        },
        "api": {
            "request_count": len(events),
            "by_model": {model: sum(item["model"] == model for item in events) for model in sorted({item["model"] for item in events})},
            "input_tokens": sum(int(item["input_tokens"]) for item in events),
            "output_tokens": sum(int(item["output_tokens"]) for item in events),
            "estimated_cost_cny": sum(float(item["estimated_cost_cny"]) for item in events),
            "retry_count": sum(max(0, int(item["attempts"]) - 1) for item in events),
            "failed_requests": sum(not item["success"] for item in events),
        },
        "cases": rows,
    }
    _atomic(output, payload)
    return payload


def _host_allowed(host: str | None, allowed: list[str]) -> bool:
    if not host:
        return False
    value = host.casefold().rstrip(".")
    return any(value == domain.casefold() or value.endswith("." + domain.casefold()) for domain in allowed)


async def run_online(runtime_root: Path, rc_path: Path, output: Path) -> dict[str, Any]:
    _, cases, _ = _validate_cases()
    rc = _assert_rc(runtime_root, rc_path)
    key = os.getenv("ZhiPu_api_key", "").strip()
    if not key:
        raise RuntimeError("ZhiPu_api_key is missing")
    configured_domains = tuple(sorted({domain for case in cases for domain in case["allowed_domains"]}))
    settings = SourceSearchSettings(
        enabled=True,
        api_key=key,
        configured_domains=configured_domains,
        max_search_calls=2,
        max_cost_cny=1.0,
    )
    provider = ZhipuSourceSearchProvider(settings)
    rows: list[dict[str, Any]] = []
    try:
        for case in cases:
            search = await provider.search(SourceSearchRequest(
                query=case["query"],
                product_category=case["domain_id"],
                target_model=case["target_model"],
                target_fields=case["target_fields"],
                region=case["region"],
                allowed_domains=case["allowed_domains"],
                max_results=5,
                trigger_reason=SourceSearchTriggerReason.EXPLICIT_USER_REQUEST,
            ))
            candidate = next(iter(search.usable_candidates), None)
            base: dict[str, Any] = {
                "case_id": case["case_id"],
                "domain_id": case["domain_id"],
                "search_executed": search.search_executed,
                "network_executed": search.network_executed,
                "search_status": search.status.value,
                "search_attempt_count": len(search.attempts),
                "accepted_candidate_count": int(candidate is not None),
                "accepted_domain_valid": bool(candidate and _host_allowed(candidate.hostname, case["allowed_domains"])),
                "accepted_model_valid": bool(candidate and candidate.status.value == "region_matched" and candidate.target_model == case["target_model"]),
                "accepted_region_valid": bool(candidate and candidate.status.value == "region_matched" and candidate.target_region == case["region"] and candidate.observed_region == case["region"]),
                "evidence_count": 0,
                "lineage_complete": True,
                "open_boundary_intact": True,
                "trusted_eligible": False,
                "checker_entry_count": 0,
                "terminal_status": search.status.value,
                "source": None,
                "verified_fields": [],
                "unknown_fields": case["target_fields"],
                "conflict_fields": [],
            }
            if candidate is not None:
                pack = DomainPackLoader().load(ROOT / "smartbuy/domain_packs" / case["domain_id"])
                research_settings = OpenResearchSettings(
                    enabled=True,
                    evidence_root=runtime_root / "online" / case["case_id"] / "temporary-evidence",
                )
                service = OpenResearchService(
                    research_settings,
                    pack,
                    StaticHTMLExtractor(research_settings),
                    TemporaryEvidenceStore(research_settings.evidence_root),
                )
                try:
                    outcome = await service.research(
                        candidate,
                        target_fields=case["target_fields"],
                        allowed_domains=case["allowed_domains"],
                        provisional_product_id=f"{case['domain_id']}-{case['target_model'].casefold().replace(' ', '-')}-open",
                        configuration=case["target_model"],
                        user_id="v2-9b-independent",
                        session_id=case["case_id"],
                        thread_id=case["case_id"],
                        request_id=case["case_id"],
                        allow_region_discovery=True,
                    )
                finally:
                    await service.aclose()
                evidence = list(outcome.evidence)
                base.update({
                    "terminal_status": outcome.report.status,
                    "source": {
                        "url": candidate.url,
                        "hostname": candidate.hostname,
                        "title": candidate.title,
                        "observed_region": candidate.observed_region,
                    },
                    "evidence_count": len(evidence),
                    "lineage_complete": all(
                        item.source_url and item.source_region and item.observed_at and item.content_hash
                        for item in evidence
                    ),
                    "open_boundary_intact": all(
                        item.evidence_scope == "open" and item.usable_for_trusted_checker is False
                        for item in evidence
                    ),
                    "trusted_eligible": outcome.report.trusted_eligible,
                    "checker_entry_count": 0,
                    "verified_fields": outcome.report.verified_fields,
                    "unknown_fields": outcome.report.unknown_fields,
                    "conflict_fields": outcome.report.conflict_fields,
                    "extraction": {
                        "status": outcome.extraction.status,
                        "final_url": outcome.extraction.final_url,
                        "detected_region": outcome.extraction.detected_region,
                        "fetched_at": outcome.extraction.fetched_at,
                        "content_hash": outcome.extraction.content_hash,
                    },
                })
            rows.append(base)
            summary = provider.ledger.summary()
            if summary["request_count"] > MAX_ONLINE_SEARCH_REQUESTS or summary["estimated_cost_cny"] > MAX_ONLINE_COST_CNY:
                raise RuntimeError("online evaluation budget exhausted")
    finally:
        await provider.aclose()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    scoring = score_online(cases, rows, policy)
    payload = {
        "schema_version": "proofpick-v2-9b-independent-online-first-v1",
        "classification": "immutable first online run on independently frozen cases",
        "run_id": rc["run_id"],
        "run_number": 1,
        "created_at": _now(),
        "rc_config_sha256": rc["config_sha256"],
        "case_sha256": _sha(ONLINE_CASES),
        "scoring": scoring,
        "api": provider.ledger.summary(),
        "cases": rows,
    }
    _atomic(output, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--rc", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--freeze-rc", action="store_true")
    action.add_argument("--run-trusted-once", action="store_true")
    action.add_argument("--run-online-once", action="store_true")
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    runtime_root = _outside_repo(args.runtime_root)
    if args.freeze_rc:
        payload = freeze_rc(runtime_root, args.rc)
        print(json.dumps({"status": "frozen", "run_id": payload["run_id"], "config_sha256": payload["config_sha256"]}, ensure_ascii=False))
        return 0
    if args.output is None:
        parser.error("run actions require --output")
    if args.run_trusted_once:
        if args.journal is None:
            parser.error("--run-trusted-once requires --journal")
        payload = asyncio.run(run_trusted(runtime_root, args.rc, _outside_repo(args.journal), args.output))
        print(json.dumps({"status": "completed", "scoring": payload["scoring"]["metrics"], "api": payload["api"]}, ensure_ascii=False))
        return 0
    payload = asyncio.run(run_online(runtime_root, args.rc, args.output))
    print(json.dumps({"status": "completed", "scoring": payload["scoring"]["metrics"], "api": payload["api"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
