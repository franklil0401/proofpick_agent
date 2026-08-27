"""Credential-free Web Search interface with an explicit unavailable state."""

from __future__ import annotations

from typing import Any

from smartbuy.tools.base import ToolResult


class WebSearchTool:
    name = "web_search"
    description = "查询动态价格、库存或近期变化；当前未配置凭据，仅返回 unavailable。"

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
                        "query": {"type": "string", "maxLength": 300},
                        "reason": {"type": "string", "maxLength": 200},
                    },
                    "required": ["query", "reason"],
                    "additionalProperties": False,
                },
            },
        }

    async def invoke(self, _arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool=self.name,
            status="unavailable",
            degraded=True,
            retryable=False,
            error_code="WEB_SEARCH_NOT_CONFIGURED",
            summary="Web Search 未配置凭据；继续使用 KB 与只读 SQLite。",
            data={"available": False, "fallback": ["kb_search", "text2sql"]},
        )
