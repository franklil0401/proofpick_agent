"""Deterministic product × requested-field completion, not purchase eligibility.

Only returned, typed ``FieldAssessment`` observations can close a cell. Retrieval
hits, catalog values, successful tool statuses and missing-result metadata are
never promoted into a checked fact. Unknown/conflict are completed checks, but
not sufficient evidence for a fully answered factual question.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from smartbuy.domain.models import EvidenceReference, FieldAssessment


FACT_COMPLETION_VERSION = "proofpick-fact-completion-v1"
_TERMINAL = frozenset({"verified_value", "verified_unknown", "verified_conflict"})
_IDENTITY_FIELDS = (
    "product_id", "model_id", "domain_id", "family_id", "configuration_id",
    "region", "data_version", "index_version",
)
_REQUEST_IDENTITY_MARKERS = frozenset({
    "product_id", "model_id", "model_name", "family_id", "configuration_id",
    "part_number", "sku", "domain_id", "data_version", "index_version",
})
_EXPLICIT_SCOPE_TYPES = frozenset({"exact_configuration", "explicit_comparison", "product_family"})


def _get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _unique(values: Any) -> list[str]:
    return list(dict.fromkeys(value for value in (values or []) if isinstance(value, str) and value.strip()))


def _present(value: Any) -> bool:
    # Zero and false are real facts, never the representation for an unknown.
    return value is not None and not (
        isinstance(value, (str, list, dict, tuple)) and not (value.strip() if isinstance(value, str) else value)
    )


def _fact_value(value: Any) -> bool:
    return _present(value) and not (
        isinstance(value, str) and value.strip().casefold() in {"null", "none", "unknown", "未知"}
    )


def _source_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return parsed.scheme.casefold() in {"http", "https"} and bool(parsed.hostname) and not (
            parsed.username or parsed.password
        )
    except ValueError:
        return False


def _identity_reason(product_id: str, identity: dict[str, Any]) -> str | None:
    for field in ("product_id", "model_id"):
        if _present(identity.get(field)) and identity[field] != product_id:
            return f"identity_mismatch:{field}"
    return None


def _reference_reason(
    reference: EvidenceReference, product_id: str, field: str,
    identity: dict[str, Any], *, known_fact: bool,
) -> str | None:
    if reference.model_id != product_id or (
        reference.product_id is not None and reference.product_id != product_id
    ):
        return "evidence_product_mismatch"
    if reference.field != field:
        return "evidence_field_mismatch"
    for key in _IDENTITY_FIELDS:
        expected, actual = identity.get(key), getattr(reference, key, None)
        # V1 references predate optional version/configuration metadata. Missing
        # optional fields remain compatible; supplied contradictions never do.
        # A tool also cannot attest its own identity when the catalog/scope has
        # no expected identity to compare it with. This is distinct from a
        # legacy reference simply omitting an optional metadata field.
        if key not in {"model_id", "product_id"} and actual is not None and not _present(expected):
            return f"evidence_identity_unbound:{key}"
        if _present(expected) and actual is not None and actual != expected:
            return f"evidence_identity_mismatch:{key}"
    if known_fact and not (
        _present(reference.evidence_id) and _present(reference.source_id)
        and _present(reference.region) and _source_url(reference.source_url) and _fact_value(reference.value)
    ):
        return "incomplete_fact_reference"
    return None


def _assessment_cell(
    assessment: FieldAssessment, product_id: str, field: str, identity: dict[str, Any],
) -> dict[str, Any]:
    cell = {
        "product_id": product_id, "field": field, "status": "not_checked",
        "actual_value": assessment.actual_value, "evidence_ids": [],
        "reason": assessment.reason, "identity": identity,
        "evidence": [reference.model_dump(mode="json") for reference in assessment.evidence],
    }
    reason = _identity_reason(product_id, identity)
    known_fact = assessment.status in {"matched", "not_matched"}
    if reason is None:
        for reference in assessment.evidence:
            reason = _reference_reason(reference, product_id, field, identity, known_fact=known_fact)
            if reason:
                break
    if reason is not None:
        cell["reason"] = reason
        return cell
    if known_fact and not _fact_value(assessment.actual_value):
        cell["reason"] = "missing_actual_value"
        return cell
    if known_fact and not assessment.evidence:
        cell["reason"] = "missing_fact_reference"
        return cell
    cell["evidence_ids"] = _unique(reference.evidence_id for reference in assessment.evidence)
    cell["status"] = {
        "matched": "verified_value", "not_matched": "verified_value",
        "unknown": "verified_unknown", "conflict": "verified_conflict",
    }.get(assessment.status, "not_checked")
    return cell


def _combine_cells(cells: list[dict[str, Any]]) -> dict[str, Any]:
    # Do not allow duplicate tool output to turn an unknown/conflict or identity
    # failure into success by whichever row happens to appear last.
    priority = {"verified_value": 0, "verified_unknown": 1, "verified_conflict": 2, "not_checked": 3}
    result = dict(max(cells, key=lambda cell: priority[cell["status"]]))
    result["evidence_ids"] = _unique(value for cell in cells for value in cell["evidence_ids"])
    result["evidence"] = []
    for cell in cells:
        for evidence in cell["evidence"]:
            if evidence not in result["evidence"]:
                result["evidence"].append(evidence)
    if len(cells) > 1:
        # Retain each observed value and reason instead of hiding disagreement.
        result["observations"] = [
            {key: cell[key] for key in ("status", "actual_value", "reason", "evidence_ids")}
            for cell in cells
        ]
        if result["status"] == "verified_value" and any(
            cell["actual_value"] != result["actual_value"] for cell in cells
        ):
            result["status"] = "verified_conflict"
            result["actual_value"] = [cell["actual_value"] for cell in cells]
            result["reason"] = "conflicting_returned_assessments"
    return result


def build_fact_completion(
    product_ids: list[str], requested_fields: list[str],
    assessments: dict[str, list[FieldAssessment]],
    identities: dict[str, dict] | None = None,
    attempts: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Return a scope-bounded, JSON-compatible matrix without calling any tool.

    ``complete`` means all required cells were actually checked. It does not
    mean every fact is known: use ``answer_sufficient`` for that stronger claim.
    Attempt statuses can explain an absent assessment, never fabricate one.
    """
    matrix: list[dict[str, Any]] = []
    for product_id in _unique(product_ids):
        identity = {
            key: value for key, value in (identities or {}).get(product_id, {}).items()
            if key in _IDENTITY_FIELDS and _present(value)
        }
        identity.setdefault("product_id", product_id)
        returned = assessments.get(product_id, [])
        for field in _unique(requested_fields):
            matches = [
                item for item in returned if isinstance(item, FieldAssessment) and item.field == field
            ]
            if matches:
                matrix.append(_combine_cells([
                    _assessment_cell(item, product_id, field, identity) for item in matches
                ]))
                continue
            attempt = (attempts or {}).get(product_id, {}).get(field)
            status = attempt if attempt in {"tool_failed", "budget_exhausted"} else "not_checked"
            matrix.append({
                "product_id": product_id, "field": field, "status": status,
                "actual_value": None, "evidence_ids": [], "reason": (
                    status if status != "not_checked" else "no_returned_field_assessment"
                ), "identity": identity, "evidence": [],
            })
    checked = sum(cell["status"] in _TERMINAL for cell in matrix)
    required = len(matrix)
    return {
        "version": FACT_COMPLETION_VERSION,
        "completion_status": (
            "complete" if required and checked == required else "partial" if checked else "incomplete"
        ),
        "checked_count": checked, "required_count": required,
        "answer_sufficient": bool(matrix) and all(cell["status"] == "verified_value" for cell in matrix),
        "matrix": matrix,
    }


def _state_identities(
    state: Any, scope: Any, product_ids: list[str], rows: dict[str, dict],
) -> dict[str, dict[str, Any]]:
    identities: dict[str, dict[str, Any]] = {}
    authoritative = _get(state, "fact_identities", None)
    for product_id in product_ids:
        # A present map is authoritative even when empty after a catalog read
        # failure. Tools must never fill its gaps and attest their own identity.
        # None only supports standalone legacy report fixtures; production
        # fact/comparison entry initializes an explicit map before any tool.
        identity = dict(
            authoritative.get(product_id, {}) if authoritative is not None
            else rows.get(product_id, {})
        )
        if authoritative is None:
            # Historical pure build_report callers supply trusted, typed
            # observations but no catalog map or rows. Preserve that contract
            # only for a unique consistent identity. Runtime callers initialize
            # {} before tools, so a runtime tool cannot enter this compatibility
            # path even when the catalog is unavailable.
            refs = [
                ref for item in (_get(state, "assessments", {}) or {}).get(product_id, [])
                if isinstance(item, FieldAssessment)
                for ref in item.evidence
                if ref.model_id == product_id and ref.product_id in {None, product_id}
                and ref.field == item.field
            ]
            for key in _IDENTITY_FIELDS:
                if _present(identity.get(key)):
                    continue
                values = {
                    getattr(ref, key, None) for ref in refs if _present(getattr(ref, key, None))
                }
                if len(values) == 1:
                    identity[key] = values.pop()
        if scope is not None:
            for key in ("data_version", "index_version", "domain_id"):
                if _present(_get(scope, key)):
                    identity[key] = _get(scope, key)
            regions = _get(scope, "regions", [])
            if len(regions) == 1:
                identity["region"] = regions[0]
            configs = _get(scope, "configuration_ids", [])
            if len(product_ids) == 1 and len(configs) == 1:
                identity["configuration_id"] = configs[0]
            for reference in _get(scope, "references", []):
                if product_id in _get(reference, "matched_product_ids", []):
                    for key in ("family_id", "configuration_id", "region"):
                        if _present(_get(reference, key)):
                            identity[key] = _get(reference, key)
        identities[product_id] = identity
    return identities


def from_agent_state(state: Any) -> dict[str, Any]:
    """Derive obligations from trusted scope and observations, never KB hit count."""
    scope = _get(state, "product_scope")
    requirements = _get(state, "requirements")
    scope_fields = _get(scope, "requested_fields", [])
    fields = [field for field in _unique(
        scope_fields or _get(requirements, "required_fields", [])
    ) if field not in _REQUEST_IDENTITY_MARKERS]
    pool = _get(state, "candidate_pool_rows", {}) or {}
    rows = dict(pool)
    candidate_ids: list[str] = []
    for row in _get(state, "candidate_rows", []) or []:
        product_id = row.get("product_id") or row.get("model_id")
        if isinstance(product_id, str) and product_id:
            candidate_ids.append(product_id)
            rows[product_id] = {**rows.get(product_id, {}), **row}
    assessments = _get(state, "assessments", {}) or {}
    observed = _unique([*pool, *candidate_ids, *assessments])
    explicit = scope is not None and (
        _get(scope, "scope_type") in _EXPLICIT_SCOPE_TYPES
        or _get(scope, "explicit_comparison", False)
        or any(_get(scope, key, []) for key in (
            "mentions", "mentioned_quotes", "include_product_ids", "include_family_ids", "include_configuration_ids",
        ))
    )
    product_ids = _unique(_get(scope, "product_ids", [])) if explicit else observed
    if scope is not None:
        allowed = set(_get(scope, "product_ids", []))
        product_ids = [product_id for product_id in product_ids if product_id in allowed]
    excluded = set(_get(requirements, "excluded_model_ids", [])) | set(_get(scope, "exclude_product_ids", []))
    product_ids = [product_id for product_id in product_ids if product_id not in excluded]
    return build_fact_completion(
        product_ids, fields, assessments,
        identities=_state_identities(state, scope, product_ids, rows),
        attempts=_get(state, "fact_check_attempts", None),
    )


def missing_fact_fields(completion: dict[str, Any]) -> dict[str, list[str]]:
    """Group nonterminal obligations; checked unknown/conflict are not retried."""
    pending: dict[str, list[str]] = {}
    for cell in completion.get("matrix", []):
        if cell.get("status") in _TERMINAL:
            continue
        product_id, field = cell.get("product_id"), cell.get("field")
        if not isinstance(product_id, str) or not isinstance(field, str):
            continue
        fields = pending.setdefault(product_id, [])
        if field not in fields:
            fields.append(field)
    return pending
