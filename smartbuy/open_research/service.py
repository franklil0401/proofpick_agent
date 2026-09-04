"""Governed Source Candidate -> Open Research pipeline."""

from __future__ import annotations

from smartbuy.source_search.validator import infer_region, model_matches_url

from smartbuy.domain_packs.loader import LoadedDomainPack
from smartbuy.open_research.evidence_check import OpenEvidenceChecker
from smartbuy.open_research.extractor import StaticHTMLExtractor
from smartbuy.open_research.models import (
    ExtractionStatus,
    OpenEvidenceStatus,
    OpenResearchOutcome,
    OpenResearchReport,
    WebExtractionResult,
)
from smartbuy.open_research.normalizer import EvidenceNormalizer, field_terms
from smartbuy.open_research.settings import OpenResearchSettings
from smartbuy.open_research.store import TemporaryEvidenceStore, scope_token
from smartbuy.source_search import SourceCandidate, SourceCandidateStatus


class OpenResearchService:
    def __init__(
        self,
        settings: OpenResearchSettings,
        pack: LoadedDomainPack,
        extractor: StaticHTMLExtractor,
        store: TemporaryEvidenceStore,
        *,
        normalizer: EvidenceNormalizer | None = None,
        checker: OpenEvidenceChecker | None = None,
    ) -> None:
        self.settings = settings
        self.pack = pack
        self.extractor = extractor
        self.store = store
        self.normalizer = normalizer or EvidenceNormalizer(
            pack, ttl_seconds=settings.ttl_seconds
        )
        self.checker = checker or OpenEvidenceChecker()

    async def aclose(self) -> None:
        await self.extractor.aclose()

    async def research(
        self,
        candidate: SourceCandidate,
        *,
        target_fields: list[str],
        allowed_domains: list[str],
        provisional_product_id: str,
        configuration: str | None,
        user_id: str | None,
        session_id: str | None,
        thread_id: str | None,
        request_id: str,
        allow_region_discovery: bool = False,
    ) -> OpenResearchOutcome:
        terms = field_terms(self.pack, target_fields)
        trace = ["source_candidate_validated"]
        opaque_user = scope_token(user_id, "anonymous")
        opaque_session = scope_token(session_id, "stateless")
        opaque_thread = scope_token(thread_id, session_id or "stateless")
        opaque_request = scope_token(request_id, "request")
        selected = candidate
        recovery_attempted = False
        recovery_succeeded = False
        if candidate.status in {
            SourceCandidateStatus.REGION_MISMATCH,
            SourceCandidateStatus.REGION_UNKNOWN,
        }:
            recovery_attempted = allow_region_discovery
            if not allow_region_discovery:
                extraction = await self.extractor.extract(
                    candidate,
                    target_fields=target_fields,
                    field_terms=terms,
                    allowed_domains=allowed_domains,
                )
            else:
                inspection, discovered = await self.extractor.discover_target_candidate(
                    candidate,
                    target_fields=target_fields,
                    field_terms=terms,
                    allowed_domains=allowed_domains,
                )
                trace.extend(["navigation_page_inspected", "canonical_hreflang_checked"])
                if discovered is None:
                    report = OpenResearchReport(
                        provisional_product_id=provisional_product_id,
                        target_model=candidate.target_model,
                        product_region=candidate.target_region,
                        configuration=configuration,
                        status="degraded",
                        source_url=candidate.url,
                        final_url=inspection.final_url,
                        source_title=inspection.title or candidate.title,
                        fetched_at=inspection.fetched_at,
                        unknown_fields=list(dict.fromkeys(target_fields)),
                        tool_trace=trace,
                        degraded_reasons=[
                            "canonical/hreflang 未发现可安全核验的目标地区页面；继续返回 no_region_matched_source。"
                        ],
                    )
                    return OpenResearchOutcome(
                        report=report,
                        extraction=inspection,
                        temporary_store_status="empty",
                        canonical_recovery_attempted=True,
                        canonical_recovery_succeeded=False,
                    )
                selected = discovered
                recovery_succeeded = True
                trace.append("target_region_candidate_discovered")
                extraction = await self.extractor.extract(
                    selected,
                    target_fields=target_fields,
                    field_terms=terms,
                    allowed_domains=allowed_domains,
                )
        else:
            extraction = await self.extractor.extract(
                selected,
                target_fields=target_fields,
                field_terms=terms,
                allowed_domains=allowed_domains,
            )
            if (
                allow_region_discovery
                and extraction.status == ExtractionStatus.EXTRACTION_INCOMPLETE
                and extraction.error == "final_page_region_not_matched"
            ):
                recovery_attempted = True
                inspection, discovered = await self.extractor.discover_target_candidate(
                    candidate,
                    target_fields=target_fields,
                    field_terms=terms,
                    allowed_domains=allowed_domains,
                )
                trace.extend(["final_region_rechecked", "canonical_hreflang_checked"])
                if discovered is not None:
                    selected = discovered
                    recovery_succeeded = True
                    trace.append("target_region_candidate_discovered")
                    extraction = await self.extractor.extract(
                        selected,
                        target_fields=target_fields,
                        field_terms=terms,
                        allowed_domains=allowed_domains,
                    )
                else:
                    extraction = inspection
        initial_extraction = extraction
        additional_extractions: list[WebExtractionResult] = []
        related_needed = extraction.status != ExtractionStatus.SUCCESS
        if extraction.status == ExtractionStatus.SUCCESS:
            probe_records, _ = self.normalizer.normalize(
                extraction,
                user_scope=opaque_user,
                session_scope=opaque_session,
                thread_scope=opaque_thread,
                request_scope=opaque_request,
                provisional_product_id=provisional_product_id,
                target_model=candidate.target_model,
                product_region=candidate.target_region,
                target_fields=target_fields,
                configuration=configuration,
            )
            related_needed = not set(target_fields).issubset(
                {item.field_name for item in probe_records}
            )
        if related_needed and extraction.related_links and self.settings.max_related_fetches:
            trace.append("model_bound_related_links_discovered")
            followed_urls = {value for value in (extraction.requested_url, extraction.final_url) if value}
            for link in extraction.related_links[: self.settings.max_related_fetches]:
                if link.url in followed_urls:
                    continue
                followed_urls.add(link.url)
                observed_region = infer_region(link.url)
                inherited_region = (
                    observed_region == "unknown"
                    and extraction.detected_region == candidate.target_region
                )
                if observed_region not in {"unknown", candidate.target_region}:
                    continue
                related_candidate = SourceCandidate(
                    title=link.label or extraction.title or candidate.title,
                    url=link.url,
                    hostname=None,
                    site_name=candidate.site_name,
                    date_published=candidate.date_published,
                    queried_at=candidate.queried_at,
                    local_request_id=candidate.local_request_id,
                    provider=candidate.provider,
                    engine="official_page_related_link",
                    target_model=candidate.target_model,
                    target_region=candidate.target_region,
                    observed_region=(
                        candidate.target_region if inherited_region else observed_region
                    ),
                    status=SourceCandidateStatus.REGION_MATCHED,
                    model_match_source=(
                        "url"
                        if model_matches_url(candidate.target_model, link.url)
                        else "title"
                    ),
                    region_match_source=(
                        "target_region_page_link" if inherited_region else "url"
                    ),
                )
                related_extraction = await self.extractor.extract(
                    related_candidate,
                    target_fields=target_fields,
                    field_terms=terms,
                    allowed_domains=allowed_domains,
                )
                additional_extractions.append(related_extraction)
                trace.append(f"related_{link.kind}_extraction_completed")
            if extraction.status != ExtractionStatus.SUCCESS:
                recovered = next(
                    (
                        item
                        for item in additional_extractions
                        if item.status == ExtractionStatus.SUCCESS
                    ),
                    None,
                )
                if recovered is not None:
                    extraction = recovered
                    recovery_attempted = True
                    recovery_succeeded = True
                    trace.append("related_source_recovery_succeeded")
        trace.append("web_extractor_completed")
        if extraction.status != ExtractionStatus.SUCCESS:
            report = OpenResearchReport(
                provisional_product_id=provisional_product_id,
                target_model=candidate.target_model,
                product_region=candidate.target_region,
                configuration=configuration,
                status="degraded",
                source_url=candidate.url,
                final_url=extraction.final_url,
                source_title=extraction.title or candidate.title,
                fetched_at=extraction.fetched_at,
                unknown_fields=list(dict.fromkeys(target_fields)),
                tool_trace=trace,
                degraded_reasons=[
                    f"网页抽取未完成：{extraction.error or extraction.status.value}；关键字段保持 unknown。"
                ],
            )
            return OpenResearchOutcome(
                report=report,
                extraction=extraction,
                additional_extractions=additional_extractions,
                temporary_store_status="empty",
                canonical_recovery_attempted=recovery_attempted,
                canonical_recovery_succeeded=recovery_succeeded,
            )

        records = []
        unsupported = []
        normalization_sources = [
            item
            for item in [initial_extraction, *additional_extractions]
            if item.status == ExtractionStatus.SUCCESS
        ]
        seen_evidence: set[str] = set()
        for source in normalization_sources:
            source_records, source_unsupported = self.normalizer.normalize(
                source,
                user_scope=opaque_user,
                session_scope=opaque_session,
                thread_scope=opaque_thread,
                request_scope=opaque_request,
                provisional_product_id=provisional_product_id,
                target_model=candidate.target_model,
                product_region=candidate.target_region,
                target_fields=target_fields,
                configuration=configuration,
            )
            for record in source_records:
                if record.evidence_id not in seen_evidence:
                    records.append(record)
                    seen_evidence.add(record.evidence_id)
            unsupported.extend(source_unsupported)
        unsupported = list(dict.fromkeys(unsupported))
        trace.append("evidence_normalizer_completed")
        store_status = "empty"
        store_degraded: str | None = None
        if records:
            try:
                written = self.store.write(records)
                store_status = "stored" if written else "disabled"
                if not written:
                    store_degraded = "临时证据存储已关闭，未写入磁盘。"
            except (OSError, ValueError):
                store_status = "failed"
                store_degraded = "临时证据原子写入失败；未触碰正式数据。"
        trace.append("temporary_evidence_store_completed")
        assessments = self.checker.assess(target_fields, records)
        trace.append("open_evidence_check_completed")
        verified = [
            item.field_name
            for item in assessments
            if item.status == OpenEvidenceStatus.MATCHED
        ]
        unknown = [
            item.field_name
            for item in assessments
            if item.status == OpenEvidenceStatus.UNKNOWN
        ]
        conflicts = [
            item.field_name
            for item in assessments
            if item.status == OpenEvidenceStatus.CONFLICT
        ]
        degraded_reasons: list[str] = []
        if unknown:
            degraded_reasons.append(
                "以下字段没有足够正文证据，保持 unknown：" + ", ".join(unknown)
            )
        if conflicts:
            degraded_reasons.append(
                "以下字段存在来源冲突，未静默选择：" + ", ".join(conflicts)
            )
        if unsupported:
            degraded_reasons.append(
                "以下字段不在 Monitor Domain Pack 支持范围：" + ", ".join(unsupported)
            )
        if store_degraded:
            degraded_reasons.append(store_degraded)
        status = "completed" if records and store_status == "stored" else "degraded"
        report = OpenResearchReport(
            provisional_product_id=provisional_product_id,
            target_model=candidate.target_model,
            product_region=candidate.target_region,
            configuration=configuration,
            status=status,
            source_url=candidate.url,
            final_url=extraction.final_url,
            source_title=extraction.title or candidate.title,
            fetched_at=extraction.fetched_at,
            field_assessments=assessments,
            verified_fields=verified,
            unknown_fields=unknown,
            conflict_fields=conflicts,
            unsupported_fields=unsupported,
            tool_trace=trace,
            degraded_reasons=degraded_reasons,
            temporary_evidence_count=len(records),
            promotion_candidate_available=bool(records),
        )
        return OpenResearchOutcome(
            report=report,
            extraction=extraction,
            additional_extractions=additional_extractions,
            evidence=records,
            temporary_store_status=store_status,
            canonical_recovery_attempted=recovery_attempted,
            canonical_recovery_succeeded=recovery_succeeded,
        )
