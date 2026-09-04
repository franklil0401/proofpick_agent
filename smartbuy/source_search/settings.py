"""Default-off, secret-safe configuration for V2 Source Search."""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_OFFICIAL_DOMAINS = (
    "dell.com",
    "www.dell.com",
    "asus.com.cn",
    "www.asus.com.cn",
    "asus.com",
    "rog.asus.com",
    "lg.com",
    "www.lg.com",
    "benq.com",
    "www.benq.com",
    "benq.com.cn",
    "sony.com",
    "hp.com",
    "lenovo.com",
    "microsoft.com",
    "bose.com",
    "logitechg.com",
    "logitech.com",
    "steelseries.com",
    "apple.com",
)


class SourceSearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    api_key: str | None = Field(default=None, exclude=True, repr=False)
    endpoint: str = "https://open.bigmodel.cn/api/paas/v4/web_search"
    provider: str = "zhipu"
    provider_version: str = "zhipu-web-search-v1"
    primary_engine: str = "search_pro"
    fallback_engine: str = "search_pro_sogou"
    configured_domains: tuple[str, ...] = DEFAULT_OFFICIAL_DOMAINS
    requested_count: int = Field(default=10, ge=1, le=10)
    raw_result_limit: int = Field(default=50, ge=1, le=50)
    usable_result_limit: int = Field(default=10, ge=1, le=10)
    navigation_result_limit: int = Field(default=10, ge=1, le=10)
    max_search_calls: int = Field(default=4, ge=1, le=4)
    max_tool_invocations_per_task: int = Field(default=2, ge=1, le=4)
    max_retries: int = Field(default=1, ge=0, le=2)
    retry_delay_seconds: float = Field(default=0.25, ge=0, le=2.0)
    timeout_seconds: float = Field(default=10.0, ge=0.1, le=30.0)
    total_timeout_seconds: float = Field(default=20.0, ge=1.0, le=60.0)
    max_cost_cny: float = Field(default=0.20, gt=0, le=1.0)
    max_rps: float = Field(default=5.0, gt=0, le=15.0)
    cache_ttl_seconds: int = Field(default=900, ge=1, le=86_400)
    cache_max_entries: int = Field(default=256, ge=1, le=10_000)

    @classmethod
    def from_environment(cls) -> SourceSearchSettings:
        raw = os.getenv("PROOFPICK_SOURCE_SEARCH_ENABLED", "false").strip().casefold()
        if raw not in {"true", "false"}:
            raise ValueError("PROOFPICK_SOURCE_SEARCH_ENABLED must be true or false")
        enabled = raw == "true"
        key = os.getenv("ZhiPu_api_key", "").strip() if enabled else ""
        return cls(enabled=enabled, api_key=key or None)

    def availability(self) -> dict[str, str]:
        return {
            "PROOFPICK_SOURCE_SEARCH_ENABLED": "enabled" if self.enabled else "disabled",
            "ZhiPu_api_key": "configured" if self.api_key else "missing",
        }
