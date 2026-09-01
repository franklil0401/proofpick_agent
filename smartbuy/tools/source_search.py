"""Controlled Source Search tool; discovery metadata never becomes trusted evidence."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from smartbuy.source_search.models import SourceSearchRequest, SourceSearchStatus
from smartbuy.source_search.provider import SourceSearchProvider
from smartbuy.source_search.settings import SourceSearchSettings
from smartbuy.tools.base import ToolResult


class SourceSearchTool:
    name = "source_search"
    description = (
        "在本地证据不足、用户明确要求或型号不在目录中时发现官方来源 URL；"
        "只返回未晋升的 Source Candidate。"
    )

    def __init__(
        self,
        settings: SourceSearchSettings,
        provider: SourceSearchProvider | None,
    ) -> None:
        self.settings = settings
        self.provider = provider

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
                        "query": {"type": "string", "maxLength": 70},
                        "product_category": {"type": "string", "maxLength": 64},
                        "target_model": {"type": "string", "maxLength": 100},
                        "target_fields": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 20,
                        },
                        "region": {"type": "string", "pattern": "^[A-Z]{2}$"},
                        "freshness": {
                            "type": "string",
                            "enum": ["oneDay", "oneWeek", "oneMonth", "oneYear", "noLimit"],
                        },
                        "allowed_domains": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 10,
                        },
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                        "trigger_reason": {
                            "type": "string",
                            "enum": [
                                "explicit_user_request",
                                "out_of_catalog_model",
                                "missing_local_evidence",
                                "dynamic_information",
                            ],
                        },
                    },
                    "required": [
                        "query",
                        "product_category",
                        "target_model",
                        "target_fields",
                        "region",
                        "allowed_domains",
                        "trigger_reason",
                    ],
                    "additionalProperties": False,
                },
            },
        }

    async def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        local_checked = bool(arguments.get("_local_evidence_checked", False))
        local_sufficient = bool(arguments.get("_local_evidence_sufficient", False))
        public_arguments = {
            key: value for key, value in arguments.items() if not key.startswith("_local_")
        }
        if not self.settings.enabled or self.provider is None:
            return ToolResult(
                tool=self.name,
                status="unavailable",
                degraded=True,
                error_code="SOURCE_SEARCH_DISABLED",
                summary="Source Search 未启用或 Provider 未配置；本地可信路径保持可用。",
                data={
                    "status": SourceSearchStatus.DISABLED,
                    "search_executed": False,
                    "usable_result_count": 0,
                },
            )
        try:
            request = SourceSearchRequest.model_validate(public_arguments)
        except ValidationError:
            return ToolResult(
                tool=self.name,
                status="failed",
                error_code="INVALID_SOURCE_SEARCH_REQUEST",
                summary="Source Search 参数未通过结构校验，未发起网络请求。",
                data={"search_executed": False},
            )
        if local_sufficient:
            return ToolResult(
                tool=self.name,
                status="degraded",
                degraded=True,
                error_code="LOCAL_EVIDENCE_SUFFICIENT",
                summary="本地证据已覆盖目标字段，安全门阻止了无效联网。",
                data={"search_executed": False, "usable_result_count": 0},
            )
        if request.trigger_reason.value == "missing_local_evidence" and not local_checked:
            return ToolResult(
                tool=self.name,
                status="failed",
                error_code="LOCAL_EVIDENCE_CHECK_REQUIRED",
                summary="尚未检查本地证据，安全门阻止了提前联网。",
                data={"search_executed": False, "usable_result_count": 0},
            )

        result = await self.provider.search(request)
        payload = result.model_dump(mode="json")
        if result.status == SourceSearchStatus.SUCCESS:
            return ToolResult(
                tool=self.name,
                status="success",
                degraded=result.degraded,
                summary=(
                    f"找到 {result.usable_result_count} 条目标地区官方来源候选"
                    + ("（已使用有界回退）。" if result.degraded else "。")
                ),
                data=payload,
            )
        if result.status in {
            SourceSearchStatus.NO_REGION_MATCHED_SOURCE,
            SourceSearchStatus.NO_OFFICIAL_SOURCE,
        }:
            return ToolResult(
                tool=self.name,
                status="degraded",
                degraded=True,
                error_code=result.status.value.upper(),
                summary="未找到可用于目标地区核验的官方来源，已明确降级。",
                data=payload,
            )
        return ToolResult(
            tool=self.name,
            status="degraded",
            degraded=True,
            error_code="SOURCE_SEARCH_PROVIDER_ERROR",
            summary="Source Search Provider 不可用；继续保留本地可信结果。",
            data=payload,
        )
