"""Exact registry-backed product references and deterministic set operations."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

from .models import (
    ProductMention,
    ProductReference,
    ProductScopeResolutionStatus,
    ProductScopeType,
    QueryIntent,
    ReferencePolarity,
    ReferenceResolutionStatus,
    ResolvedProductScope,
)


_COMPARISON_MARKERS = ("比较", "对比", "对照", "区分", "是否等同", "是不是同", "混成")
_FILTER_MARKERS = ("筛选", "筛出", "找", "只要", "只接受", "仅限", "需要", "选择", "选 ", "返回对应")
_CLARIFICATION_MARKERS = (
    "先确认", "先问", "先澄清", "没指定", "没有指定", "没决定",
    "未决定", "尚未决定", "还没决定", "没有选", "请先问", "先别替",
)
_DIRECT_EXCLUDE = (
    "不要", "排除", "剔除", "不接受", "别加入", "不是", "除了", "别把",
    "不应匹配", "不匹配",
)
_TRAILING_EXCLUDE = (
    "不参与", "不能算进", "别加入", "不能拿来", "不能据此",
    "不能替代", "不要包含", "不要混进", "别混进", "参数算进来", "资料算进来",
    "必须隔离", "需要隔离", "不属于比较对象",
)
_REGION_ALIASES = {
    "中国大陆": "CN", "中国区": "CN", "中国版": "CN", "国行": "CN", "中国": "CN",
    "美国版": "US", "美国区": "US", "美版": "US", "美国": "US",
    "加拿大版": "CA", "加拿大区": "CA", "加版": "CA", "加拿大": "CA",
    "德国版": "DE", "德国区": "DE", "菲律宾版": "PH", "菲律宾区": "PH",
    "全球版": "GLOBAL", "以色列版": "IL",
}


def _identity_value(product: dict[str, Any], field: str) -> str | None:
    value = product.get(field, product.get("attributes", {}).get(field))
    return str(value) if value is not None else None


def _fold_with_map(value: str) -> tuple[str, list[int]]:
    output: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(value):
        for normalized in unicodedata.normalize("NFKC", char).casefold():
            if normalized.isspace() or normalized in {"-", "_"}:
                continue
            output.append(normalized)
            positions.append(index)
    return "".join(output), positions


def _fold(value: str) -> str:
    return _fold_with_map(value)[0]


def _exact_occurrences(query: str, value: str) -> list[tuple[int, int, str]]:
    normalized_query, index_map = _fold_with_map(query)
    needle = _fold(value)
    if not needle:
        return []
    output: list[tuple[int, int, str]] = []
    position = 0
    while True:
        position = normalized_query.find(needle, position)
        if position < 0:
            break
        end_position = position + len(needle)
        start = index_map[position]
        end = index_map[end_position - 1] + 1
        before = query[start - 1].casefold() if start else ""
        after = query[end].casefold() if end < len(query) else ""
        if not re.match(r"[a-z0-9]", before) and not re.match(r"[a-z0-9]", after):
            output.append((start, end, query[start:end]))
        position += 1
    return output


def _identity_aliases(value: str) -> set[str]:
    aliases = {value, value.replace("_", "-"), re.sub(r"[-_]", " ", value)}
    return {item.strip() for item in aliases if item.strip()}


def _family_aliases(
    family_id: str,
    brand: str,
    products: Iterable[dict[str, Any]],
) -> set[str]:
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
    return {item for item in output if len(_fold(item)) >= 4}


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
    """Resolve exact Pack identities; LLM output never grants registry authority."""

    def __init__(self, *, domain_id: str, data_version: str, index_version: str | None = None) -> None:
        self.domain_id = domain_id
        self.data_version = data_version
        self.index_version = index_version

    def _matches(self, query: str, products: dict[str, dict[str, Any]]) -> list[_Match]:
        matches: list[_Match] = []
        by_family: dict[str, list[dict[str, Any]]] = {}
        for product in products.values():
            family = _identity_value(product, "family_id")
            if family:
                by_family.setdefault(family, []).append(product)
        seen: set[tuple[int, int, str, tuple[str, ...]]] = set()

        def add(priority: int, kind: str, value: str, aliases: Iterable[str], ids: Iterable[str]) -> None:
            product_ids = tuple(sorted(set(ids)))
            for alias in sorted(set(aliases), key=lambda item: len(_fold(item)), reverse=True):
                for start, end, quote in _exact_occurrences(query, alias):
                    key = (start, end, kind, product_ids)
                    if key in seen:
                        continue
                    seen.add(key)
                    matches.append(_Match(priority, kind, value, quote, start, end, product_ids))

        for product_id, product in products.items():
            configuration = _identity_value(product, "configuration_id")
            part_number = _identity_value(product, "part_number")
            if configuration:
                add(1, "configuration_id", configuration, _identity_aliases(configuration), {product_id})
            if part_number:
                add(2, "part_number", part_number, _identity_aliases(part_number), {product_id})
            add(3, "product_id", product_id, _identity_aliases(product_id), {product_id})
            model_name = str(product.get("model_name", ""))
            aliases = {model_name, *map(str, product.get("aliases", []))} - {""}
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
        selected = self._select_non_overlapping(matches)
        exact = [item for item in selected if item.priority <= 4]
        if exact:
            best_by_products: dict[tuple[str, ...], int] = {}
            for item in exact:
                best_by_products[item.product_ids] = min(
                    item.priority, best_by_products.get(item.product_ids, item.priority)
                )
            selected = [
                item for item in exact
                if item.priority == best_by_products[item.product_ids]
            ]
        return selected

    @staticmethod
    def _select_non_overlapping(matches: list[_Match]) -> list[_Match]:
        ordered = sorted(
            matches,
            key=lambda item: (item.start, -(item.end - item.start), item.priority, item.value),
        )
        output: list[_Match] = []
        for item in ordered:
            duplicate = any(
                prior.start == item.start
                and prior.end == item.end
                and prior.product_ids == item.product_ids
                for prior in output
            )
            if duplicate:
                continue
            overlap = [prior for prior in output if item.start < prior.end and prior.start < item.end]
            if overlap:
                if all(
                    item.priority < prior.priority
                    or (item.priority == prior.priority and item.end - item.start > prior.end - prior.start)
                    for prior in overlap
                ):
                    output = [prior for prior in output if prior not in overlap]
                else:
                    continue
            output.append(item)
        return sorted(output, key=lambda item: (item.start, item.end))

    @staticmethod
    def _clause(query: str, start: int, end: int) -> tuple[str, str]:
        separators = ("，", ",", "；", ";", "。", "：", ":", "？", "?", "！", "!")
        left = max(query.rfind(mark, 0, start) for mark in separators) + 1
        right_candidates = [query.find(mark, end) for mark in separators]
        right_candidates = [item for item in right_candidates if item >= 0]
        right = min(right_candidates) if right_candidates else len(query)
        return query[left:start], query[end:right]

    @classmethod
    def _polarity(cls, query: str, match: _Match) -> ReferencePolarity:
        prefix, suffix = cls._clause(query, match.start, match.end)
        clause = prefix + match.quote + suffix
        sentence_separators = ("；", ";", "。", "？", "?", "！", "!")
        sentence_left = max(query.rfind(mark, 0, match.start) for mark in sentence_separators) + 1
        sentence_right_candidates = [query.find(mark, match.end) for mark in sentence_separators]
        sentence_right_candidates = [item for item in sentence_right_candidates if item >= 0]
        sentence_right = min(sentence_right_candidates) if sentence_right_candidates else len(query)
        sentence_prefix = query[sentence_left:match.start]
        sentence_suffix = query[match.end:sentence_right]
        conditional_context = sentence_prefix + match.quote + sentence_suffix
        if (
            re.search(r"(?:若|如果|即使|即便|就算)", conditional_context)
            and re.search(r"(?:不能|不得|不应|不可以)", sentence_suffix)
        ):
            return ReferencePolarity.EXCLUDE
        if "混成" in clause and ("不要把" in prefix or "别把" in prefix):
            return ReferencePolarity.INCLUDE
        transfer = re.search(r"(?:事实|参数|证据).{0,4}(?:写到|套到|用于)", clause)
        if transfer:
            mention_offset = len(prefix)
            return (
                ReferencePolarity.INCLUDE
                if mention_offset < transfer.start()
                else ReferencePolarity.EXCLUDE
            )
        if match.kind in {"family_id", "catalog_literal"} and prefix.rstrip().endswith("相似"):
            return ReferencePolarity.INCLUDE
        if any(prefix.rstrip().endswith(marker) for marker in _DIRECT_EXCLUDE):
            return ReferencePolarity.EXCLUDE
        if any(marker in prefix for marker in ("不要", "排除", "剔除", "不接受", "别加入", "除了", "别把")):
            return ReferencePolarity.EXCLUDE
        if any(marker in suffix[:36] for marker in _TRAILING_EXCLUDE):
            return ReferencePolarity.EXCLUDE
        if re.match(r"\s*(?:明确)?排除(?:\s|$)", suffix):
            return ReferencePolarity.EXCLUDE
        return ReferencePolarity.INCLUDE

    @classmethod
    def _region_references(
        cls,
        query: str,
        products: dict[str, dict[str, Any]],
    ) -> list[ProductReference]:
        available = {str(product["region"]) for product in products.values()}
        references: list[ProductReference] = []
        seen: set[tuple[int, int, str]] = set()

        def add(region: str, start: int, end: int, quote: str) -> None:
            if (start, end, region) in seen:
                return
            seen.add((start, end, region))
            match = _Match(0, "region", region, quote, start, end, ())
            ids = sorted(
                product_id for product_id, product in products.items()
                if str(product["region"]) == region
            )
            references.append(ProductReference(
                quote=quote,
                span_start=start,
                span_end=end,
                polarity=cls._polarity(query, match),
                identity_kind="region",
                region=region,
                matched_product_ids=ids,
            ))

        for alias, region in _REGION_ALIASES.items():
            if region not in available:
                continue
            for start, end, quote in _exact_occurrences(query, alias):
                add(region, start, end, quote)
        for region in available:
            for start, end, quote in _exact_occurrences(query, region):
                add(region, start, end, quote)
        return sorted(references, key=lambda item: (item.span_start, item.span_end))

    @staticmethod
    def _unknown_reference(query: str, known_tokens: set[str]) -> tuple[str, int, int] | None:
        found = re.search(
            r"(?:型号|机型|配置号|order\s*code|sku|part\s*number)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9_-]{3,})",
            query,
            flags=re.IGNORECASE,
        )
        if found is None or _fold(found.group(1)) in known_tokens:
            return None
        return found.group(1), found.start(1), found.end(1)

    @staticmethod
    def _catalog_literal_matches(
        query: str,
        products: dict[str, dict[str, Any]],
    ) -> list[_Match]:
        token_products: dict[str, set[str]] = {}
        spelling: dict[str, str] = {}
        for product_id, product in products.items():
            brand = _fold(str(product.get("brand", "")))
            for token in re.findall(r"[A-Za-z][A-Za-z0-9]{3,}", str(product.get("model_name", ""))):
                folded = _fold(token)
                if folded == brand:
                    continue
                token_products.setdefault(folded, set()).add(product_id)
                spelling.setdefault(folded, token)
        output = []
        for token, product_ids in token_products.items():
            if len(product_ids) < 2:
                continue
            for start, end, quote in _exact_occurrences(query, spelling[token]):
                output.append(_Match(
                    6, "catalog_literal", spelling[token], quote,
                    start, end, tuple(sorted(product_ids)),
                ))
        return output

    @staticmethod
    def _literal_qualifier_ids(
        query: str,
        candidate_ids: set[str],
        products: dict[str, dict[str, Any]],
    ) -> set[str]:
        narrowed = set(candidate_ids)
        for field in set().union(*(products[item]["attributes"] for item in candidate_ids)):
            values: dict[str, set[str]] = {}
            for product_id in candidate_ids:
                value = products[product_id]["attributes"].get(field)
                if isinstance(value, str) and len(value) >= 3:
                    values.setdefault(value, set()).add(product_id)
            mentioned = set()
            for value, ids in values.items():
                if _exact_occurrences(query, value):
                    mentioned |= ids
            if mentioned and mentioned != candidate_ids:
                narrowed &= mentioned
        return narrowed

    @staticmethod
    def _to_reference(
        match: _Match,
        polarity: ReferencePolarity,
        products: dict[str, dict[str, Any]],
    ) -> ProductReference:
        product_id = match.product_ids[0] if len(match.product_ids) == 1 else None
        product = products.get(product_id or "", {})
        return ProductReference(
            quote=match.quote,
            span_start=match.start,
            span_end=match.end,
            polarity=polarity,
            identity_kind=match.kind,
            family_id=(
                match.value if match.kind == "family_id"
                else _identity_value(product, "family_id")
            ),
            product_id=product_id,
            configuration_id=_identity_value(product, "configuration_id"),
            part_number=_identity_value(product, "part_number"),
            region=str(product["region"]) if product else None,
            matched_product_ids=list(match.product_ids),
        )

    def resolve(self, query: str, products: dict[str, dict[str, Any]]) -> ResolvedProductScope:
        if not products:
            raise ValueError("product identity resolution requires a non-empty catalog")
        if any(product.get("domain_id") != self.domain_id for product in products.values()):
            raise ValueError("product catalog crosses domain boundary")
        matches = [
            item for item in self._matches(query, products)
            if not re.search(
                r"(?:不能|不得|不应)(?:据此)?(?:说|认定|说明)\s*$",
                query[max(0, item.start - 16):item.start],
            )
        ]
        if not matches:
            matches = self._catalog_literal_matches(query, products)
        references = [self._to_reference(item, self._polarity(query, item), products) for item in matches]
        region_references = [
            item for item in self._region_references(query, products)
            if not any(
                match.start <= item.span_start and item.span_end <= match.end
                for match in matches
            )
        ]
        references.extend(region_references)
        allowed_regions = {
            item.region for item in region_references
            if item.polarity == ReferencePolarity.INCLUDE and item.region
        }
        excluded_regions = {
            item.region for item in region_references
            if item.polarity == ReferencePolarity.EXCLUDE and item.region
        }
        allowed_regions -= excluded_regions
        included = [item for item in references if item.polarity == ReferencePolarity.INCLUDE]
        excluded = [item for item in references if item.polarity == ReferencePolarity.EXCLUDE]
        include_products = {
            product_id for item in included if item.identity_kind not in {"family_id", "region"}
            for product_id in item.matched_product_ids
        }
        include_families = {item.family_id for item in included if item.identity_kind == "family_id" and item.family_id}
        exclude_products = {
            product_id for item in excluded
            if item.identity_kind not in {"family_id", "region"}
            for product_id in item.matched_product_ids
        }
        exclude_families = {item.family_id for item in excluded if item.identity_kind == "family_id" and item.family_id}
        exclude_configurations = {item.configuration_id for item in excluded if item.configuration_id}
        if include_products:
            candidates = set(include_products)
        elif include_families:
            candidates = {
                product_id for product_id, product in products.items()
                if _identity_value(product, "family_id") in include_families
            }
        else:
            candidates = set(products)
        if allowed_regions:
            candidates &= {
                product_id for product_id, product in products.items()
                if str(product["region"]) in allowed_regions
            }
        candidates -= exclude_products
        candidates = {
            product_id for product_id in candidates
            if _identity_value(products[product_id], "family_id") not in exclude_families
            and _identity_value(products[product_id], "configuration_id") not in exclude_configurations
            and str(products[product_id]["region"]) not in excluded_regions
        }
        if include_families and any(
            marker.casefold() in query.casefold()
            for marker in (*_FILTER_MARKERS, "哪一个", "哪个", "哪套")
        ):
            qualified = self._literal_qualifier_ids(query, candidates, products)
            if qualified:
                candidates = qualified
        explicit_comparison = any(marker in query.casefold() for marker in _COMPARISON_MARKERS)
        known_tokens = {
            _fold(str(value))
            for product in products.values()
            for value in (
                product["product_id"],
                *product.get("aliases", []),
                *product.get("attributes", {}).values(),
            )
            if isinstance(value, str)
        }
        unknown = self._unknown_reference(query, known_tokens)
        unresolved: list[ProductReference] = []
        if unknown and not included:
            token, start, end = unknown
            unresolved = [ProductReference(
                quote=query[start:end], span_start=start, span_end=end,
                polarity=ReferencePolarity.INCLUDE, identity_kind="unknown",
                matched_product_ids=[], resolution_status=ReferenceResolutionStatus.UNRESOLVED,
            )]
            candidates = set()
            scope_type = ProductScopeType.OPEN_UNKNOWN_PRODUCT
            status = ProductScopeResolutionStatus.OPEN_REQUIRED
            clarification = False
            reason = "product_identity_not_present_in_governed_catalog"
            query_intent = QueryIntent.OPEN_PRODUCT_RESEARCH
        elif not candidates:
            scope_type = ProductScopeType.CATALOG_FILTER
            status = ProductScopeResolutionStatus.NO_MATCH
            clarification = False
            reason = "candidate_set_empty_after_identity_exclusions"
            query_intent = QueryIntent.RECOMMENDATION_FILTER
        elif explicit_comparison and len(candidates) >= 2 and (include_products or include_families):
            scope_type = ProductScopeType.EXPLICIT_COMPARISON
            status = ProductScopeResolutionStatus.RESOLVED
            clarification = False
            reason = "explicit_registry_comparison"
            query_intent = QueryIntent.EXPLICIT_COMPARISON
        elif include_products and len(candidates) == 1:
            scope_type = ProductScopeType.EXACT_CONFIGURATION
            status = ProductScopeResolutionStatus.RESOLVED
            clarification = False
            reason = "exact_registry_identity"
            query_intent = QueryIntent.EXACT_FACT_VERIFICATION
        elif include_families:
            if len(candidates) == 1:
                scope_type = ProductScopeType.EXACT_CONFIGURATION
                status = ProductScopeResolutionStatus.RESOLVED
                clarification = False
                reason = "family_with_unique_catalog_selector"
                query_intent = QueryIntent.EXACT_FACT_VERIFICATION
                include_families = set(include_families)
            else:
                clarification = any(marker in query for marker in _CLARIFICATION_MARKERS) or (
                    not any(marker.casefold() in query.casefold() for marker in _FILTER_MARKERS)
                )
                explicit_deferred_choice = any(
                    marker in query
                    for marker in (
                        "没指定", "没有指定", "没决定", "未决定", "尚未决定",
                        "还没决定", "没有选", "先确认", "先澄清", "先别替",
                    )
                )
                scope_type = (
                    ProductScopeType.PRODUCT_FAMILY
                    if not clarification or explicit_deferred_choice
                    else ProductScopeType.AMBIGUOUS_PRODUCT_SCOPE
                )
                status = (
                    ProductScopeResolutionStatus.NEEDS_CLARIFICATION
                    if clarification else ProductScopeResolutionStatus.RESOLVED
                )
                reason = (
                    "family_requires_configuration_or_region"
                    if clarification else "explicit_registry_family"
                )
                query_intent = QueryIntent.FAMILY_OVERVIEW
        else:
            scope_type = ProductScopeType.CATALOG_FILTER
            status = ProductScopeResolutionStatus.RESOLVED
            clarification = False
            reason = "no_product_identity_catalog_filter"
            query_intent = QueryIntent.RECOMMENDATION_FILTER
        positive_mentions = [
            ProductMention(
                quote=item.quote,
                span_start=item.span_start,
                span_end=item.span_end,
                identity_kind=item.identity_kind,
                canonical_value=(item.product_id or item.family_id or item.configuration_id or item.quote),
                product_ids=item.matched_product_ids,
            )
            for item in included
            if item.identity_kind != "region"
        ]
        family_ids = sorted({
            value for product_id in candidates
            if (value := _identity_value(products[product_id], "family_id"))
        })
        configuration_ids = sorted({
            value for product_id in candidates
            if (value := _identity_value(products[product_id], "configuration_id"))
        })
        regions = sorted({str(products[product_id]["region"]) for product_id in candidates})
        return ResolvedProductScope(
            domain_id=self.domain_id,
            scope_type=scope_type,
            mentioned_quotes=list(dict.fromkeys(item.quote for item in positive_mentions)),
            mentions=positive_mentions,
            references=[*references, *unresolved],
            query_intent=query_intent,
            include_family_ids=sorted(include_families),
            exclude_family_ids=sorted(item for item in exclude_families if item),
            include_product_ids=sorted(include_products),
            exclude_product_ids=sorted(exclude_products),
            include_configuration_ids=sorted({item.configuration_id for item in included if item.configuration_id}),
            exclude_configuration_ids=sorted(item for item in exclude_configurations if item),
            allowed_regions=sorted(allowed_regions),
            excluded_regions=sorted(excluded_regions),
            unresolved_references=unresolved,
            family_ids=family_ids,
            product_ids=sorted(candidates),
            configuration_ids=configuration_ids,
            regions=regions,
            explicit_comparison=explicit_comparison,
            clarification_required=clarification,
            resolution_status=status,
            resolution_reason=reason,
            data_version=self.data_version,
            index_version=self.index_version,
        )
