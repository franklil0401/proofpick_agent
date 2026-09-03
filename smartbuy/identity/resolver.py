"""Exact, registry-backed product identity resolution without fuzzy authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .models import (
    ProductMention,
    ProductScopeResolutionStatus,
    ProductScopeType,
    ResolvedProductScope,
)


_COMPARISON_MARKERS = ("比较", "对比", "区分", "是否等同", "是不是同", "不要把", "不能混")
_FILTER_MARKERS = ("筛选", "找", "只要", "只接受", "仅限", "需要", "配置是哪一个", "哪一个", "哪个")
_SELECTOR_MARKERS = ("哪一个", "哪个", "哪款", "配置是", "order code")
_NEGATIVE_REGION_MARKERS = ("不接受", "排除", "不要", "不是", "非")
_NEGATED_IDENTITY_PREFIXES = (
    "不是",
    "不匹配",
    "不应匹配",
    "排除",
    "不要选择",
    "不要推荐",
)
_REGION_ALIASES = {
    "中国大陆": "CN", "中国区": "CN", "中国版": "CN", "国行": "CN",
    "美国版": "US", "美国区": "US", "美版": "US",
    "加拿大版": "CA", "加拿大区": "CA",
    "德国版": "DE", "德国区": "DE",
    "菲律宾版": "PH", "菲律宾区": "PH",
}


def _identity_value(product: dict[str, Any], field: str) -> str | None:
    if field in product:
        value = product.get(field)
    else:
        value = product.get("attributes", {}).get(field)
    return str(value) if value is not None else None


def _token_pattern(value: str) -> re.Pattern[str]:
    escaped = re.escape(value)
    if " " in value:
        escaped = escaped.replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)


def _identity_aliases(value: str) -> set[str]:
    aliases = {value, value.replace("_", "-"), re.sub(r"[-_]", " ", value)}
    expanded = set()
    for alias in aliases:
        expanded.add(re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", alias))
    return {item.strip() for item in aliases | expanded if item.strip()}


def _family_aliases(family_id: str, brand: str, products: Iterable[dict[str, Any]]) -> set[str]:
    output = _identity_aliases(family_id)
    brand_pattern = re.compile(rf"^{re.escape(brand)}(?:[-_\s]+)", re.IGNORECASE)
    output |= {brand_pattern.sub("", item) for item in tuple(output)}
    tokens = re.split(r"[-_\s]+", family_id)
    if tokens and re.search(r"[A-Za-z]", tokens[-1]) and re.search(r"\d", tokens[-1]):
        output |= _identity_aliases(tokens[-1])
    for product in products:
        name = str(product.get("model_name", ""))
        configuration = _identity_value(product, "configuration_id")
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
        if configuration:
            name = re.sub(
                rf"(?:\s+|[-_(]){re.escape(configuration)}(?:\)?\s*)$",
                "",
                name,
                flags=re.IGNORECASE,
            ).strip()
        if name:
            output.add(name)
            output.add(re.sub(rf"^{re.escape(brand)}\s+", "", name, flags=re.IGNORECASE))
    return {item for item in output if len(re.sub(r"\W", "", item)) >= 4}


@dataclass(frozen=True)
class _Match:
    priority: int
    kind: str
    value: str
    quote: str
    start: int
    end: int
    product_ids: tuple[str, ...]


class ProductIdentityResolver:
    """Resolve only exact Product Pack identities; ambiguity always fails closed."""

    def __init__(self, *, domain_id: str, data_version: str, index_version: str | None = None) -> None:
        self.domain_id = domain_id
        self.data_version = data_version
        self.index_version = index_version

    @staticmethod
    def _find(query: str, value: str) -> list[re.Match[str]]:
        return list(_token_pattern(value).finditer(query))

    def _matches(self, query: str, products: dict[str, dict[str, Any]]) -> list[_Match]:
        matches: list[_Match] = []
        by_family: dict[str, list[dict[str, Any]]] = {}
        for product in products.values():
            family = _identity_value(product, "family_id")
            if family:
                by_family.setdefault(family, []).append(product)
        seen: set[tuple[int, int, str, str, tuple[str, ...]]] = set()

        def add(priority: int, kind: str, value: str, aliases: Iterable[str], ids: Iterable[str]) -> None:
            product_ids = tuple(sorted(set(ids)))
            for alias in sorted(set(aliases), key=len, reverse=True):
                for found in self._find(query, alias):
                    key = (found.start(), found.end(), kind, value.casefold(), product_ids)
                    if key in seen:
                        continue
                    seen.add(key)
                    matches.append(_Match(
                        priority, kind, value, found.group(0), found.start(), found.end(), product_ids
                    ))

        for product_id, product in products.items():
            configuration = _identity_value(product, "configuration_id")
            part_number = _identity_value(product, "part_number")
            if configuration:
                add(1, "configuration_id", configuration, {configuration}, {product_id})
            if part_number:
                add(2, "part_number", part_number, {part_number}, {product_id})
            add(3, "product_id", product_id, {product_id}, {product_id})
            model_name = str(product.get("model_name", ""))
            aliases = {model_name, *map(str, product.get("aliases", []))}
            aliases.discard("")
            add(4, "model_or_alias", model_name or product_id, aliases, {product_id})
        for family_id, family_products in by_family.items():
            brand = str(family_products[0].get("brand", ""))
            add(
                5,
                "family_id",
                family_id,
                _family_aliases(family_id, brand, family_products),
                {str(item["product_id"]) for item in family_products},
            )
        return matches

    @staticmethod
    def _deduplicate_mentions(matches: Iterable[_Match]) -> list[_Match]:
        ordered = sorted(matches, key=lambda item: (item.start, item.end, item.priority, item.value))
        output: list[_Match] = []
        for item in ordered:
            if any(
                prior.start == item.start
                and prior.end == item.end
                and prior.product_ids == item.product_ids
                for prior in output
            ):
                continue
            output.append(item)
        return output

    @staticmethod
    def _is_negated_identity(query: str, match: _Match) -> bool:
        """Reject an identity only when a local, explicit negation targets it."""
        prefix = query[max(0, match.start - 12):match.start].rstrip()
        return any(prefix.endswith(marker) for marker in _NEGATED_IDENTITY_PREFIXES)

    @staticmethod
    def _region_filters(query: str, available: set[str]) -> tuple[set[str], set[str]]:
        positive: set[str] = set()
        negative: set[str] = set()
        clauses = re.split(r"[，,；;。]", query)
        for clause in clauses:
            clause_negative = any(marker in clause for marker in _NEGATIVE_REGION_MARKERS)
            for alias, region in _REGION_ALIASES.items():
                if alias in clause and region in available:
                    (negative if clause_negative and "只接受" not in clause else positive).add(region)
            for region in available:
                for found in _token_pattern(region).finditer(clause):
                    prefix = clause[max(0, found.start() - 8):found.start()]
                    is_negative = clause_negative or any(marker in prefix for marker in _NEGATIVE_REGION_MARKERS)
                    (negative if is_negative and "只接受" not in prefix else positive).add(region)
        return positive - negative, negative

    @staticmethod
    def _literal_qualifier_ids(
        query: str,
        candidate_ids: set[str],
        products: dict[str, dict[str, Any]],
    ) -> set[str]:
        """Narrow a family selector only by exact Pack-owned attribute literals."""
        narrowed = set(candidate_ids)
        for field in set().union(*(products[item]["attributes"] for item in candidate_ids)):
            values: dict[str, set[str]] = {}
            for product_id in candidate_ids:
                value = products[product_id]["attributes"].get(field)
                if isinstance(value, str) and len(value) >= 3:
                    values.setdefault(value.casefold(), set()).add(product_id)
            mentioned = set()
            for value, ids in values.items():
                if _token_pattern(value).search(query):
                    mentioned |= ids
            if mentioned and mentioned != candidate_ids:
                narrowed &= mentioned
        return narrowed or candidate_ids

    @staticmethod
    def _looks_like_unknown_identity(query: str, known_attribute_tokens: set[str]) -> str | None:
        context = re.search(
            r"(?:型号|机型|配置号|order\s*code|sku|part\s*number)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9_-]{3,})",
            query,
            flags=re.IGNORECASE,
        )
        if not context:
            return None
        token = context.group(1)
        return None if token.casefold() in known_attribute_tokens else token

    @staticmethod
    def _catalog_literal_matches(
        query: str,
        products: dict[str, dict[str, Any]],
        known_attribute_tokens: set[str],
    ) -> list[ProductMention]:
        """Find exact Pack-owned product-line words without treating them as a SKU."""
        token_products: dict[str, set[str]] = {}
        token_spelling: dict[str, str] = {}
        for product_id, product in products.items():
            brand = str(product.get("brand", "")).casefold()
            for token in re.findall(r"[A-Za-z][A-Za-z0-9]{3,}", str(product.get("model_name", ""))):
                folded = token.casefold()
                if folded == brand or folded in known_attribute_tokens:
                    continue
                token_products.setdefault(folded, set()).add(product_id)
                token_spelling.setdefault(folded, token)
        mentions = []
        for token, product_ids in token_products.items():
            if len(product_ids) < 2:
                continue
            found = _token_pattern(token).search(query)
            if found:
                mentions.append(ProductMention(
                    quote=found.group(0),
                    span_start=found.start(),
                    span_end=found.end(),
                    identity_kind="catalog_literal",
                    canonical_value=token_spelling[token],
                    product_ids=sorted(product_ids),
                ))
        return mentions

    def resolve(
        self,
        query: str,
        products: dict[str, dict[str, Any]],
    ) -> ResolvedProductScope:
        if not products:
            raise ValueError("product identity resolution requires a non-empty catalog")
        if any(product.get("domain_id") != self.domain_id for product in products.values()):
            raise ValueError("product catalog crosses domain boundary")
        matches = [
            item for item in self._matches(query, products)
            if not self._is_negated_identity(query, item)
        ]
        explicit_comparison = any(marker.casefold() in query.casefold() for marker in _COMPARISON_MARKERS)
        available_regions = {str(product["region"]) for product in products.values()}
        positive_regions, negative_regions = self._region_filters(query, available_regions)
        known_tokens = {
            str(value).casefold()
            for product in products.values()
            for value in product["attributes"].values()
            if isinstance(value, str)
        }

        if matches:
            best_priority = min(item.priority for item in matches)
            best = self._deduplicate_mentions(item for item in matches if item.priority == best_priority)
            product_ids = {product_id for item in best for product_id in item.product_ids}
            family_ids = {
                value
                for product_id in product_ids
                if (value := _identity_value(products[product_id], "family_id"))
            }
            kind = best[0].kind
            if positive_regions and kind == "family_id":
                product_ids = {
                    product_id for product_id in product_ids
                    if str(products[product_id]["region"]) in positive_regions
                }
            if negative_regions and kind == "family_id":
                product_ids = {
                    product_id for product_id in product_ids
                    if str(products[product_id]["region"]) not in negative_regions
                }
            selector = any(marker.casefold() in query.casefold() for marker in _SELECTOR_MARKERS)
            if kind == "family_id" and selector:
                product_ids = self._literal_qualifier_ids(query, product_ids, products)
            if kind in {"configuration_id", "part_number", "product_id", "model_or_alias"}:
                scope_type = (
                    ProductScopeType.EXPLICIT_COMPARISON
                    if len(product_ids) > 1 and explicit_comparison
                    else ProductScopeType.EXACT_CONFIGURATION
                    if len(product_ids) == 1
                    else ProductScopeType.AMBIGUOUS_PRODUCT_SCOPE
                )
            elif explicit_comparison:
                scope_type = ProductScopeType.EXPLICIT_COMPARISON
            elif selector and len(product_ids) == 1:
                scope_type = ProductScopeType.EXACT_CONFIGURATION
            elif selector:
                scope_type = ProductScopeType.AMBIGUOUS_PRODUCT_SCOPE
            elif any(marker.casefold() in query.casefold() for marker in _FILTER_MARKERS):
                scope_type = ProductScopeType.PRODUCT_FAMILY
            else:
                scope_type = ProductScopeType.AMBIGUOUS_PRODUCT_SCOPE
            clarification = scope_type == ProductScopeType.AMBIGUOUS_PRODUCT_SCOPE
            status = (
                ProductScopeResolutionStatus.NEEDS_CLARIFICATION
                if clarification else ProductScopeResolutionStatus.RESOLVED
            )
            reason = (
                "multiple_registry_identities_require_clarification"
                if clarification else "exact_registry_identity"
                if scope_type == ProductScopeType.EXACT_CONFIGURATION else "explicit_registry_scope"
            )
            mentions = [
                ProductMention(
                    quote=item.quote,
                    span_start=item.start,
                    span_end=item.end,
                    identity_kind=item.kind,
                    canonical_value=item.value,
                    product_ids=list(item.product_ids),
                )
                for item in best
            ]
        else:
            unknown = self._looks_like_unknown_identity(query, known_tokens)
            if unknown:
                found = _token_pattern(unknown).search(query)
                assert found is not None
                mentions = [ProductMention(
                    quote=found.group(0), span_start=found.start(), span_end=found.end(),
                    identity_kind="unknown", canonical_value=unknown, product_ids=[],
                )]
                product_ids = set()
                family_ids = set()
                scope_type = ProductScopeType.OPEN_UNKNOWN_PRODUCT
                status = ProductScopeResolutionStatus.OPEN_REQUIRED
                clarification = False
                reason = "product_identity_not_present_in_governed_catalog"
            else:
                mentions = self._catalog_literal_matches(query, products, known_tokens)
                product_ids = (
                    set.intersection(*(set(item.product_ids) for item in mentions))
                    if mentions else set(products)
                )
                if positive_regions:
                    product_ids = {
                        product_id for product_id in product_ids
                        if str(products[product_id]["region"]) in positive_regions
                    }
                product_ids = {
                    product_id for product_id in product_ids
                    if str(products[product_id]["region"]) not in negative_regions
                }
                family_ids = {
                    value
                    for product_id in product_ids
                    if (value := _identity_value(products[product_id], "family_id"))
                }
                scope_type = ProductScopeType.CATALOG_FILTER
                status = ProductScopeResolutionStatus.RESOLVED
                clarification = False
                reason = "no_product_mention_catalog_filter"
        configuration_ids = sorted({
            value
            for product_id in product_ids
            if (value := _identity_value(products[product_id], "configuration_id"))
        })
        regions = sorted({str(products[product_id]["region"]) for product_id in product_ids})
        return ResolvedProductScope(
            domain_id=self.domain_id,
            scope_type=scope_type,
            mentioned_quotes=list(dict.fromkeys(item.quote for item in mentions)),
            mentions=mentions,
            family_ids=sorted(family_ids),
            product_ids=sorted(product_ids),
            configuration_ids=configuration_ids,
            regions=regions,
            explicit_comparison=explicit_comparison,
            clarification_required=clarification,
            resolution_status=status,
            resolution_reason=reason,
            data_version=self.data_version,
            index_version=self.index_version,
        )
