"""Deterministic, pack-driven separation of intent and requested fact fields."""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from smartbuy.domain_packs import LoadedDomainPack
from smartbuy.identity import ProductScopeType, QueryIntent, ResolvedProductScope


_COMPARISON = (
    "比较", "对比", "对照", "区分", "差异", "不同", "有何不同",
    "是否等同", "是不是同", "混成",
)
_FACT = (
    "多少", "是什么", "哪个", "哪套", "属于", "核验", "核对", "核实", "确认",
    "是否", "能否", "请查", "查询", "查一下", "只查", "事实", "给证据",
    "怎么样", "有什么", "支持哪些", "能力",
)
_FILTER = ("筛选", "筛出", "推荐", "想要", "需要", "只要", "找", "选择", "选 ", "返回对应")
_EXPLICIT_FILTER = ("筛选", "筛出", "推荐", "想要", "只要", "只接受", "仅限", "找", "选择", "选 ", "返回对应")
_CLARIFY = (
    "先确认", "先问", "先澄清", "没指定", "没有指定", "没决定",
    "未决定", "尚未决定", "还没决定", "没有选", "请先问", "不明确",
)

_QUALITATIVE_WITHOUT_THRESHOLD = (
    "别太大", "别太小", "大一点", "小一点", "高一点", "低一点", "久一点",
    "轻一点", "便宜一点", "快一点", "强一点", "好一点", "窄一点",
    "窄一些", "强一些", "好一些", "性能强一点", "性能强一些",
    "通话好一点", "通话好一些", "别太贵", "不能太高", "不要太重",
)


def _has_explicit_filter_signal(text: str) -> bool:
    if any(marker in text for marker in _EXPLICIT_FILTER):
        return True
    return bool(
        re.search(r"(?:^|[，,；;：:\s])(?:要|要求|必须)(?!求证|确认|核验)", text)
        or re.search(r"(?:至少|最低|不低于|不少于|不超过|至多|最多|以内|以下)", text)
    )


def _fold(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _contains_term(text: str, term: str) -> bool:
    folded = _fold(term)
    if not folded:
        return False
    if re.fullmatch(r"[a-z0-9_.+ -]+", folded):
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(folded)}(?![a-z0-9])", text
            )
        )
    return folded in text


class QueryUnderstanding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: QueryIntent
    requested_fields: list[str] = Field(default_factory=list)
    clarification_reason: str | None = None


class QueryUnderstandingEngine:
    def __init__(self, pack: LoadedDomainPack) -> None:
        self.pack = pack

    def requested_fields(self, query: str) -> list[str]:
        folded = _fold(query)
        fields: list[str] = []
        understanding = self.pack.pack.policies.get("understanding", {})
        extra_terms = understanding.get("requested_field_terms", {})
        for field_id, definition in self.pack.fields.items():
            terms = [
                definition.label,
                *definition.aliases,
                *definition.enum_values,
                *definition.value_aliases,
                *extra_terms.get(field_id, []),
            ]
            if any(_contains_term(folded, term) for term in terms if term):
                fields.append(field_id)
        if re.search(r"(?:扩展|升级)到(?:其他|全部|全库|候选)", query):
            fields = [item for item in fields if item != "upgradeability"]
        if re.search(r"(?:其他|全部|全库|候选)\s*配置", query):
            fields = [item for item in fields if item != "configuration_id"]
        # "内存/硬盘能否升级" asks about upgradeability, not their capacity.
        if "upgradeability" in fields and re.search(
            r"(?:内存|硬盘|固态)[^，,。；;？！?]{0,8}(?:升级|扩展)", query
        ):
            fields = [item for item in fields if item not in {"memory_gb", "storage_gb"}]
        bundles = understanding.get("requested_field_bundles", {})
        for field_id in tuple(fields):
            fields.extend(
                item for item in bundles.get(field_id, []) if item in self.pack.fields
            )
        return list(dict.fromkeys(fields))

    def analyze(self, query: str, scope: ResolvedProductScope) -> QueryUnderstanding:
        folded = _fold(query)
        requested = self.requested_fields(query)
        included_exact = {
            item.product_id for item in scope.references
            if item.polarity.value == "include" and item.product_id
        }
        if scope.scope_type == ProductScopeType.OPEN_UNKNOWN_PRODUCT:
            intent = QueryIntent.OPEN_PRODUCT_RESEARCH
        elif scope.resolution_status.value == "needs_clarification":
            intent = QueryIntent.CLARIFICATION_REQUIRED
        elif scope.scope_type == ProductScopeType.EXPLICIT_COMPARISON or any(
            marker in folded for marker in _COMPARISON
        ):
            intent = QueryIntent.EXPLICIT_COMPARISON
        elif any(marker in folded for marker in _CLARIFY):
            intent = QueryIntent.CLARIFICATION_REQUIRED
        elif (
            any(marker in folded for marker in _QUALITATIVE_WITHOUT_THRESHOLD)
            and not re.search(r"\d", folded)
        ):
            intent = QueryIntent.CLARIFICATION_REQUIRED
        elif _has_explicit_filter_signal(folded):
            intent = QueryIntent.RECOMMENDATION_FILTER
        elif included_exact and any(marker in folded for marker in _FACT):
            intent = QueryIntent.EXACT_FACT_VERIFICATION
        elif scope.scope_type == ProductScopeType.PRODUCT_FAMILY and not any(
            marker in folded for marker in _FILTER
        ):
            intent = QueryIntent.FAMILY_OVERVIEW
        elif any(marker in folded for marker in _FILTER) or re.search(
            r"(?:至少|最低|不低于|不超过|至多|最多|必须|以内|以下)", folded
        ):
            intent = QueryIntent.RECOMMENDATION_FILTER
        elif requested and any(marker in folded for marker in _FACT):
            intent = QueryIntent.EXACT_FACT_VERIFICATION
        else:
            intent = QueryIntent.RECOMMENDATION_FILTER
        understanding = self.pack.pack.policies.get("understanding", {})
        if intent == QueryIntent.EXPLICIT_COMPARISON and not requested:
            requested = [
                item for item in understanding.get("default_comparison_fields", [])
                if item in self.pack.fields
            ]
        elif intent == QueryIntent.EXACT_FACT_VERIFICATION and not requested:
            requested = [
                item for item in understanding.get("default_identity_fact_fields", [])
                if item in self.pack.fields
            ]
        if intent in {
            QueryIntent.EXACT_FACT_VERIFICATION,
            QueryIntent.EXPLICIT_COMPARISON,
        } and any(item.identity_kind == "region" for item in scope.references):
            if "region" in self.pack.fields and "region" not in requested:
                requested.append("region")
        reason = None
        if intent == QueryIntent.CLARIFICATION_REQUIRED:
            reason = (
                scope.resolution_reason
                if scope.resolution_status.value == "needs_clarification"
                else "qualitative_threshold_missing"
                if any(marker in folded for marker in _QUALITATIVE_WITHOUT_THRESHOLD)
                else "explicit_clarification_language"
            )
        return QueryUnderstanding(intent=intent, requested_fields=requested, clarification_reason=reason)
