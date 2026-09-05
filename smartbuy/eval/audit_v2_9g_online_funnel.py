"""Recompute the exposed Online result as a monotonic task-level funnel.

The V2-9F report aggregated each stage independently across candidate branches.
This audit keeps task and candidate denominators separate and only lets a task
advance when one candidate lineage satisfies every preceding stage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


STAGES = (
    "source_search",
    "official_domain_filter",
    "model_match",
    "target_region_validation",
    "page_fetch",
    "content_extraction",
    "field_normalization",
    "evidence_check",
    "actual_evidence_completion",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_cases(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows[row["case_id"]] = row
    return rows


def _is_2xx(item: dict[str, Any]) -> bool:
    status = item.get("http_status")
    return isinstance(status, int) and 200 <= status < 300


def _operation_region_valid(
    item: dict[str, Any], candidate_status: str, target_region: str
) -> bool:
    detected = item.get("detected_region") or "unknown"
    if detected != "unknown":
        return detected == target_region
    return candidate_status == "region_matched"


def _lineage_flags(
    attempt: dict[str, Any], target_region: str
) -> dict[str, bool]:
    candidate_status = str(attempt.get("candidate_status") or "")
    operations = list(attempt.get("extractions") or [])
    region_valid = candidate_status == "region_matched" or any(
        item.get("status") == "success"
        and item.get("detected_region") == target_region
        for item in operations
    )
    fetched = any(
        _is_2xx(item)
        and _operation_region_valid(item, candidate_status, target_region)
        for item in operations
    )
    extracted = any(
        _is_2xx(item)
        and int(item.get("snippet_count") or 0) > 0
        and _operation_region_valid(item, candidate_status, target_region)
        for item in operations
    )
    normalized = extracted and int(attempt.get("evidence_count") or 0) > 0
    return {
        "target_region_validation": region_valid,
        "page_fetch": region_valid and fetched,
        "content_extraction": region_valid and fetched and extracted,
        "field_normalization": region_valid and fetched and extracted and normalized,
        "evidence_check": region_valid and fetched and extracted and normalized,
        "actual_evidence_completion": region_valid
        and fetched
        and extracted
        and normalized,
    }


def audit(result: dict[str, Any], cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    candidate_totals = {
        "candidate_branches": 0,
        "extraction_operations": 0,
        "page_fetch_2xx_all_branches": 0,
        "content_extraction_all_branches": 0,
        "target_region_valid_branches": 0,
        "page_fetch_on_target_region_branch": 0,
        "content_extraction_on_target_region_branch": 0,
        "page_fetch_outside_target_region_branch": 0,
    }
    for row in result["cases"]:
        case_id = row["case_id"]
        if case_id not in cases:
            raise ValueError(f"missing case definition: {case_id}")
        target_region = cases[case_id]["region"]
        attempts = list(row.get("extraction_attempts") or [])
        lineage = [_lineage_flags(item, target_region) for item in attempts]
        source = bool(row.get("search_executed"))
        official = source and any(
            int(item.get("domain_matched_count") or 0) > 0
            for item in row.get("search_attempts") or []
        )
        model = official and any(
            int(item.get("model_matched_count") or 0) > 0
            for item in row.get("search_attempts") or []
        )
        flags = {
            "source_search": source,
            "official_domain_filter": official,
            "model_match": model,
        }
        for stage in STAGES[3:]:
            flags[stage] = model and any(item[stage] for item in lineage)
        first_failure = next((stage for stage in STAGES if not flags[stage]), None)

        all_operations = [
            operation
            for attempt in attempts
            for operation in attempt.get("extractions") or []
        ]
        fetched_all = any(_is_2xx(item) for item in all_operations)
        fetched_target = flags["page_fetch"]
        rows.append(
            {
                "case_id": case_id,
                "domain_id": row["domain_id"],
                "target_region": target_region,
                "stage_pass": flags,
                "first_failure_stage": first_failure,
                "candidate_branch_count": len(attempts),
                "has_multiple_candidate_branches": len(attempts) > 1,
                "page_fetch_any_branch": fetched_all,
                "page_fetch_on_target_region_lineage": fetched_target,
                "page_fetch_only_outside_target_region_lineage": fetched_all
                and not fetched_target,
            }
        )

        candidate_totals["candidate_branches"] += len(attempts)
        candidate_totals["extraction_operations"] += len(all_operations)
        candidate_totals["page_fetch_2xx_all_branches"] += sum(
            _is_2xx(item) for item in all_operations
        )
        candidate_totals["content_extraction_all_branches"] += sum(
            _is_2xx(item) and int(item.get("snippet_count") or 0) > 0
            for item in all_operations
        )
        candidate_totals["target_region_valid_branches"] += sum(
            item["target_region_validation"] for item in lineage
        )
        candidate_totals["page_fetch_on_target_region_branch"] += sum(
            item["page_fetch"] for item in lineage
        )
        candidate_totals["content_extraction_on_target_region_branch"] += sum(
            item["content_extraction"] for item in lineage
        )
        candidate_totals["page_fetch_outside_target_region_branch"] += sum(
            _is_2xx(operation)
            and not _operation_region_valid(
                operation,
                str(attempt.get("candidate_status") or ""),
                target_region,
            )
            for attempt in attempts
            for operation in attempt.get("extractions") or []
        )

    stage_rows: list[dict[str, Any]] = []
    denominator = len(rows)
    previous = len(rows)
    for stage in STAGES:
        passed = sum(row["stage_pass"][stage] for row in rows)
        if passed > previous:
            raise AssertionError(f"non-monotonic stage {stage}: {passed} > {previous}")
        stage_rows.append(
            {
                "stage": stage,
                "passed_tasks": passed,
                "entered_tasks": denominator,
                "stage_rate": passed / denominator if denominator else 0.0,
                "cumulative_denominator": len(rows),
                "cumulative_rate": passed / len(rows) if rows else 0.0,
            }
        )
        denominator = passed
        previous = passed

    return {
        "schema_version": "proofpick-v2-9g-monotonic-funnel-audit-v1",
        "source_result_run_id": result["run_id"],
        "classification": "read_only_recalculation_of_exposed_v2_9f_result",
        "definitions": {
            "task_level": (
                "A task advances only when one candidate lineage satisfies every "
                "preceding stage; target-region validation may be established by "
                "validated search metadata or the fetched official page."
            ),
            "candidate_level": (
                "All attempted candidate branches and page operations, including "
                "navigation candidates that cannot become target-region evidence."
            ),
        },
        "task_level_funnel": stage_rows,
        "first_failure_counts": {
            stage: sum(row["first_failure_stage"] == stage for row in rows)
            for stage in (*STAGES, None)
        },
        "candidate_level": candidate_totals,
        "multiple_candidate_branch_tasks": sum(
            row["has_multiple_candidate_branches"] for row in rows
        ),
        "page_fetch_included_region_failed_tasks": [
            row["case_id"]
            for row in rows
            if row["page_fetch_only_outside_target_region_lineage"]
        ],
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = audit(
        json.loads(args.result.read_text(encoding="utf-8")),
        _load_cases(args.cases),
    )
    payload["inputs"] = {
        "result_sha256": _sha256(args.result),
        "cases_sha256": _sha256(args.cases),
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["task_level_funnel"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
