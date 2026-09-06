"""Pack-driven Agent workflow shared by every installed V2 product category."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from typing import Any

from smartbuy.constraint_proposals import ClarificationState, ConstraintResolution, ProposalStatus
from smartbuy.constraint_proposals.models import ProposalSource
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.constraints import (
    CandidateVerification,
    ConstraintResult,
    ConstraintSet,
    ConstraintOperator,
    VerificationBatch,
    VerificationStatus,
)
from smartbuy.domain import ResearchMode
from smartbuy.domain.models import (
    CandidateDecision,
    ConstraintStatus,
    DecisionReport,
    EvidenceReference,
    FieldAssessment,
    ToolTrace,
    UnresolvedFact,
)
from smartbuy.domain_packs import LoadedDomainPack
from smartbuy.identity import (
    ProductIdentityResolver,
    ProductScopeResolutionStatus,
    ProductScopeType,
    ResolvedProductScope,
    QueryIntent,
    ReferencePolarity,
    evidence_identity_status,
    product_identity,
    require_product_in_scope,
)
from smartbuy.decision_core.delta import ConstraintDeltaResolver
from smartbuy.decision_core.canonical import CanonicalValueError, CanonicalValueNormalizer
from smartbuy.decision_core.intent import QueryUnderstandingEngine
from smartbuy.decision_core.scope import CandidateScopeReducer
from smartbuy.decision_core.result import ResultClassificationInput, classify_result
from smartbuy.decision_core.safety import CandidateChainViolation, assert_candidate_chain
from smartbuy.decision_core.requirements import audit_requirement_coverage
from smartbuy.agent.fact_completion import build_fact_completion
from smartbuy.memory import DomainPreferenceMemoryStore
from smartbuy.orchestration.contracts import EventCallback, emit_event
from smartbuy.ranking import (
    DeterministicDecisionRanker,
    RankingCandidateInput,
    RankingEvidence,
    RankingExplanation,
    RankingProfileError,
    RankingProfileLoader,
    RankingRequest,
    stable_fallback,
)
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainKBSearchTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)
from smartbuy.tools import ToolResult


_FACT_MARKERS = ("多少", "是什么", "哪个", "属于", "核验", "是否", "能否", "比较", "区分")
_COMPARE_MARKERS = ("比较", "对比", "区分", "是否等同", "不要把", "不能混")
_IDENTITY_FIELDS = {"product_id", "family_id", "model_name", "region", "configuration_id", "part_number"}


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", value.casefold())


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _verification_status(value: str) -> VerificationStatus:
    return {
        "matched": VerificationStatus.PASSED,
        "not_matched": VerificationStatus.FAILED,
        "unknown": VerificationStatus.UNKNOWN,
        "conflict": VerificationStatus.CONFLICT,
    }[value]


class DomainDecisionAgent:
    """Bounded workflow whose business vocabulary comes only from loaded packs."""

    supports_v2_ranking = True

    def __init__(
        self,
        pack: LoadedDomainPack,
        repository: DomainReadonlyRepository,
        product_query: DomainProductQueryTool,
        evidence_check: DomainEvidenceCheckTool,
        checker: DomainConstraintCheckerTool,
        constraint_engine: NaturalConstraintEngine,
        preference_memory: DomainPreferenceMemoryStore,
        *,
        kb_search: DomainKBSearchTool | None = None,
        max_steps: int = 8,
        max_tool_calls: int = 12,
    ) -> None:
        if not 1 <= max_steps <= 8 or not 1 <= max_tool_calls <= 12:
            raise ValueError("domain Agent bounds exceed the public contract")
        self.pack = pack
        self.repository = repository
        self.product_query = product_query
        self.kb_search = kb_search
        self.evidence_check = evidence_check
        self.checker = checker
        self.constraint_engine = constraint_engine
        self.preference_memory = preference_memory
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls
        self._session_constraints: dict[str, ConstraintSet] = {}
        self._ranking_profile_error: str | None = None
        try:
            loaded_profile = RankingProfileLoader.load(pack)
            self.ranker: DeterministicDecisionRanker | None = DeterministicDecisionRanker(
                loaded_profile
            )
            self.ranking_profile_version = loaded_profile.profile.profile_version
        except RankingProfileError as exc:
            self.ranker = None
            self.ranking_profile_version = "unavailable"
            self._ranking_profile_error = type(exc).__name__

    def _session_key(self, session_id: str | None, user_id: str | None) -> str | None:
        if not session_id:
            return None
        identity = user_id or "ephemeral"
        return hashlib.sha256(
            f"{self.pack.domain_id}\x1f{identity}\x1f{session_id}".encode("utf-8")
        ).hexdigest()

    def _intent(self, query: str) -> str:
        folded = query.casefold()
        if any(marker in folded for marker in _COMPARE_MARKERS):
            return "comparison"
        if any(marker in folded for marker in _FACT_MARKERS):
            return "fact"
        return "filter"

    def _field_mentions(self, query: str) -> list[str]:
        folded = query.casefold()
        output = []
        for field_id, definition in self.pack.fields.items():
            terms = [
                field_id,
                definition.label,
                *definition.aliases,
                *definition.enum_values,
                *definition.value_aliases,
            ]
            if any(
                term
                and re.search(
                    rf"(?<![a-z0-9]){re.escape(term.casefold())}(?![a-z0-9])",
                    folded,
                )
                for term in terms
            ):
                output.append(field_id)
        return list(dict.fromkeys(output))

    def _repair_pack_proposals(
        self,
        query: str,
        resolution: ConstraintResolution,
        products: dict[str, dict[str, Any]],
    ) -> ConstraintResolution:
        repaired = []
        superseded_ids: set[str] = set()
        for proposal in resolution.proposals:
            if proposal.source_span is None:
                continue
            definition = self.pack.fields.get(proposal.field)
            if proposal.status.value == "invalid" and definition is not None and definition.data_type.value == "string_list":
                vocabulary = sorted({
                    str(value)
                    for product in products.values()
                    for value in (product["attributes"].get(proposal.field) or [])
                    if isinstance(value, str)
                })
                chosen = []
                for value in vocabulary:
                    related = [
                        field
                        for field in self.pack.fields.values()
                        if field.field_id == value or field.field_id.startswith(value + "_")
                    ]
                    terms = [value, *(term for field in related for term in (field.label, *field.aliases))]
                    if any(term and term.casefold() in proposal.source_span.text.casefold() for term in terms):
                        chosen.append(value)
                if chosen:
                    repaired.append(self.constraint_engine.validator.validate(
                        query,
                        {
                            "field": proposal.field, "operator": "contains_all", "value": chosen,
                            "unit": None, "strength": proposal.strength.value, "status": "supported",
                            "action": proposal.action.value, "span_start": proposal.source_span.start,
                            "span_end": proposal.source_span.end, "span_text": proposal.source_span.text,
                            "confidence": 1.0, "reason": "pack_vocabulary_rule",
                        },
                        source=ProposalSource.RULE,
                        source_turn=proposal.source_turn,
                    ))
                continue
            if proposal.status.value != "unsupported":
                continue
            literal = proposal.source_span.text.casefold()
            for target in self.pack.fields.values():
                value_map = {key.casefold(): value for key, value in target.value_aliases.items()}
                value_map.update({value.casefold(): value for value in target.enum_values})
                if literal not in value_map or "eq" not in {item.value for item in target.allowed_operators}:
                    continue
                repaired.append(self.constraint_engine.validator.validate(
                    query,
                    {
                        "field": target.field_id,
                        "operator": "eq",
                        "value": value_map[literal],
                        "unit": target.unit,
                        "strength": proposal.strength.value,
                        "status": "supported",
                        "action": proposal.action.value,
                        "span_start": proposal.source_span.start,
                        "span_end": proposal.source_span.end,
                        "span_text": proposal.source_span.text,
                        "confidence": 1.0,
                        "reason": "pack_literal_rule",
                    },
                    source=ProposalSource.RULE,
                    source_turn=proposal.source_turn,
                ))
                superseded_ids.add(proposal.proposal_id)
                break
        if not repaired:
            return resolution
        constraint_set, activated, diffs = self.constraint_engine._apply(
            resolution.constraint_set, repaired
        )
        proposals = [
            item.model_copy(
                update={
                    "status": ProposalStatus.INVALID,
                    "active": False,
                    "reason": "superseded_by_pack_literal",
                }
            )
            if item.proposal_id in superseded_ids else item
            for item in resolution.proposals
        ]
        return resolution.model_copy(update={
            "proposals": [*proposals, *activated],
            "constraint_set": constraint_set,
            "diff": [*resolution.diff, *diffs],
        })

    @staticmethod
    def _literal_match(query: str, value: str) -> re.Match[str] | None:
        escaped = re.escape(value).replace(r"\ ", r"\s+")
        return re.search(
            rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])",
            query,
            flags=re.I,
        )

    def _add_catalog_value_proposals(
        self,
        query: str,
        resolution: ConstraintResolution,
        products: dict[str, dict[str, Any]],
        intent: QueryIntent,
        scope: ResolvedProductScope,
    ) -> ConstraintResolution:
        """Bind free string/list values using only Pack fields and catalog values."""
        if intent not in {
            QueryIntent.RECOMMENDATION_FILTER,
            QueryIntent.CLARIFICATION_REQUIRED,
        }:
            return resolution
        existing = {
            item.field for item in resolution.proposals
            if item.status != ProposalStatus.INVALID
        }
        additions = []
        interpretation = self.pack.pack.policies.get("understanding", {})
        list_triggers = interpretation.get("string_list_triggers", {})
        scoped_products = [products[item] for item in scope.product_ids]
        numeric_selector_fields = set(interpretation.get("numeric_selector_fields", []))
        for field_id, definition in self.pack.fields.items():
            if not definition.constraint_enabled or field_id in existing or field_id in _IDENTITY_FIELDS:
                continue
            values = [product["attributes"].get(field_id) for product in products.values()]
            if definition.data_type.value == "string":
                vocabulary = sorted(
                    {str(item) for item in values if isinstance(item, str)},
                    key=len,
                    reverse=True,
                )
                aliases: dict[str, set[str]] = {}
                for value in vocabulary:
                    aliases.setdefault(value, set()).add(value)
                    tokens = value.split()
                    for position in range(max(0, len(tokens) - 5), len(tokens) - 1):
                        suffix = " ".join(tokens[position:])
                        if len(suffix) >= 6 and re.search(r"\d", suffix):
                            aliases.setdefault(suffix, set()).add(value)
                for alias in sorted(aliases, key=len, reverse=True):
                    canonical_values = aliases[alias]
                    if len(canonical_values) != 1:
                        continue
                    match = self._literal_match(query, alias)
                    if match is None:
                        continue
                    value = next(iter(canonical_values))
                    additions.append(self.constraint_engine.validator.validate(
                        query,
                        {
                            "field": field_id,
                            "operator": "eq",
                            "value": value,
                            "unit": definition.unit,
                            "strength": "hard",
                            "status": "supported",
                            "action": "add",
                            "span_start": match.start(),
                            "span_end": match.end(),
                            "span_text": match.group(0),
                            "confidence": 1.0,
                            "reason": "exact_catalog_literal",
                        },
                        source=ProposalSource.RULE,
                        source_turn=resolution.source_turn,
                    ))
                    break
            elif definition.data_type.value == "string_list":
                triggers = list_triggers.get(field_id, [])
                trigger_match = next(
                    (self._literal_match(query, str(item)) for item in triggers
                     if self._literal_match(query, str(item)) is not None),
                    None,
                )
                if trigger_match is None:
                    continue
                vocabulary = sorted({
                    str(item)
                    for value in values if isinstance(value, list)
                    for item in value if isinstance(item, str)
                })
                chosen = []
                starts = [trigger_match.start()]
                ends = [trigger_match.end()]
                for value in vocabulary:
                    related = [
                        candidate for candidate in self.pack.fields.values()
                        if candidate.field_id == value or candidate.field_id.startswith(value + "_")
                    ]
                    terms = [value, *(term for candidate in related for term in (candidate.label, *candidate.aliases))]
                    found = next(
                        (self._literal_match(query, term) for term in terms
                         if self._literal_match(query, term) is not None),
                        None,
                    )
                    if found is not None:
                        chosen.append(value)
                        starts.append(found.start())
                        ends.append(found.end())
                if chosen:
                    additions.append(self.constraint_engine.validator.validate(
                        query,
                        {
                            "field": field_id,
                            "operator": "contains_all",
                            "value": chosen,
                            "unit": None,
                            "strength": "hard",
                            "status": "supported",
                            "action": "add",
                            "span_start": min(starts),
                            "span_end": max(ends),
                            "span_text": query[min(starts):max(ends)],
                            "confidence": 1.0,
                            "reason": "exact_catalog_list_literal",
                        },
                        source=ProposalSource.RULE,
                        source_turn=resolution.source_turn,
                    ))
        # A bare capacity followed by "version/configuration" is an identity
        # selector only when one Pack field can explain it within the already
        # resolved family scope.  Ambiguous units never gain authority.
        if scope.scope_type in {
            ProductScopeType.PRODUCT_FAMILY,
            ProductScopeType.AMBIGUOUS_PRODUCT_SCOPE,
        } and re.search(r"(?:版本|配置)", query):
            for number in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)\s*([A-Za-z]+)(?![A-Za-z])", query):
                matches: list[tuple[str, Any]] = []
                for field_id, definition in self.pack.fields.items():
                    if (
                        field_id in existing
                        or not definition.constraint_enabled
                        or definition.data_type.value not in {"number", "integer"}
                        or (numeric_selector_fields and field_id not in numeric_selector_fields)
                    ):
                        continue
                    try:
                        canonical = CanonicalValueNormalizer.normalize(
                            definition, float(number.group(1)), unit=number.group(2)
                        ).to_native()
                    except CanonicalValueError:
                        continue
                    selected = [
                        item for item in scoped_products
                        if item["attributes"].get(field_id) is not None
                        and CanonicalValueNormalizer.equivalent(
                            definition, item["attributes"][field_id], canonical
                        )
                    ]
                    if selected and len(selected) < len(scoped_products):
                        matches.append((field_id, canonical))
                if len(matches) != 1:
                    continue
                field_id, canonical = matches[0]
                definition = self.pack.fields[field_id]
                additions.append(self.constraint_engine.validator.validate(
                    query,
                    {
                        "field": field_id,
                        "operator": "eq",
                        "value": canonical,
                        "unit": definition.unit,
                        "strength": "hard",
                        "status": "supported",
                        "action": "add",
                        "span_start": number.start(),
                        "span_end": number.end(),
                        "span_text": number.group(0),
                        "confidence": 1.0,
                        "reason": "unique_pack_numeric_selector",
                    },
                    source=ProposalSource.RULE,
                    source_turn=resolution.source_turn,
                ))
        if not additions:
            return resolution
        # The primary parser may emit one whole-query unsupported fallback
        # before Pack/catalog literals are bound.  Once deterministic Pack
        # proposals explain the request, that broad fallback loses authority;
        # narrow unsupported spans remain intact.
        effective_existing = []
        for proposal in resolution.proposals:
            source = proposal.source_span
            broad_fallback = bool(
                proposal.field == "unsupported"
                and proposal.reason == "field_not_declared_by_domain_pack"
                and source is not None
                and not query[:source.start].strip()
                and not query[source.end:].strip()
            )
            effective_existing.append(
                proposal.model_copy(
                    update={
                        "status": ProposalStatus.INVALID,
                        "active": False,
                        "reason": "superseded_by_pack_supported_proposals",
                    }
                )
                if broad_fallback else proposal
            )
        proposals = self.constraint_engine.parser._deduplicate_and_mark_conflicts(
            [*effective_existing, *additions]
        )
        base = ConstraintSet(
            constraints=[item for item in resolution.constraint_set.constraints if not item.active],
            cancelled_fields=list(resolution.constraint_set.cancelled_fields),
            rejected_model_constraints=list(resolution.constraint_set.rejected_model_constraints),
        )
        constraint_set, activated, diffs = self.constraint_engine._apply(base, proposals)
        pending = [
            item.proposal_id for item in activated
            if item.status in {ProposalStatus.AMBIGUOUS, ProposalStatus.NEEDS_CONFIRMATION}
        ]
        return resolution.model_copy(update={
            "proposals": activated,
            "constraint_set": constraint_set,
            "diff": diffs,
            "pending_proposal_ids": pending,
            "clarification_state": ClarificationState.PENDING if pending else ClarificationState.NOT_REQUIRED,
            "clarification_question": self.constraint_engine._question(activated) if pending else None,
        })

    def _add_region_proposals(
        self,
        query: str,
        resolution: ConstraintResolution,
        scope: ResolvedProductScope,
        intent: QueryIntent,
    ) -> ConstraintResolution:
        if intent == QueryIntent.CLARIFICATION_REQUIRED or "region" not in self.pack.fields:
            return resolution
        additions = []
        positive = [
            item for item in scope.references
            if item.identity_kind == "region"
            and item.polarity == ReferencePolarity.INCLUDE
            and item.region in scope.allowed_regions
        ]
        negative = [
            item for item in scope.references
            if item.identity_kind == "region"
            and item.polarity == ReferencePolarity.EXCLUDE
            and item.region in scope.excluded_regions
        ]
        for item in positive:
            additions.append(self.constraint_engine.validator.validate(
                query,
                {
                    "field": "region", "operator": "eq", "value": item.region,
                    "unit": None, "strength": "hard", "status": "supported",
                    "action": "add", "span_start": item.span_start,
                    "span_end": item.span_end, "span_text": item.quote,
                    "confidence": 1.0, "reason": "registry_region_include",
                },
                source=ProposalSource.RULE,
                source_turn=resolution.source_turn,
            ))
        for item in negative:
            additions.append(self.constraint_engine.validator.validate(
                query,
                {
                    "field": "region", "operator": "not_in", "value": [item.region],
                    "unit": None, "strength": "hard", "status": "supported",
                    "action": "add", "span_start": item.span_start,
                    "span_end": item.span_end, "span_text": item.quote,
                    "confidence": 1.0, "reason": "registry_region_exclude",
                },
                source=ProposalSource.RULE,
                source_turn=resolution.source_turn,
            ))
        if not additions:
            return resolution
        proposals = [
            item for item in resolution.proposals
            if item.field != "region" or item.status == ProposalStatus.INVALID
        ] + additions
        base = ConstraintSet(
            constraints=[item for item in resolution.constraint_set.constraints if not item.active],
            cancelled_fields=list(resolution.constraint_set.cancelled_fields),
            rejected_model_constraints=list(resolution.constraint_set.rejected_model_constraints),
        )
        constraint_set, activated, diffs = self.constraint_engine._apply(base, proposals)
        return resolution.model_copy(update={
            "proposals": activated,
            "constraint_set": constraint_set,
            "diff": diffs,
        })

    @staticmethod
    def _separate_requested_fields(
        resolution: ConstraintResolution,
        intent: QueryIntent,
    ) -> ConstraintResolution:
        if intent in {
            QueryIntent.RECOMMENDATION_FILTER,
        }:
            allowed = None
        elif intent == QueryIntent.CLARIFICATION_REQUIRED:
            allowed = set()
            disallowed = _IDENTITY_FIELDS
        else:
            allowed = set()
        if intent == QueryIntent.CLARIFICATION_REQUIRED:
            pass
        elif allowed is None:
            disallowed = _IDENTITY_FIELDS - {"region"}
        else:
            disallowed = {item.field for item in resolution.proposals if item.field not in allowed}
        proposals = [
            item.model_copy(update={
                "status": ProposalStatus.INVALID,
                "active": False,
                "reason": "requested_fact_or_identity_not_purchase_constraint",
            })
            if item.field in disallowed and item.status != ProposalStatus.INVALID else item
            for item in resolution.proposals
        ]
        constraints = [
            item.model_copy(update={
                "active": False,
                "note": "requested_fact_or_identity_not_purchase_constraint",
            }) if item.field in disallowed and item.active else item
            for item in resolution.constraint_set.constraints
        ]
        pending = [
            item.proposal_id for item in proposals
            if item.status in {ProposalStatus.AMBIGUOUS, ProposalStatus.NEEDS_CONFIRMATION}
        ]
        return resolution.model_copy(update={
            "proposals": proposals,
            "constraint_set": resolution.constraint_set.model_copy(update={"constraints": constraints}),
            "pending_proposal_ids": pending,
            "clarification_state": ClarificationState.PENDING if pending else ClarificationState.NOT_REQUIRED,
            "clarification_question": resolution.clarification_question if pending else None,
        })

    def _canonicalize_resolution(
        self,
        query: str,
        resolution: ConstraintResolution,
        products: dict[str, dict[str, Any]],
        mentioned: list[str],
        intent: QueryIntent,
    ) -> ConstraintResolution:
        updated = []
        for constraint in resolution.constraint_set.constraints:
            value = constraint.normalized_value
            if constraint.active and constraint.operator == ConstraintOperator.EQ and isinstance(value, str):
                known = {
                    product["attributes"].get(constraint.field)
                    for product in products.values()
                    if isinstance(product["attributes"].get(constraint.field), str)
                }
                candidates = [item for item in known if _compact(value) in _compact(item)]
                if value not in known and len(candidates) == 1:
                    constraint = constraint.model_copy(
                        update={"normalized_value": candidates[0], "note": "canonicalized_from_product_pack"}
                    )
            updated.append(constraint)
        return resolution.model_copy(
            update={"constraint_set": resolution.constraint_set.model_copy(update={"constraints": updated})}
        )

    @staticmethod
    def _scope_identity_values(
        field: str,
        scope: ResolvedProductScope,
        products: dict[str, dict[str, Any]],
    ) -> set[str]:
        values = set()
        for product_id in scope.product_ids:
            product = products[product_id]
            value = product.get(field, product["attributes"].get(field))
            if value is not None:
                values.add(str(value).casefold())
        return values

    def _reconcile_identity_resolution(
        self,
        resolution: ConstraintResolution,
        scope: ResolvedProductScope,
        products: dict[str, dict[str, Any]],
    ) -> ConstraintResolution:
        """Keep identity history, but let only registry-resolved identity control scope."""
        if scope.resolution_status != ProductScopeResolutionStatus.RESOLVED:
            return resolution
        invalidated_proposal_ids: set[str] = set()
        constraints = []
        for item in resolution.constraint_set.constraints:
            if item.field not in _IDENTITY_FIELDS:
                constraints.append(item)
                continue
            allowed = self._scope_identity_values(item.field, scope, products)
            values = item.normalized_value if isinstance(item.normalized_value, list) else [item.normalized_value]
            normalized = {str(value).casefold() for value in values if value is not None}
            compatible = (
                bool(allowed & normalized)
                if item.operator in {ConstraintOperator.EQ, ConstraintOperator.IN}
                else not bool(allowed & normalized)
                if item.operator == ConstraintOperator.NOT_IN
                else False
            )
            if item.active and not compatible:
                item = item.model_copy(
                    update={
                        "active": False,
                        "note": "superseded_by_deterministic_product_identity",
                    }
                )
            constraints.append(item)
        proposals = []
        for proposal in resolution.proposals:
            if proposal.field not in _IDENTITY_FIELDS:
                proposals.append(proposal)
                continue
            allowed = self._scope_identity_values(proposal.field, scope, products)
            raw_values = (
                proposal.normalized_value
                if isinstance(proposal.normalized_value, list)
                else [proposal.normalized_value]
            )
            normalized = {str(value).casefold() for value in raw_values if value is not None}
            compatible = (
                bool(allowed & normalized)
                if proposal.operator in {ConstraintOperator.EQ, ConstraintOperator.IN}
                else not bool(allowed & normalized)
                if proposal.operator == ConstraintOperator.NOT_IN
                else False
            )
            if proposal.status in {
                ProposalStatus.AMBIGUOUS,
                ProposalStatus.NEEDS_CONFIRMATION,
            } or not compatible:
                invalidated_proposal_ids.add(proposal.proposal_id)
                proposal = proposal.model_copy(
                    update={
                        "status": ProposalStatus.INVALID,
                        "active": False,
                        "reason": "superseded_by_deterministic_product_identity",
                    }
                )
            proposals.append(proposal)
        pending_ids = [
            proposal_id
            for proposal_id in resolution.pending_proposal_ids
            if proposal_id not in invalidated_proposal_ids
        ]
        return resolution.model_copy(
            update={
                "proposals": proposals,
                "constraint_set": resolution.constraint_set.model_copy(
                    update={"constraints": constraints}
                ),
                "clarification_state": (
                    ClarificationState.PENDING
                    if pending_ids else ClarificationState.NOT_REQUIRED
                ),
                "clarification_question": (
                    resolution.clarification_question if pending_ids else None
                ),
                "pending_proposal_ids": pending_ids,
            }
        )

    async def _trace(
        self,
        callback: EventCallback | None,
        trace: list[ToolTrace],
        tool: str,
        status: str,
        summary: str,
        *,
        arguments: dict[str, Any] | None = None,
        duration_ms: float = 0.0,
        parent_step: int | None = None,
    ) -> None:
        if len(trace) >= self.max_tool_calls:
            raise RuntimeError("tool_call_budget_exhausted")
        item = ToolTrace(
            step=len(trace) + 1,
            parent_step=parent_step,
            task_summary=f"{self.pack.domain_id} domain task",
            tool=tool,
            arguments_summary=arguments or {},
            status=status,
            result_summary=summary,
            next_action="continue" if tool != "domain_constraint_checker" else "render_report",
            duration_ms=duration_ms,
        )
        trace.append(item)
        await emit_event(
            callback,
            {
                "type": "domain_tool_completed",
                "domain_id": self.pack.domain_id,
                "tool": tool,
                "status": status,
                "step": item.step,
                "summary": summary,
            },
        )

    @staticmethod
    def _tool_constraints(resolution: ConstraintResolution) -> list[dict[str, Any]]:
        return [
            {
                "field": item.field,
                "operator": item.operator.value,
                "value": item.normalized_value,
                "unit": item.unit,
            }
            for item in resolution.constraint_set.active(hard_only=True, supported_only=True)
        ]

    def _references(
        self,
        product: dict[str, Any],
        fields: set[str],
        scope: ResolvedProductScope,
        *,
        index_version: str | None = None,
    ) -> list[EvidenceReference]:
        try:
            require_product_in_scope(
                product,
                scope,
                data_version=self.repository.snapshot.data_version,
                index_version=index_version,
            )
        except ValueError:
            return []
        output = []
        for row in product["evidence"]:
            if row["field_id"] not in fields:
                continue
            valid, _ = evidence_identity_status(product, row, field=row["field_id"])
            if not valid:
                continue
            output.append(
                EvidenceReference(
                    evidence_id=row["evidence_id"], source_id=row["source_id"],
                    source_url=row["source_url"], source_type=row["source_type"],
                    model_id=product["product_id"], product_id=product["product_id"],
                    domain_id=product["domain_id"],
                    family_id=product["attributes"].get("family_id"),
                    configuration_id=product["attributes"].get("configuration_id"),
                    region=row["region"],
                    data_version=self.repository.snapshot.data_version,
                    index_version=index_version,
                    field=row["field_id"], value=row["normalized_value"],
                    location="governed field evidence", effective_time=row["observed_at"],
                )
            )
        return output

    def _fact_requests(self, product: dict[str, Any], fields: set[str]) -> list[dict[str, Any]]:
        """Request governed checks without inventing purchase constraints.

        Some Pack fields permit only ordering operators. A reflexive value
        check still delegates type, unit and Evidence four-state semantics to
        the existing Evidence tool; it does not enter the user's ConstraintSet.
        """
        output = []
        for field in sorted(fields):
            definition = self.pack.fields[field]
            allowed = {item.value for item in definition.allowed_operators}
            operator = next((item for item in ("eq", "lte", "gte", "range", "in", "contains_all") if item in allowed), "eq")
            actual = product["attributes"].get(field)
            expected = (
                [actual, actual] if operator == "range"
                else [actual] if operator == "in" else actual
            )
            output.append({"field": field, "operator": operator, "value": expected, "unit": definition.unit})
        return output

    def _checked_fact_fields(
        self,
        product: dict[str, Any],
        fields: set[str],
        result: ToolResult,
        scope: ResolvedProductScope,
        *,
        index_version: str | None,
    ) -> tuple[list[FieldAssessment], dict[str, str]]:
        """Consume executed Evidence results, never synthesize completion from rows."""
        attempts = dict.fromkeys(fields, "not_checked")
        identity = product_identity(product, data_version=self.repository.snapshot.data_version)
        if result.status != "success" or any(result.data.get(key) != value for key, value in identity.items()):
            return [], dict.fromkeys(fields, "tool_failed")
        rows = result.data.get("field_results")
        if not isinstance(rows, list):
            return [], dict.fromkeys(fields, "tool_failed")
        references = self._references(product, fields, scope, index_version=index_version)
        assessments = []
        for field in sorted(fields):
            matching = [row for row in rows if isinstance(row, dict) and row.get("field_id") == field]
            if not matching:
                continue
            if len(matching) != 1:
                attempts[field] = "tool_failed"
                continue
            row = matching[0]
            try:
                status = ConstraintStatus(row["state"])
                evidence_ids = set(row["evidence_ids"])
                source_ids = set(row["source_ids"])
            except (KeyError, TypeError, ValueError):
                attempts[field] = "tool_failed"
                continue
            refs = [ref for ref in references if ref.field == field and ref.evidence_id in evidence_ids and ref.source_id in source_ids]
            if status in {ConstraintStatus.MATCHED, ConstraintStatus.NOT_MATCHED, ConstraintStatus.CONFLICT} and not refs:
                attempts[field] = "tool_failed"
                continue
            actual = row.get("actual_value")
            if status in {ConstraintStatus.MATCHED, ConstraintStatus.NOT_MATCHED} and actual is None:
                attempts[field] = "tool_failed"
                continue
            if status == ConstraintStatus.CONFLICT:
                values = {json.dumps(ref.value, ensure_ascii=False, sort_keys=True) for ref in refs}
                if len(values) < 2:
                    attempts[field] = "tool_failed"
                    continue
                actual = [json.loads(value) for value in sorted(values)]
            assessments.append(FieldAssessment(
                field=field, status=status, actual_value=actual,
                reason=str(row.get("reason") or "governed_field_checked"), evidence=refs,
            ))
            attempts.pop(field)
        return assessments, attempts

    def _batch(
        self,
        result: Any,
        constraint_set: ConstraintSet,
        products: dict[str, dict[str, Any]],
        scope: ResolvedProductScope,
    ) -> VerificationBatch:
        now = _utc_now()
        if result.status != "success":
            return VerificationBatch(
                verifier_version=self.checker.VERSION, checked_at=now,
                constraint_set_version=constraint_set.version,
                semantic_fingerprint=hashlib.sha256(b"checker-failed").hexdigest(),
                degraded=True, degrade_reason=result.error_code or "checker_failed",
            )
        result_ids = {str(row.get("product_id")) for row in result.data.get("results", [])}
        if not result_ids <= set(scope.product_ids):
            return VerificationBatch(
                verifier_version=self.checker.VERSION,
                checked_at=now,
                constraint_set_version=constraint_set.version,
                semantic_fingerprint=hashlib.sha256(b"checker-scope-mismatch").hexdigest(),
                degraded=True,
                degrade_reason="checker_scope_mismatch",
            )
        active = {item.field: item for item in constraint_set.active(hard_only=True, supported_only=True)}
        candidates = []
        for row in result.data["results"]:
            converted = []
            for decision in row["constraint_results"]:
                constraint = active[decision["field_id"]]
                refs = self._references(
                    products[row["product_id"]], {decision["field_id"]}, scope
                )
                converted.append(
                    ConstraintResult(
                        constraint=constraint,
                        actual_value=decision["actual_value"],
                        status=_verification_status(decision["state"]),
                        reason=decision["reason"],
                        evidence_id=refs[0].evidence_id if refs else None,
                        source_id=refs[0].source_id if refs else None,
                    )
                )
            overall = (
                VerificationStatus.PASSED if row["eligible"] else
                VerificationStatus.FAILED if row["violations"] else
                VerificationStatus.CONFLICT if row["conflicts"] else VerificationStatus.UNKNOWN
            )
            source_ids = sorted({
                item.source_id
                for item in self._references(products[row["product_id"]], set(active), scope)
            })
            candidates.append(
                CandidateVerification(
                    model_id=row["product_id"], overall_status=overall,
                    constraint_results=converted, eligible=row["eligible"],
                    violated_fields=row["violations"], unknown_fields=row["unknown_fields"],
                    conflict_fields=row["conflicts"],
                    unsupported_constraints=row["unsupported_constraints"],
                    evidence_ids=row["evidence_ids"], source_ids=source_ids,
                    checked_at=now, verifier_version=row["checker_version"],
                )
            )
        eligible = [item.model_id for item in candidates if item.eligible]
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "constraints": [item.model_dump(mode="json") for item in active.values()],
                    "pool": [item.model_id for item in candidates],
                    "scope": scope.fingerprint,
                    "data_version": self.repository.snapshot.data_version,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return VerificationBatch(
            verifier_version=self.checker.VERSION, checked_at=now,
            constraint_set_version=constraint_set.version,
            candidate_pool_model_ids=[item.model_id for item in candidates],
            candidates=candidates, eligible_model_ids=eligible,
            rejected_model_ids=[item.model_id for item in candidates if not item.eligible],
            semantic_fingerprint=fingerprint,
        )

    @staticmethod
    def _empty_batch(
        candidate_ids: list[str],
        constraint_set: ConstraintSet,
        scope: ResolvedProductScope | None = None,
    ) -> VerificationBatch:
        now = _utc_now()
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "pool": candidate_ids,
                    "constraints": [],
                    "scope": scope.fingerprint if scope else None,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return VerificationBatch(
            verifier_version="proofpick-domain-checker-v2-6b", checked_at=now,
            constraint_set_version=constraint_set.version,
            candidate_pool_model_ids=candidate_ids, semantic_fingerprint=fingerprint,
        )

    async def run(
        self,
        query: str,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        use_long_term_memory: bool = False,
        mode: ResearchMode = ResearchMode.TRUSTED,
        thread_id: str | None = None,
        event_callback: EventCallback | None = None,
        constraint_resolution: ConstraintResolution | None = None,
        ranking_scenario: str | None = None,
        ranking_preferences: dict[str, Any] | None = None,
        ranking_weight_overrides: dict[str, float] | None = None,
        ranking_use_memory: bool | None = None,
        ranking_what_if: bool = False,
    ) -> DecisionReport:
        if mode != ResearchMode.TRUSTED:
            raise ValueError("DomainDecisionAgent handles Trusted Mode only")
        started = time.perf_counter()
        trace: list[ToolTrace] = []
        await emit_event(event_callback, {"type": "domain_context_selected", "domain_id": self.pack.domain_id,
                                          "domain_pack_version": self.pack.version,
                                          "data_version": self.repository.snapshot.data_version})
        products = self.repository.load()
        index_version = getattr(self.kb_search, "index_version", None)
        index_manager = getattr(self.kb_search, "index_manager", None)
        if index_manager is not None:
            try:
                index_version = index_manager.current().index_version
            except Exception:
                index_version = None
        scope = ProductIdentityResolver(
            domain_id=self.pack.domain_id,
            data_version=self.repository.snapshot.data_version,
            index_version=index_version,
            qualifier_aliases={
                field_id: {
                    **definition.value_aliases,
                    **{value: value for value in definition.enum_values},
                }
                for field_id, definition in self.pack.fields.items()
                if definition.value_aliases or definition.enum_values
            },
        ).resolve(query, products)
        understanding = QueryUnderstandingEngine(self.pack).analyze(query, scope)
        intent = understanding.intent
        scope = scope.model_copy(update={
            "query_intent": intent,
            "requested_fields": understanding.requested_fields,
        })
        await emit_event(
            event_callback,
            {
                "type": "product_scope_resolved",
                "domain_id": scope.domain_id,
                "scope_type": scope.scope_type.value,
                "resolution_status": scope.resolution_status.value,
                "candidate_count": len(scope.product_ids),
                "mention_count": len(scope.mentions),
                "clarification_required": scope.clarification_required,
                "scope_fingerprint": scope.fingerprint,
                "query_intent": intent.value,
                "requested_fields": understanding.requested_fields,
            },
        )
        if scope.resolution_status in {
            ProductScopeResolutionStatus.OPEN_REQUIRED,
            ProductScopeResolutionStatus.NO_MATCH,
        }:
            initial_status = (
                "insufficient_evidence"
                if scope.resolution_status == ProductScopeResolutionStatus.OPEN_REQUIRED
                else "no_matching_candidate"
            )
            return DecisionReport(
                request_summary=query,
                product_scope=scope,
                query_intent=intent,
                requested_fields=understanding.requested_fields,
                task_type="fact" if intent == QueryIntent.OPEN_PRODUCT_RESEARCH else "filter",
                clarification_state=ClarificationState.NOT_REQUIRED,
                constraint_verification=self._empty_batch([], ConstraintSet(), scope),
                unresolved_facts=[UnresolvedFact(
                    field="product_id",
                    status="unknown",
                    reason=(
                        "本地治理目录中没有该商品身份；仅返回待进入 Open Mode 状态。"
                        if scope.scope_type == ProductScopeType.OPEN_UNKNOWN_PRODUCT
                        else "身份包含/排除集合计算后没有候选。"
                    ),
                )],
                abstained=True,
                stop_reason="Trusted Mode 未获得可用候选，已安全停止。",
                usage={
                    "domain_id": self.pack.domain_id,
                    "data_version": self.repository.snapshot.data_version,
                    "index_version": index_version,
                    "scope_fingerprint": scope.fingerprint,
                    "provider_calls": 0,
                    "result_status": initial_status,
                },
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        if (
            scope.resolution_status == ProductScopeResolutionStatus.NEEDS_CLARIFICATION
            and understanding.intent != QueryIntent.RECOMMENDATION_FILTER
        ):
            early_coverage = audit_requirement_coverage(
                query, ConstraintSet(), self.pack,
                purchase=intent == QueryIntent.CLARIFICATION_REQUIRED,
            )
            return DecisionReport(
                request_summary=query,
                product_scope=scope,
                query_intent=QueryIntent.CLARIFICATION_REQUIRED,
                requested_fields=understanding.requested_fields,
                task_type="fact",
                clarification_state=ClarificationState.PENDING,
                constraint_verification=self._empty_batch([], ConstraintSet(), scope),
                pending_questions=["请明确具体商品配置、地区或可执行阈值。"],
                abstained=True,
                stop_reason="商品身份或条件存在歧义；未调用模型、检索工具或 Checker。",
                usage={
                    "domain_id": self.pack.domain_id,
                    "data_version": self.repository.snapshot.data_version,
                    "index_version": index_version,
                    "scope_fingerprint": scope.fingerprint,
                    "provider_calls": 0,
                    "result_status": "needs_clarification",
                    "requirement_coverage": early_coverage.public(),
                },
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        session_key = self._session_key(session_id, user_id)
        previous = self._session_constraints.get(session_key or "")
        memory_requested = (
            use_long_term_memory if ranking_use_memory is None else ranking_use_memory
        )
        memory_snapshot = self.preference_memory.recall_with_sources(
            user_id,
            requested=bool(memory_requested and user_id),
        )
        memory_preferences = dict(memory_snapshot["preferences"])
        if constraint_resolution is None:
            preferences = {
                key: value
                for key, value in memory_preferences.items()
                if key in self.preference_memory.allowed
            }
            constraint_resolution = await self.constraint_engine.resolve(
                query, source_turn=1, previous=previous, preferences=preferences,
            )
        if constraint_resolution is None:
            constraint_resolution = ConstraintResolution(query=query, source_turn=1)
        mentioned = list(scope.include_product_ids or scope.product_ids)
        constraint_resolution = self._repair_pack_proposals(query, constraint_resolution, products)
        constraint_resolution = self._add_catalog_value_proposals(
            query, constraint_resolution, products, intent, scope
        )
        constraint_resolution = self._add_region_proposals(
            query, constraint_resolution, scope, intent
        )
        constraint_resolution = self._separate_requested_fields(
            constraint_resolution, intent
        )
        constraint_resolution = self._canonicalize_resolution(
            query, constraint_resolution, products, mentioned, intent
        )
        constraint_resolution = self._reconcile_identity_resolution(
            constraint_resolution, scope, products
        )
        coverage = audit_requirement_coverage(
            query, constraint_resolution.constraint_set, self.pack,
            purchase=intent in {QueryIntent.RECOMMENDATION_FILTER, QueryIntent.CLARIFICATION_REQUIRED},
            resolution=constraint_resolution,
        )
        await emit_event(event_callback, {
            "type": "requirement_coverage_checked", "domain_id": self.pack.domain_id,
            "complete": coverage.complete, "obligation_count": len(coverage.obligations),
            "unresolved_fields": sorted({item["field"] for item in coverage.obligations if not item["resolved"]}),
        })
        if not coverage.complete:
            return DecisionReport(
                request_summary=query, product_scope=scope,
                query_intent=QueryIntent.CLARIFICATION_REQUIRED,
                requested_fields=understanding.requested_fields, task_type="filter",
                constraint_set=constraint_resolution.constraint_set,
                constraint_proposals=constraint_resolution.proposals,
                clarification_state=ClarificationState.PENDING,
                constraint_diff=constraint_resolution.diff,
                constraint_deltas=ConstraintDeltaResolver.from_resolution(constraint_resolution),
                constraint_verification=self._empty_batch([], constraint_resolution.constraint_set, scope),
                pending_questions=["请确认未完整解析的硬要求及其数值、单位或作用字段。"],
                abstained=True,
                stop_reason="明确硬要求未完整进入有效约束；已在工具执行前暂停。",
                usage={
                    "domain_id": self.pack.domain_id, "data_version": self.repository.snapshot.data_version,
                    "index_version": index_version, "scope_fingerprint": scope.fingerprint,
                    "provider_calls": constraint_resolution.provider_calls,
                    "requirement_coverage": coverage.public(), "result_status": "needs_clarification",
                },
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        constraints = self._tool_constraints(constraint_resolution)
        require_unique = bool(
            intent == QueryIntent.CLARIFICATION_REQUIRED
            or re.search(r"(?:哪一套|哪套|哪个配置|对应配置|返回配置|先确认|先问)", query)
        )
        scope, _transition = CandidateScopeReducer(self.pack).reduce(
            scope,
            products,
            constraints,
            intent=intent,
            require_unique=require_unique,
        )
        scope = scope.model_copy(update={
            "query_intent": (
                QueryIntent.CLARIFICATION_REQUIRED
                if scope.resolution_status == ProductScopeResolutionStatus.NEEDS_CLARIFICATION
                else intent
            ),
            "requested_fields": understanding.requested_fields,
        })
        if scope.resolution_status == ProductScopeResolutionStatus.NO_MATCH:
            return DecisionReport(
                request_summary=query,
                product_scope=scope,
                query_intent=intent,
                requested_fields=understanding.requested_fields,
                task_type="filter",
                constraint_set=constraint_resolution.constraint_set,
                constraint_proposals=constraint_resolution.proposals,
                constraint_diff=constraint_resolution.diff,
                constraint_deltas=ConstraintDeltaResolver.from_resolution(constraint_resolution),
                constraint_verification=self._empty_batch([], constraint_resolution.constraint_set, scope),
                abstained=True,
                stop_reason="结构化条件将候选集合收敛为空，未恢复全库。",
                usage={
                    "domain_id": self.pack.domain_id,
                    "data_version": self.repository.snapshot.data_version,
                    "index_version": index_version,
                    "scope_fingerprint": scope.fingerprint,
                    "provider_calls": constraint_resolution.provider_calls,
                    "result_status": "no_matching_candidate",
                    "requirement_coverage": coverage.public(),
                },
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        pending = (
            constraint_resolution.clarification_state == ClarificationState.PENDING
            or scope.resolution_status == ProductScopeResolutionStatus.NEEDS_CLARIFICATION
            or intent == QueryIntent.CLARIFICATION_REQUIRED
        )
        active_constraint_fields = {item["field"] for item in constraints}
        requested_fields = set(understanding.requested_fields)
        requested_fields -= (
            set(constraint_resolution.constraint_set.cancelled_fields)
            - active_constraint_fields
        )
        fields = (requested_fields | active_constraint_fields) & set(self.pack.fields)
        if intent == QueryIntent.EXPLICIT_COMPARISON:
            compared = [products[item] for item in scope.product_ids]
            if len({item["attributes"].get("configuration_id") for item in compared}) > 1:
                fields.add("configuration_id")
            if len({item["region"] for item in compared}) > 1:
                fields.add("region")
        if session_key and not pending:
            self._session_constraints[session_key] = constraint_resolution.constraint_set
        cross_region_inference = (
            intent != QueryIntent.RECOMMENDATION_FILTER
            and bool(set(scope.allowed_regions) - set(scope.regions))
            and bool(re.search(r"(?:能否用于|可否用于|能不能用于)", query))
        )
        if pending:
            batch = self._empty_batch([], constraint_resolution.constraint_set, scope)
            return DecisionReport(
                request_summary=query,
                product_scope=scope,
                query_intent=QueryIntent.CLARIFICATION_REQUIRED,
                requested_fields=understanding.requested_fields,
                task_type="filter",
                constraint_set=constraint_resolution.constraint_set,
                constraint_proposals=constraint_resolution.proposals,
                clarification_state=ClarificationState.PENDING,
                constraint_diff=constraint_resolution.diff,
                constraint_deltas=ConstraintDeltaResolver.from_resolution(constraint_resolution),
                constraint_verification=batch,
                pending_questions=[
                    constraint_resolution.clarification_question
                    or "请明确具体配置、地区或可执行阈值。"
                ],
                abstained=True,
                stop_reason="等待用户澄清；未调用收费检索工具、Checker 或长期 Memory 写入。",
                usage={"domain_id": self.pack.domain_id, "data_version": self.repository.snapshot.data_version,
                       "index_version": index_version, "scope_fingerprint": scope.fingerprint,
                       "provider_calls": constraint_resolution.provider_calls,
                       "result_status": "needs_clarification",
                       "requirement_coverage": coverage.public()},
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        candidate_ids = list(scope.product_ids)
        safety_blocked_reason: str | None = None
        try:
            assert_candidate_chain(
                catalog_ids=products,
                scope=scope,
                checker_pool_ids=candidate_ids if constraints else (),
                stage="before_checker",
            )
        except CandidateChainViolation as exc:
            safety_blocked_reason = exc.code
            await emit_event(
                event_callback,
                {
                    "type": "scope_violation",
                    "stage": exc.stage,
                    "reason": exc.code,
                    "scope_count": len(scope.product_ids),
                    "candidate_count": len(candidate_ids),
                    "action": "fail_closed",
                },
            )
        evidence_candidate_ids = list(candidate_ids)
        query_result = None
        if constraints:
            tool_started = time.perf_counter()
            query_result = self.product_query.run(constraints, scope=scope)
            await self._trace(event_callback, trace, query_result.tool, query_result.status,
                              query_result.summary, arguments={"constraint_fields": sorted(fields)},
                              duration_ms=(time.perf_counter() - tool_started) * 1000)
            if query_result.status == "success":
                narrowed_ids = {
                    row["product_id"] for row in query_result.data.get("rows", [])
                    if row["status"] in {"matched", "unknown"}
                }
                evidence_candidate_ids = sorted(set(scope.product_ids) & narrowed_ids)
                scope.assert_monotonic_transition(evidence_candidate_ids)

        kb_result = None
        if self.kb_search is not None and fields:
            tool_started = time.perf_counter()
            kb_result = await self.kb_search.run(
                query,
                product_id=scope.product_ids[0] if len(scope.product_ids) == 1 else None,
                scope=scope,
                vector_top_k=12,
                top_k=5,
            )
            await self._trace(event_callback, trace, kb_result.tool, kb_result.status,
                              kb_result.summary, arguments={"domain_id": self.pack.domain_id},
                              duration_ms=(time.perf_counter() - tool_started) * 1000)

        evidence_targets = (
            list(scope.product_ids)
            if intent == QueryIntent.EXPLICIT_COMPARISON
            else evidence_candidate_ids
        )
        fact_task = intent != QueryIntent.RECOMMENDATION_FILTER
        fact_assessments: dict[str, list[FieldAssessment]] = {}
        fact_attempts = {
            product_id: dict.fromkeys(fields, "budget_exhausted") for product_id in scope.product_ids
        } if fact_task else {}
        for product_id in evidence_targets[: max(0, self.max_tool_calls - len(trace) - 1)]:
            requested = self._fact_requests(products[product_id], fields) if fact_task else constraints
            if not requested:
                requested = [
                    {"field": field, "operator": "eq", "value": products[product_id]["attributes"].get(field),
                     "unit": self.pack.fields[field].unit}
                    for field in sorted(fields)
                    if field in self.pack.fields
                    and "eq" in {item.value for item in self.pack.fields[field].allowed_operators}
                ]
            if requested:
                if fact_task:
                    try:
                        evidence_result = self.evidence_check.run(product_id, requested, scope=scope)
                    except Exception:
                        evidence_result = ToolResult(tool="domain_evidence_check", status="failed", summary="字段核验未完成。", error_code="evidence_tool_failed")
                    fact_assessments[product_id], fact_attempts[product_id] = self._checked_fact_fields(
                        products[product_id], fields, evidence_result, scope, index_version=index_version,
                    )
                else:
                    evidence_result = self.evidence_check.run(product_id, requested, scope=scope)
                await self._trace(event_callback, trace, evidence_result.tool, evidence_result.status,
                                  evidence_result.summary, arguments={"product_id": product_id,
                                                                     "fields": [item["field"] for item in requested]})

        checker_required = bool(
            constraints
            and intent in {
                QueryIntent.RECOMMENDATION_FILTER,
                QueryIntent.EXACT_FACT_VERIFICATION,
            }
        )
        if checker_required and candidate_ids and safety_blocked_reason is None:
            checker_result = self.checker.run(
                constraints,
                candidate_ids=candidate_ids,
                scope=scope,
            )
            await self._trace(event_callback, trace, checker_result.tool, checker_result.status,
                              checker_result.summary, arguments={"candidate_pool_size": len(candidate_ids)})
            batch = self._batch(
                checker_result, constraint_resolution.constraint_set, products, scope
            )
            if batch.degraded and batch.degrade_reason == "checker_scope_mismatch":
                safety_blocked_reason = batch.degrade_reason
                await emit_event(
                    event_callback,
                    {
                        "type": "scope_violation",
                        "stage": "after_checker",
                        "reason": batch.degrade_reason,
                        "scope_count": len(scope.product_ids),
                        "checker_pool_count": len(
                            checker_result.data.get("results", [])
                        ),
                        "eligible_count": 0,
                        "action": "fail_closed",
                    },
                )
        else:
            batch = self._empty_batch([], constraint_resolution.constraint_set, scope)

        if checker_required and safety_blocked_reason is None:
            try:
                assert_candidate_chain(
                    catalog_ids=products,
                    scope=scope,
                    checker_pool_ids=batch.candidate_pool_model_ids,
                    checker_eligible_ids=batch.eligible_model_ids,
                    stage="after_checker",
                )
            except CandidateChainViolation as exc:
                safety_blocked_reason = exc.code
                await emit_event(
                    event_callback,
                    {
                        "type": "scope_violation",
                        "stage": exc.stage,
                        "reason": exc.code,
                        "scope_count": len(scope.product_ids),
                        "checker_pool_count": len(batch.candidate_pool_model_ids),
                        "eligible_count": len(batch.eligible_model_ids),
                        "action": "fail_closed",
                    },
                )
        if safety_blocked_reason is not None:
            batch = self._empty_batch(
                sorted(set(scope.product_ids) & set(products)),
                constraint_resolution.constraint_set,
                scope,
            ).model_copy(
                update={
                    "degraded": True,
                    "degrade_reason": safety_blocked_reason,
                }
            )

        recommended = list(batch.eligible_model_ids) if checker_required and not fact_task else []
        report_ids = sorted(set(
            batch.candidate_pool_model_ids if checker_required else candidate_ids
        ))
        try:
            assert_candidate_chain(
                catalog_ids=products,
                scope=scope,
                checker_pool_ids=(batch.candidate_pool_model_ids if checker_required else ()),
                checker_eligible_ids=(batch.eligible_model_ids if checker_required else ()),
                report_ids=report_ids,
                recommended_ids=recommended,
                stage="before_reporting",
            )
        except CandidateChainViolation as exc:
            safety_blocked_reason = exc.code
            await emit_event(
                event_callback,
                {
                    "type": "scope_violation",
                    "stage": exc.stage,
                    "reason": exc.code,
                    "scope_count": len(scope.product_ids),
                    "report_count": len(report_ids),
                    "recommendation_count": len(recommended),
                    "action": "fail_closed",
                },
            )
            recommended = []
            report_ids = sorted(set(report_ids) & set(scope.product_ids) & set(products))
            batch = self._empty_batch(
                report_ids,
                constraint_resolution.constraint_set,
                scope,
            ).model_copy(
                update={"degraded": True, "degrade_reason": safety_blocked_reason}
            )
        candidates = []
        all_evidence: list[EvidenceReference] = []
        unresolved: list[UnresolvedFact] = []
        verified_by_id = {item.model_id: item for item in batch.candidates}
        for product_id in report_ids:
            product = products[product_id]
            checked_fields = {item.field: item for item in fact_assessments.get(product_id, [])}
            refs = (
                [ref for item in checked_fields.values() for ref in item.evidence]
                if fact_task else self._references(product, fields, scope, index_version=index_version)
            )
            all_evidence.extend(refs)
            verification = verified_by_id.get(product_id)
            field_assessments = []
            for field in sorted(fields):
                if fact_task:
                    assessment = checked_fields.get(field)
                    if assessment is None:
                        attempt = fact_attempts.get(product_id, {}).get(field, "not_checked")
                        assessment = FieldAssessment(field=field, status=ConstraintStatus.UNKNOWN,
                                                     actual_value=None, reason=f"fact_check_{attempt}", evidence=[])
                    field_assessments.append(assessment)
                    if assessment.status in {ConstraintStatus.UNKNOWN, ConstraintStatus.CONFLICT}:
                        values = assessment.actual_value if isinstance(assessment.actual_value, list) else []
                        unresolved.append(UnresolvedFact(model_id=product_id, field=field,
                                                         status=assessment.status.value, values=values,
                                                         reason=assessment.reason, evidence=assessment.evidence))
                    continue
                field_refs = [item for item in refs if item.field == field]
                actual = product["attributes"].get(field)
                status = ConstraintStatus.MATCHED if field_refs and actual is not None else ConstraintStatus.UNKNOWN
                field_assessments.append(FieldAssessment(
                    field=field, status=status, actual_value=actual,
                    reason="governed_field_evidence" if status == ConstraintStatus.MATCHED else "missing_governed_evidence",
                    evidence=field_refs,
                ))
                if status == ConstraintStatus.UNKNOWN and product_id in evidence_targets:
                    unresolved.append(UnresolvedFact(model_id=product_id, field=field, status="unknown",
                                                     reason="目标配置缺少治理字段证据。"))
            overall = (
                ConstraintStatus.CONFLICT if fact_task and any(item.status == ConstraintStatus.CONFLICT for item in field_assessments) else
                ConstraintStatus.NOT_MATCHED if fact_task and any(item.status == ConstraintStatus.NOT_MATCHED for item in field_assessments) else
                ConstraintStatus.UNKNOWN if fact_task and any(item.status == ConstraintStatus.UNKNOWN for item in field_assessments) else
                ConstraintStatus.MATCHED if fact_task and field_assessments else
                ConstraintStatus.MATCHED if verification and verification.eligible else
                ConstraintStatus.NOT_MATCHED if verification and verification.overall_status == VerificationStatus.FAILED else
                ConstraintStatus.CONFLICT if verification and verification.overall_status == VerificationStatus.CONFLICT else
                ConstraintStatus.UNKNOWN if verification else
                ConstraintStatus.MATCHED if field_assessments and all(item.status == ConstraintStatus.MATCHED for item in field_assessments) else ConstraintStatus.UNKNOWN
            )
            candidates.append(CandidateDecision(
                model_id=product_id,
                product_id=product_id,
                domain_id=product["domain_id"],
                family_id=product["attributes"].get("family_id"),
                configuration_id=product["attributes"].get("configuration_id"),
                brand=product["brand"], model_name=product["model_name"],
                region=product["region"],
                data_version=self.repository.snapshot.data_version,
                index_version=index_version,
                overall_status=overall,
                fields=field_assessments, eligible=bool(not fact_task and verification and verification.eligible),
                verifier_status=verification.overall_status if verification else None,
                constraint_results=verification.constraint_results if verification else [],
                violated_fields=verification.violated_fields if verification else [],
                unknown_fields=verification.unknown_fields if verification else [],
                conflict_fields=verification.conflict_fields if verification else [],
                unsupported_constraints=verification.unsupported_constraints if verification else [],
                verifier_version=verification.verifier_version if verification else None,
                recommendation_reason="所有已激活硬约束均通过确定性复核。" if product_id in recommended else None,
                elimination_reason=("硬约束未全部通过或证据不足。" if checker_required and product_id not in recommended else None),
            ))

        ranking: RankingExplanation | None = None
        ranking_degraded_states: list[str] = []
        if checker_required and recommended:
            explicit_ranking_preferences = dict(ranking_preferences or {})
            explicit_weights = ranking_weight_overrides
            memory_weights = memory_preferences.get("ranking_weights")
            weights = (
                dict(explicit_weights)
                if explicit_weights is not None
                else dict(memory_weights) if isinstance(memory_weights, dict) else {}
            )
            weight_source = (
                "explicit"
                if explicit_weights is not None
                else memory_snapshot["sources"].get("ranking_weights", "explicit")
            )
            ranking_request = RankingRequest(
                domain_id=self.pack.domain_id,
                scenario=ranking_scenario,
                eligible_candidates=[
                    RankingCandidateInput(
                        product_id=product_id,
                        configuration_id=products[product_id]["attributes"].get(
                            "configuration_id"
                        ),
                        region=products[product_id]["region"],
                        values=dict(products[product_id]["attributes"]),
                        evidence=[
                            RankingEvidence(
                                evidence_id=row["evidence_id"],
                                source_id=row["source_id"],
                                source_type=row["source_type"],
                                field_id=row["field_id"],
                                normalized_value=row["normalized_value"],
                                region=row["region"],
                            )
                            for row in products[product_id]["evidence"]
                        ],
                    )
                    for product_id in recommended
                ],
                checker_eligible_ids=list(batch.eligible_model_ids),
                explicit_preferences=explicit_ranking_preferences,
                confirmed_memory_preferences=memory_preferences,
                memory_preference_sources=dict(memory_snapshot["sources"]),
                weight_overrides=weights,
                weight_override_source=weight_source,
                ranking_profile_version=self.ranking_profile_version,
                data_version=self.repository.snapshot.data_version,
                domain_pack_version=self.pack.version,
                memory_enabled=bool(memory_snapshot["enabled"]),
                what_if=ranking_what_if,
            )
            await emit_event(
                event_callback,
                {
                    "type": "ranking_started",
                    "domain_id": self.pack.domain_id,
                    "eligible_count": len(recommended),
                    "scenario": ranking_scenario,
                    "what_if": ranking_what_if,
                },
            )
            try:
                if self.ranker is None:
                    raise RankingProfileError(
                        self._ranking_profile_error or "ranking_profile_unavailable"
                    )
                ranking = self.ranker.rank(ranking_request)
            except Exception as exc:
                ranking = stable_fallback(ranking_request, type(exc).__name__)
                ranking_degraded_states.append("ranking_degraded")
            if memory_snapshot.get("degraded_reasons"):
                reasons = list(
                    dict.fromkeys(
                        [
                            *ranking.degraded_reasons,
                            *memory_snapshot["degraded_reasons"],
                        ]
                    )
                )
                ranking = ranking.model_copy(
                    update={
                        "degraded_reasons": reasons,
                        "ranking_degraded": True,
                    }
                )
                ranking_degraded_states.append("ranking_degraded")
            recommended = ranking.ranked_ids
            ranked_by_id = {
                item.product_id: item for item in ranking.candidate_contributions
            }
            candidates = [
                candidate.model_copy(
                    update={
                        "rank": ranked_by_id[candidate.model_id].rank,
                        "ranking_score": ranked_by_id[candidate.model_id].total_score,
                        "ranking_advantages": ranked_by_id[candidate.model_id].advantages,
                        "ranking_tradeoffs": ranked_by_id[candidate.model_id].tradeoffs,
                    }
                )
                if candidate.model_id in ranked_by_id
                else candidate
                for candidate in candidates
            ]
            await emit_event(
                event_callback,
                {
                    "type": "ranking_completed",
                    "domain_id": self.pack.domain_id,
                    "scenario": ranking.active_scenario,
                    "eligible_count": len(recommended),
                    "ranked_product_ids": recommended,
                    "ranking_degraded": ranking.ranking_degraded,
                    "ranking_profile_version": ranking.ranking_profile_version,
                    "memory_enabled": ranking.memory_enabled,
                },
            )

        unsupported = [item for item in constraint_resolution.proposals if item.status.value == "unsupported"]
        recommendation_task = intent == QueryIntent.RECOMMENDATION_FILTER
        evidence_complete_ids = {
            item.model_id
            for item in candidates
            if item.fields and all(field.status == ConstraintStatus.MATCHED for field in item.fields)
        }
        result_classification = classify_result(
            ResultClassificationInput(
                recommendation_task=recommendation_task,
                clarification_required=pending,
                unsupported_request=bool(unsupported),
                tool_failure=any(item.status == "failed" for item in trace),
                safety_blocked=safety_blocked_reason is not None,
                candidate_count=len(candidates),
                eligible_count=len(recommended),
                evidence_complete_count=(
                    len(evidence_complete_ids & set(recommended))
                    if recommendation_task else len(evidence_complete_ids)
                ),
                unknown_or_conflict_count=sum(
                    item.overall_status in {ConstraintStatus.UNKNOWN, ConstraintStatus.CONFLICT}
                    for item in candidates
                ) + int(cross_region_inference),
            )
        )
        fact_completion = None
        if fact_task:
            fact_completion = build_fact_completion(
                list(scope.product_ids), sorted(fields), fact_assessments,
                identities={product_id: product_identity(products[product_id], data_version=self.repository.snapshot.data_version, index_version=index_version)
                            for product_id in scope.product_ids},
                attempts=fact_attempts,
            )
            sufficient = bool(fact_completion["answer_sufficient"]) and not cross_region_inference
            result_classification = classify_result(ResultClassificationInput(
                recommendation_task=False, clarification_required=pending, unsupported_request=bool(unsupported),
                tool_failure=any(item.status == "failed" for item in trace),
                safety_blocked=safety_blocked_reason is not None,
                candidate_count=len(candidates), evidence_complete_count=len(candidates) if sufficient else 0,
            ))
            await emit_event(event_callback, {"type": "fact_completion_checked", "domain_id": self.pack.domain_id,
                                               "fact_completion": fact_completion})
        abstained = result_classification.abstained
        if kb_result and kb_result.status in {"success", "degraded"}:
            index_version = kb_result.data.get("index_version", index_version)
        return DecisionReport(
            request_summary=query,
            product_scope=scope,
            query_intent=intent,
            requested_fields=understanding.requested_fields,
            task_type=(
                "comparison" if intent == QueryIntent.EXPLICIT_COMPARISON
                else "filter" if intent == QueryIntent.RECOMMENDATION_FILTER
                else "fact"
            ),
            constraint_set=constraint_resolution.constraint_set,
            constraint_proposals=constraint_resolution.proposals,
            clarification_state=constraint_resolution.clarification_state,
            constraint_diff=constraint_resolution.diff,
            constraint_deltas=ConstraintDeltaResolver.from_resolution(constraint_resolution),
            constraint_verification=batch,
            soft_preferences=[item.source_text for item in constraint_resolution.constraint_set.active() if item.hard_or_soft.value == "soft"],
            tools_used=[item.tool for item in trace], candidates=candidates,
            recommended_model_ids=recommended,
            eliminated_model_ids=[item for item in report_ids if checker_required and item not in recommended],
            evidence=all_evidence,
            unresolved_facts=[
                *unresolved,
                *(
                    [UnresolvedFact(
                        field="region", status="unknown",
                        reason="目标地区配置没有可比治理证据，禁止跨地区推断。",
                    )]
                    if cross_region_inference else []
                ),
            ],
            degraded_states=(
                ([kb_result.error_code or "kb_search_degraded"] if kb_result and kb_result.status in {"failed", "degraded"} else [])
                + ranking_degraded_states
            ),
            pending_questions=[item.clarification_question for item in unsupported if item.clarification_question],
            abstained=abstained,
            stop_reason=(
                "请求字段已逐一执行核验；存在 unknown/conflict，不能声明全部事实已经确定。"
                if fact_completion and fact_completion["completion_status"] == "complete" and not fact_completion["answer_sufficient"]
                else "请求字段核验尚未完成；未执行、失败或预算耗尽的字段保留未完成状态。"
                if fact_completion and fact_completion["completion_status"] != "complete"
                else result_classification.reason
            ),
            trace=trace, tool_call_count=len(trace),
            latency_ms=(time.perf_counter() - started) * 1000,
            usage={
                "domain_id": self.pack.domain_id,
                "domain_pack_version": self.pack.version,
                "data_version": self.repository.snapshot.data_version,
                "index_version": index_version,
                "complete_candidate_pool_size": len(scope.product_ids),
                "scope_fingerprint": scope.fingerprint,
                "provider_calls": constraint_resolution.provider_calls,
                "input_tokens": constraint_resolution.input_tokens,
                "output_tokens": constraint_resolution.output_tokens,
                "estimated_cost_cny": constraint_resolution.estimated_cost_cny,
                "result_status": result_classification.status.value,
                "requirement_coverage": coverage.public(),
                "result_reason": result_classification.reason,
                "safety_blocked": safety_blocked_reason is not None,
                "ranking_profile_version": self.ranking_profile_version,
                "ranking_model_calls": 0,
                **({"fact_completion": fact_completion} if fact_completion is not None else {}),
            },
            ranking=ranking,
        )
