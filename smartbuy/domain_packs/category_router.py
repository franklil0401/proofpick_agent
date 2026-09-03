"""Deterministic category routing from registry metadata, never from an LLM."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from smartbuy.domain_packs.loader import DomainPackValidationError
from smartbuy.domain_packs.registry import DomainPackRegistry


DEFAULT_CATEGORY_REGISTRY = Path(__file__).with_name("category_registry.json")


class CategoryRouteStatus(StrEnum):
    RESOLVED = "resolved"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"
    OPEN = "open"


class CategoryRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: CategoryRouteStatus
    domain_id: str | None = None
    matched_domain_ids: list[str] = Field(default_factory=list)
    reason: str
    clarification_question: str | None = None


class CategoryRouter:
    """Resolve an installed domain using a versioned, data-only alias registry."""

    def __init__(
        self,
        registry: DomainPackRegistry,
        metadata_path: Path | str = DEFAULT_CATEGORY_REGISTRY,
    ) -> None:
        self.registry = registry
        try:
            payload = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DomainPackValidationError("category registry is unavailable") from exc
        if payload.get("schema_version") != "proofpick-category-registry-v1":
            raise DomainPackValidationError("category registry version is incompatible")
        installed = set(registry.list())
        domains = payload.get("domains")
        if not isinstance(domains, dict) or not domains:
            raise DomainPackValidationError("category registry has no domains")
        self.aliases: dict[str, tuple[str, ...]] = {}
        for domain_id, settings in domains.items():
            if domain_id not in installed:
                continue
            values = settings.get("aliases") if isinstance(settings, dict) else None
            if not isinstance(values, list) or not values:
                raise DomainPackValidationError("category aliases are invalid")
            normalized = tuple(dict.fromkeys(str(item).strip().casefold() for item in values))
            if any(not item for item in normalized):
                raise DomainPackValidationError("category alias is empty")
            self.aliases[domain_id] = normalized

    @staticmethod
    def _contains(text: str, alias: str) -> bool:
        if re.fullmatch(r"[a-z0-9_-]+", alias):
            return re.search(rf"(?<![a-z0-9_-]){re.escape(alias)}(?![a-z0-9_-])", text) is not None
        return alias in text

    def route(
        self,
        query: str,
        *,
        explicit_domain_id: str | None = None,
        allow_open: bool = False,
    ) -> CategoryRoute:
        if explicit_domain_id is not None:
            try:
                self.registry.load(explicit_domain_id)
            except DomainPackValidationError:
                return CategoryRoute(
                    status=CategoryRouteStatus.OPEN if allow_open else CategoryRouteStatus.UNSUPPORTED,
                    reason="explicit_domain_not_installed",
                )
            return CategoryRoute(
                status=CategoryRouteStatus.RESOLVED,
                domain_id=explicit_domain_id,
                matched_domain_ids=[explicit_domain_id],
                reason="explicit_domain_validated",
            )
        folded = query.casefold()
        matches = sorted(
            domain_id
            for domain_id, aliases in self.aliases.items()
            if any(self._contains(folded, alias) for alias in aliases)
        )
        if len(matches) == 1:
            return CategoryRoute(
                status=CategoryRouteStatus.RESOLVED,
                domain_id=matches[0],
                matched_domain_ids=matches,
                reason="registry_alias_match",
            )
        if len(matches) > 1:
            return CategoryRoute(
                status=CategoryRouteStatus.NEEDS_CLARIFICATION,
                matched_domain_ids=matches,
                reason="mixed_categories",
                clarification_question="请分别说明要查询哪个品类，或拆成两个问题。",
            )
        return CategoryRoute(
            status=CategoryRouteStatus.NEEDS_CLARIFICATION,
            reason="category_not_explicit",
            clarification_question="请确认要查询的商品品类。",
        )
