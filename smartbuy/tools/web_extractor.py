"""Agent-facing, Source-Candidate-gated Open Research extraction tool."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from smartbuy.open_research.service import OpenResearchService
from smartbuy.open_research.settings import OpenResearchSettings
from smartbuy.source_search import SourceCandidate
from smartbuy.tools.base import ToolResult


class WebExtractorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_url: str = Field(min_length=1, max_length=2_048)
    target_model: str = Field(min_length=1, max_length=100)
    target_fields: list[str] = Field(min_length=1, max_length=20)
    region: str = Field(pattern=r"^[A-Z]{2}$")
    allowed_domains: list[str] = Field(min_length=1, max_length=10)
    provisional_product_id: str = Field(min_length=1, max_length=160)
    configuration: str | None = Field(default=None, max_length=160)
    allow_region_discovery: bool = False
    reason: str = Field(min_length=1, max_length=200)


class WebExtractorTool:
    name = "web_extractor"
    description = (
        "仅在 Open Mode 中打开先前 Source Search 返回的官方候选页，提取最小正文片段，"
        "规范化为请求级临时证据并生成 provisional 研究报告。"
    )

    def __init__(
        self,
        settings: OpenResearchSettings,
        service: OpenResearchService | None,
    ) -> None:
        self.settings = settings
        self.service = service

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_url": {"type": "string", "maxLength": 2048},
                        "target_model": {"type": "string", "maxLength": 100},
                        "target_fields": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 20,
                        },
                        "region": {"type": "string", "pattern": "^[A-Z]{2}$"},
                        "allowed_domains": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 10,
                        },
                        "provisional_product_id": {"type": "string", "maxLength": 160},
                        "configuration": {"type": ["string", "null"], "maxLength": 160},
                        "allow_region_discovery": {"type": "boolean"},
                        "reason": {"type": "string", "maxLength": 200},
                    },
                    "required": [
                        "source_url",
                        "target_model",
                        "target_fields",
                        "region",
                        "allowed_domains",
                        "provisional_product_id",
                        "reason",
                    ],
                    "additionalProperties": False,
                },
            },
        }

    async def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        if not self.settings.enabled or self.service is None:
            return ToolResult(
                tool=self.name,
                status="unavailable",
                degraded=True,
                error_code="OPEN_RESEARCH_DISABLED",
                summary="Open Research 未启用；本地 Trusted Mode 路径保持可用。",
                data={"mode": "trusted", "extraction_executed": False},
            )
        internal_candidate = arguments.get("_source_candidate")
        if not isinstance(internal_candidate, dict):
            return ToolResult(
                tool=self.name,
                status="failed",
                error_code="SOURCE_CANDIDATE_REQUIRED",
                summary="没有经过 Source Search 状态门的候选，未抓取网页。",
                data={"mode": "open", "extraction_executed": False},
            )
        public_arguments = {key: value for key, value in arguments.items() if not key.startswith("_")}
        try:
            request = WebExtractorRequest.model_validate(public_arguments)
            candidate = SourceCandidate.model_validate(internal_candidate)
        except ValidationError:
            return ToolResult(
                tool=self.name,
                status="failed",
                error_code="INVALID_WEB_EXTRACTION_REQUEST",
                summary="网页抽取参数未通过结构校验，未发起请求。",
                data={"mode": "open", "extraction_executed": False},
            )
        if (
            request.source_url != candidate.url
            or request.target_model.casefold() != candidate.target_model.casefold()
            or request.region != candidate.target_region
        ):
            return ToolResult(
                tool=self.name,
                status="failed",
                error_code="SOURCE_CANDIDATE_MISMATCH",
                summary="工具参数与已观察的 Source Candidate 不一致，安全门已阻断。",
                data={"mode": "open", "extraction_executed": False},
            )
        outcome = await self.service.research(
            candidate,
            target_fields=request.target_fields,
            allowed_domains=request.allowed_domains,
            provisional_product_id=request.provisional_product_id,
            configuration=request.configuration,
            user_id=arguments.get("_user_id"),
            session_id=arguments.get("_session_id"),
            thread_id=arguments.get("_thread_id"),
            request_id=str(arguments.get("_request_id") or "request"),
            allow_region_discovery=request.allow_region_discovery,
        )
        payload = outcome.model_dump(mode="json")
        if outcome.report.status == "completed":
            return ToolResult(
                tool=self.name,
                status="success",
                summary=(
                    f"Open Research 已生成 {outcome.report.temporary_evidence_count} 条临时字段证据；"
                    "结果不具备 Trusted eligible 资格。"
                ),
                data=payload,
            )
        return ToolResult(
            tool=self.name,
            status="degraded",
            degraded=True,
            error_code=(outcome.extraction.error or outcome.extraction.status.value).upper(),
            summary="网页正文或临时证据不足，Open Research 已明确降级且未生成 Trusted 推荐。",
            data=payload,
        )
