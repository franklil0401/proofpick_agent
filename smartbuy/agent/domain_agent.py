"""Pack-driven Agent workflow shared by every installed V2 product category."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from typing import Any

from smartbuy.constraint_proposals import ClarificationState, ConstraintResolution
from smartbuy.constraint_proposals.models import ProposalSource
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.constraints import (
    CandidateVerification,
    ConstraintResult,
    ConstraintSet,
    ConstraintOperator,
    ConstraintProvenance,
    ConstraintStrength,
    NormalizedConstraint,
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
from smartbuy.memory import DomainPreferenceMemoryStore
from smartbuy.orchestration.contracts import EventCallback, emit_event
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainKBSearchTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)


_FACT_MARKERS = ("多少", "是什么", "哪个", "属于", "核验", "是否", "能否", "比较", "区分")
_COMPARE_MARKERS = ("比较", "对比", "区分", "是否等同", "不要把", "不能混")


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
            terms = [field_id, definition.label, *definition.aliases]
            if any(term and term.casefold() in folded for term in terms):
                output.append(field_id)
        return list(dict.fromkeys(output))

    @staticmethod
    def _identity_values(product: dict[str, Any]) -> list[str]:
        attributes = product["attributes"]
        values = [
            product["product_id"], product["model_name"], product["brand"],
            *product.get("aliases", []),
        ]
        for field_id, value in attributes.items():
            if field_id.endswith("_id") or field_id in {"part_number", "model_name"}:
                if value is not None:
                    values.append(str(value))
        return values

    def _mentioned_products(self, query: str, products: dict[str, dict[str, Any]]) -> list[str]:
        compact_query = _compact(query)
        scored: list[tuple[int, str]] = []
        for product_id, product in products.items():
            matches = []
            for value in self._identity_values(product):
                compact = _compact(value)
                if compact and len(compact) >= 4 and compact in compact_query:
                    matches.append(len(compact))
                matches.extend(
                    len(token)
                    for token in re.findall(r"[a-z0-9]+", value.casefold())
                    if len(token) >= 4 and token in compact_query
                )
            if matches:
                scored.append((max(matches), product_id))
        if not scored:
            return []
        longest = max(score for score, _ in scored)
        # Exact configuration identifiers win; family/model mentions intentionally keep siblings.
        threshold = longest if longest >= 8 else 4
        return sorted(product_id for score, product_id in scored if score >= threshold)

    @staticmethod
    def _narrow_fact_by_literal_values(
        query: str,
        candidate_ids: list[str],
        products: dict[str, dict[str, Any]],
    ) -> list[str]:
        """Use literal catalog values only as fact-query identity qualifiers."""
        if len(candidate_ids) < 2:
            return candidate_ids
        compact_query = _compact(query)
        narrowed = set(candidate_ids)
        fields = set().union(*(products[item]["attributes"] for item in candidate_ids))
        for field in fields:
            matching = {
                product_id
                for product_id in candidate_ids
                if isinstance((value := products[product_id]["attributes"].get(field)), str)
                and len(_compact(value)) >= 3
                and _compact(value) in compact_query
            }
            if matching and matching != set(candidate_ids):
                narrowed &= matching
        return sorted(narrowed or set(candidate_ids))

    def _repair_pack_list_proposals(
        self,
        query: str,
        resolution: ConstraintResolution,
        products: dict[str, dict[str, Any]],
    ) -> ConstraintResolution:
        repaired = []
        for proposal in resolution.proposals:
            if proposal.status.value != "invalid" or proposal.source_span is None:
                continue
            definition = self.pack.fields.get(proposal.field)
            if definition is None or definition.data_type.value != "string_list":
                continue
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
            if not chosen:
                continue
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
        if not repaired:
            return resolution
        constraint_set, activated, diffs = self.constraint_engine._apply(
            resolution.constraint_set, repaired
        )
        return resolution.model_copy(update={
            "proposals": [*resolution.proposals, *activated],
            "constraint_set": constraint_set,
            "diff": [*resolution.diff, *diffs],
        })

    def _canonicalize_resolution(
        self,
        query: str,
        resolution: ConstraintResolution,
        products: dict[str, dict[str, Any]],
        mentioned: list[str],
        intent: str,
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
        active_fields = {item.field for item in updated if item.active}
        if intent == "filter" and len(mentioned) > 1 and "family_id" in self.pack.fields and "family_id" not in active_fields:
            families = {products[item]["attributes"].get("family_id") for item in mentioned}
            families.discard(None)
            if len(families) == 1:
                family = next(iter(families))
                updated.append(NormalizedConstraint(
                    field="family_id", operator=ConstraintOperator.EQ,
                    normalized_value=family, hard_or_soft=ConstraintStrength.HARD,
                    provenance=ConstraintProvenance.CURRENT_INPUT, source_text=query,
                    source_turn=1, confidence=1.0,
                    note="deterministic_identity_binding",
                ))
        return resolution.model_copy(
            update={"constraint_set": resolution.constraint_set.model_copy(update={"constraints": updated})}
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
    ) -> list[EvidenceReference]:
        output = []
        for row in product["evidence"]:
            if row["field_id"] not in fields:
                continue
            output.append(
                EvidenceReference(
                    evidence_id=row["evidence_id"], source_id=row["source_id"],
                    source_url=row["source_url"], source_type=row["source_type"],
                    model_id=product["product_id"], region=row["region"],
                    field=row["field_id"], value=row["normalized_value"],
                    location="governed field evidence", effective_time=row["observed_at"],
                )
            )
        return output

    def _batch(
        self,
        result: Any,
        constraint_set: ConstraintSet,
        products: dict[str, dict[str, Any]],
    ) -> VerificationBatch:
        now = _utc_now()
        if result.status != "success":
            return VerificationBatch(
                verifier_version=self.checker.VERSION, checked_at=now,
                constraint_set_version=constraint_set.version,
                semantic_fingerprint=hashlib.sha256(b"checker-failed").hexdigest(),
                degraded=True, degrade_reason=result.error_code or "checker_failed",
            )
        active = {item.field: item for item in constraint_set.active(hard_only=True, supported_only=True)}
        candidates = []
        for row in result.data["results"]:
            converted = []
            for decision in row["constraint_results"]:
                constraint = active[decision["field_id"]]
                refs = self._references(products[row["product_id"]], {decision["field_id"]})
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
            source_ids = sorted({item.source_id for item in self._references(products[row["product_id"]], set(active))})
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
    def _empty_batch(candidate_ids: list[str], constraint_set: ConstraintSet) -> VerificationBatch:
        now = _utc_now()
        fingerprint = hashlib.sha256(
            json.dumps({"pool": candidate_ids, "constraints": []}, sort_keys=True).encode()
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
    ) -> DecisionReport:
        if mode != ResearchMode.TRUSTED:
            raise ValueError("DomainDecisionAgent handles Trusted Mode only")
        started = time.perf_counter()
        trace: list[ToolTrace] = []
        await emit_event(event_callback, {"type": "domain_context_selected", "domain_id": self.pack.domain_id,
                                          "domain_pack_version": self.pack.version,
                                          "data_version": self.repository.snapshot.data_version})
        products = self.repository.load()
        intent = self._intent(query)
        previous = self._session_constraints.get(session_id or "")
        if constraint_resolution is None:
            preferences = self.preference_memory.recall(user_id or "anonymous", requested=use_long_term_memory)
            constraint_resolution = await self.constraint_engine.resolve(
                query, source_turn=1, previous=previous, preferences=preferences,
            )
        if constraint_resolution is None:
            constraint_resolution = ConstraintResolution(query=query, source_turn=1)
        mentioned = self._mentioned_products(query, products)
        if intent == "fact":
            mentioned = self._narrow_fact_by_literal_values(query, mentioned, products)
        constraint_resolution = self._repair_pack_list_proposals(query, constraint_resolution, products)
        constraint_resolution = self._canonicalize_resolution(
            query, constraint_resolution, products, mentioned, intent
        )
        if session_id and constraint_resolution.clarification_state != ClarificationState.PENDING:
            self._session_constraints[session_id] = constraint_resolution.constraint_set
        constraints = self._tool_constraints(constraint_resolution)
        fields = set(self._field_mentions(query)) | {item["field"] for item in constraints}
        pending = constraint_resolution.clarification_state == ClarificationState.PENDING
        cross_region_inference = (
            intent != "filter"
            and "能否用于" in query
            and any(item.field == "region" for item in constraint_resolution.constraint_set.active())
        )
        if pending:
            batch = self._empty_batch([], constraint_resolution.constraint_set)
            return DecisionReport(
                request_summary=query, task_type="filter",
                constraint_set=constraint_resolution.constraint_set,
                constraint_proposals=constraint_resolution.proposals,
                clarification_state=constraint_resolution.clarification_state,
                constraint_diff=constraint_resolution.diff,
                constraint_verification=batch, pending_questions=[constraint_resolution.clarification_question or "请确认约束。"],
                abstained=True, stop_reason="等待用户澄清，未进入 Checker。",
                usage={"domain_id": self.pack.domain_id, "data_version": self.repository.snapshot.data_version,
                       "index_version": None, "provider_calls": constraint_resolution.provider_calls},
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        candidate_ids = mentioned or sorted(products)
        query_result = None
        if constraints:
            tool_started = time.perf_counter()
            query_result = self.product_query.run(constraints)
            await self._trace(event_callback, trace, query_result.tool, query_result.status,
                              query_result.summary, arguments={"constraint_fields": sorted(fields)},
                              duration_ms=(time.perf_counter() - tool_started) * 1000)
            if intent != "filter" and query_result.status == "success":
                matched_ids = {
                    row["product_id"] for row in query_result.data.get("rows", [])
                    if row["status"] == "matched"
                }
                candidate_ids = sorted((set(mentioned) & matched_ids) if mentioned else matched_ids)

        kb_result = None
        if self.kb_search is not None and (mentioned or fields):
            tool_started = time.perf_counter()
            kb_result = await self.kb_search.run(
                query,
                product_id=mentioned[0] if len(mentioned) == 1 else None,
                vector_top_k=12,
                top_k=5,
            )
            await self._trace(event_callback, trace, kb_result.tool, kb_result.status,
                              kb_result.summary, arguments={"domain_id": self.pack.domain_id},
                              duration_ms=(time.perf_counter() - tool_started) * 1000)

        evidence_targets = candidate_ids if intent != "filter" else mentioned or (
            [row["product_id"] for row in query_result.data.get("rows", []) if row["status"] == "matched"]
            if query_result and query_result.status == "success" else []
        )
        for product_id in evidence_targets[: max(0, self.max_tool_calls - len(trace) - 1)]:
            requested = constraints
            if not requested:
                requested = [
                    {"field": field, "operator": "eq", "value": products[product_id]["attributes"].get(field),
                     "unit": self.pack.fields[field].unit}
                    for field in sorted(fields)
                    if field in self.pack.fields and products[product_id]["attributes"].get(field) is not None
                    and "eq" in {item.value for item in self.pack.fields[field].allowed_operators}
                ]
            if requested:
                evidence_result = self.evidence_check.run(product_id, requested)
                await self._trace(event_callback, trace, evidence_result.tool, evidence_result.status,
                                  evidence_result.summary, arguments={"product_id": product_id,
                                                                     "fields": [item["field"] for item in requested]})

        if constraints and intent == "filter":
            checker_result = self.checker.run(constraints, candidate_ids=sorted(products))
            await self._trace(event_callback, trace, checker_result.tool, checker_result.status,
                              checker_result.summary, arguments={"candidate_pool_size": len(products)})
            batch = self._batch(checker_result, constraint_resolution.constraint_set, products)
        else:
            batch = self._empty_batch(candidate_ids, constraint_resolution.constraint_set)

        recommended = list(batch.eligible_model_ids) if constraints and intent == "filter" else []
        report_ids = sorted(set(
            batch.candidate_pool_model_ids if constraints and intent == "filter" else candidate_ids
        ))
        candidates = []
        all_evidence: list[EvidenceReference] = []
        unresolved: list[UnresolvedFact] = []
        verified_by_id = {item.model_id: item for item in batch.candidates}
        for product_id in report_ids:
            product = products[product_id]
            refs = self._references(product, fields)
            all_evidence.extend(refs)
            verification = verified_by_id.get(product_id)
            field_assessments = []
            for field in sorted(fields):
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
                ConstraintStatus.MATCHED if verification and verification.eligible else
                ConstraintStatus.NOT_MATCHED if verification and verification.overall_status == VerificationStatus.FAILED else
                ConstraintStatus.CONFLICT if verification and verification.overall_status == VerificationStatus.CONFLICT else
                ConstraintStatus.UNKNOWN if verification else
                ConstraintStatus.MATCHED if field_assessments and all(item.status == ConstraintStatus.MATCHED for item in field_assessments) else ConstraintStatus.UNKNOWN
            )
            candidates.append(CandidateDecision(
                model_id=product_id, brand=product["brand"], model_name=product["model_name"],
                region=product["region"], overall_status=overall,
                fields=field_assessments, eligible=bool(verification and verification.eligible),
                verifier_status=verification.overall_status if verification else None,
                constraint_results=verification.constraint_results if verification else [],
                violated_fields=verification.violated_fields if verification else [],
                unknown_fields=verification.unknown_fields if verification else [],
                conflict_fields=verification.conflict_fields if verification else [],
                unsupported_constraints=verification.unsupported_constraints if verification else [],
                verifier_version=verification.verifier_version if verification else None,
                recommendation_reason="所有已激活硬约束均通过确定性复核。" if product_id in recommended else None,
                elimination_reason=("硬约束未全部通过或证据不足。" if constraints and intent == "filter" and product_id not in recommended else None),
            ))

        unsupported = [item for item in constraint_resolution.proposals if item.status.value == "unsupported"]
        state_update_only = any(item.action.value in {"cancel", "confirm"} for item in constraint_resolution.proposals)
        abstained = bool(
            pending
            or cross_region_inference
            or unsupported
            or (intent == "filter" and constraints and not recommended)
            or (intent != "filter" and (not candidate_ids or unresolved))
            or (intent == "filter" and not constraints and not state_update_only)
        )
        index_version = kb_result.data.get("index_version") if kb_result and kb_result.status in {"success", "degraded"} else None
        return DecisionReport(
            request_summary=query,
            task_type="comparison" if intent == "comparison" else "filter" if intent == "filter" else "fact",
            constraint_set=constraint_resolution.constraint_set,
            constraint_proposals=constraint_resolution.proposals,
            clarification_state=constraint_resolution.clarification_state,
            constraint_diff=constraint_resolution.diff,
            constraint_verification=batch,
            soft_preferences=[item.source_text for item in constraint_resolution.constraint_set.active() if item.hard_or_soft.value == "soft"],
            tools_used=[item.tool for item in trace], candidates=candidates,
            recommended_model_ids=recommended,
            eliminated_model_ids=[item for item in report_ids if constraints and intent == "filter" and item not in recommended],
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
            degraded_states=([kb_result.error_code or "kb_search_degraded"] if kb_result and kb_result.status in {"failed", "degraded"} else []),
            pending_questions=[item.clarification_question for item in unsupported if item.clarification_question],
            abstained=abstained,
            stop_reason=("没有可由治理证据确定的合规候选。" if abstained else "已完成字段证据核验与确定性安全门。"),
            trace=trace, tool_call_count=len(trace),
            latency_ms=(time.perf_counter() - started) * 1000,
            usage={
                "domain_id": self.pack.domain_id,
                "domain_pack_version": self.pack.version,
                "data_version": self.repository.snapshot.data_version,
                "index_version": index_version,
                "complete_candidate_pool_size": len(products),
                "provider_calls": constraint_resolution.provider_calls,
                "input_tokens": constraint_resolution.input_tokens,
                "output_tokens": constraint_resolution.output_tokens,
                "estimated_cost_cny": constraint_resolution.estimated_cost_cny,
            },
        )
