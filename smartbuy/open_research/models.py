"""Strict contracts for governed web extraction and request-scoped open evidence."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


OPEN_RESEARCH_SCHEMA_VERSION = "proofpick-open-research-v1"
EXTRACTOR_VERSION = "proofpick-static-html-extractor-v1"
OPEN_EVIDENCE_SCHEMA_VERSION = "proofpick-open-evidence-v1"
NORMALIZATION_VERSION = "proofpick-open-normalizer-v1"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResearchMode(StrEnum):
    TRUSTED = "trusted"
    OPEN = "open"


class ExtractionStatus(StrEnum):
    SUCCESS = "success"
    UNSAFE_URL = "unsafe_url"
    INVALID_SOURCE_CANDIDATE = "invalid_source_candidate"
    HTTP_ERROR = "http_error"
    NON_HTML = "non_html"
    CONTENT_TOO_LARGE = "content_too_large"
    TIMEOUT = "timeout"
    REDIRECT_LIMIT = "redirect_limit"
    DYNAMIC_RENDER_REQUIRED = "dynamic_render_required"
    EXTRACTION_INCOMPLETE = "extraction_incomplete"


class OpenEvidenceStatus(StrEnum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class AlternateLink(FrozenModel):
    url: str = Field(max_length=2_048)
    hreflang: str | None = Field(default=None, max_length=32)


class ExtractedSnippet(FrozenModel):
    kind: Literal["json_ld", "specification", "visible_text"]
    text: str = Field(min_length=1, max_length=1_000)
    locator: str = Field(min_length=1, max_length=300)


class WebExtractionResult(FrozenModel):
    requested_url: str = Field(max_length=2_048)
    final_url: str | None = Field(default=None, max_length=2_048)
    redirect_chain: list[str] = Field(default_factory=list, max_length=3)
    title: str | None = Field(default=None, max_length=500)
    canonical_url: str | None = Field(default=None, max_length=2_048)
    alternate_links: list[AlternateLink] = Field(default_factory=list, max_length=30)
    detected_region: str = "unknown"
    detected_language: str | None = Field(default=None, max_length=32)
    fetched_at: str
    http_status: int | None = None
    content_type: str | None = Field(default=None, max_length=200)
    content_length: int | None = Field(default=None, ge=0)
    content_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    extractor_version: Literal[EXTRACTOR_VERSION] = EXTRACTOR_VERSION
    snippets: list[ExtractedSnippet] = Field(default_factory=list, max_length=100)
    status: ExtractionStatus
    degraded: bool = False
    error: str | None = Field(default=None, max_length=160)


class OpenEvidenceRecord(FrozenModel):
    schema_version: Literal[OPEN_EVIDENCE_SCHEMA_VERSION] = OPEN_EVIDENCE_SCHEMA_VERSION
    evidence_id: str = Field(pattern=r"^open-[a-f0-9]{24}$")
    user_scope: str = Field(min_length=1, max_length=128)
    session_scope: str = Field(min_length=1, max_length=128)
    thread_scope: str = Field(min_length=1, max_length=128)
    request_scope: str = Field(min_length=1, max_length=128)
    product_id: str | None = Field(default=None, max_length=160)
    provisional_product_id: str = Field(min_length=1, max_length=160)
    field_name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    raw_value: Any
    normalized_value: Any = None
    unit: str | None = Field(default=None, max_length=32)
    source_url: str = Field(max_length=2_048)
    final_url: str = Field(max_length=2_048)
    source_title: str = Field(min_length=1, max_length=500)
    source_region: str = Field(min_length=2, max_length=16)
    product_region: str = Field(min_length=2, max_length=16)
    configuration: str | None = Field(default=None, max_length=160)
    exact_snippet: str = Field(min_length=1, max_length=1_000)
    snippet_locator: str = Field(min_length=1, max_length=300)
    fetched_at: str
    observed_at: str
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    extractor_version: Literal[EXTRACTOR_VERSION] = EXTRACTOR_VERSION
    normalization_version: Literal[NORMALIZATION_VERSION] = NORMALIZATION_VERSION
    evidence_scope: Literal["open"] = "open"
    expires_at: str
    confidence: Literal["high", "medium", "low"]
    status: OpenEvidenceStatus = OpenEvidenceStatus.MATCHED
    usable_for_trusted_checker: Literal[False] = False
    promotion_status: Literal["not_reviewed"] = "not_reviewed"

    def to_trusted_checker_input(self) -> None:
        raise ValueError("open evidence cannot enter the Trusted Constraint Checker")


class ScopedEvidenceValue(FrozenModel):
    evidence_id: str
    field_name: str
    normalized_value: Any = None
    source_url: str
    source_region: str
    product_region: str
    observed_at: str
    exact_snippet: str
    evidence_scope: Literal["governed", "open"]


class OpenFieldAssessment(FrozenModel):
    field_name: str
    status: OpenEvidenceStatus
    values: list[Any] = Field(default_factory=list)
    reason: str
    evidence: list[ScopedEvidenceValue] = Field(default_factory=list)


class TemporaryEvidenceEnvelope(FrozenModel):
    schema_version: Literal[OPEN_EVIDENCE_SCHEMA_VERSION] = OPEN_EVIDENCE_SCHEMA_VERSION
    user_scope: str
    session_scope: str
    thread_scope: str
    request_scope: str
    created_at: str
    expires_at: str
    records: list[OpenEvidenceRecord]


class TemporaryStoreReadResult(FrozenModel):
    records: list[OpenEvidenceRecord] = Field(default_factory=list)
    status: Literal["ok", "missing", "expired", "corrupt", "disabled"]
    degraded: bool = False
    error: str | None = None


class OpenResearchReport(FrozenModel):
    schema_version: Literal[OPEN_RESEARCH_SCHEMA_VERSION] = OPEN_RESEARCH_SCHEMA_VERSION
    mode: Literal[ResearchMode.OPEN] = ResearchMode.OPEN
    provisional_product_id: str
    target_model: str
    product_region: str
    configuration: str | None = None
    status: Literal["completed", "degraded", "failed"]
    source_url: str | None = None
    final_url: str | None = None
    source_title: str | None = None
    fetched_at: str | None = None
    field_assessments: list[OpenFieldAssessment] = Field(default_factory=list)
    verified_fields: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    conflict_fields: list[str] = Field(default_factory=list)
    unsupported_fields: list[str] = Field(default_factory=list)
    tool_trace: list[str] = Field(default_factory=list)
    degraded_reasons: list[str] = Field(default_factory=list)
    temporary_evidence_count: int = Field(default=0, ge=0)
    trusted_eligible: Literal[False] = False
    promotion_candidate_available: bool = False
    declaration: str = (
        "开放研究结果仅使用请求级临时网页证据，不构成 Trusted Mode 的正式推荐。"
    )

    @model_validator(mode="after")
    def enforce_open_boundary(self) -> OpenResearchReport:
        if self.trusted_eligible:
            raise ValueError("Open Mode can never create a Trusted eligible product")
        if set(self.verified_fields) & (set(self.unknown_fields) | set(self.conflict_fields)):
            raise ValueError("unknown/conflict fields cannot also be verified")
        return self

    def to_markdown(self) -> str:
        lines = [
            "## Open Research（开放研究）",
            "",
            f"- 商品：`{self.target_model}`（`{self.provisional_product_id}`）",
            f"- 目标地区：`{self.product_region}`",
            f"- 状态：**{self.status}**",
            "- Trusted eligible：`false`",
        ]
        if self.source_url:
            lines.append(f"- 官方来源：[{self.source_title or self.target_model}]({self.final_url or self.source_url})")
        if self.fetched_at:
            lines.append(f"- 抓取时间：`{self.fetched_at}`")
        lines.extend(["", "### 字段核验", ""])
        if not self.field_assessments:
            lines.append("- 未获得可形成字段证据的正文片段。")
        for item in self.field_assessments:
            values = ", ".join(str(value) for value in item.values) or "未知"
            lines.append(f"- `{item.field_name}`：**{item.status.value}**；值：`{values}`；{item.reason}")
            for evidence in item.evidence:
                lines.append(
                    f"  - [{evidence.evidence_id}]({evidence.source_url}) / "
                    f"{evidence.source_region} / {evidence.observed_at} / scope={evidence.evidence_scope}"
                )
        if self.degraded_reasons:
            lines.extend(["", "### 降级与待确认", ""])
            lines.extend(f"- {item}" for item in self.degraded_reasons)
        lines.extend(["", f"> {self.declaration}"])
        return "\n".join(lines)


class OpenResearchOutcome(FrozenModel):
    report: OpenResearchReport
    extraction: WebExtractionResult
    evidence: list[OpenEvidenceRecord] = Field(default_factory=list)
    temporary_store_status: Literal["stored", "empty", "disabled", "failed"]
    canonical_recovery_attempted: bool = False
    canonical_recovery_succeeded: bool = False
