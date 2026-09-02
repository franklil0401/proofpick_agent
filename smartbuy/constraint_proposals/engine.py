"""Deterministic-first natural constraint parsing and strict proposal validation."""

from __future__ import annotations

import hashlib
import json
import re
import time
from copy import deepcopy
from typing import Any, Iterable

from smartbuy.constraints import (
    ConstraintNormalizer,
    ConstraintOperator,
    ConstraintProvenance,
    ConstraintSet,
    ConstraintStrength,
    NormalizedConstraint,
)
from smartbuy.domain_packs.loader import DomainPackValidationError, LoadedDomainPack

from .models import (
    ClarificationState,
    ConstraintDiff,
    ConstraintProposal,
    ConstraintResolution,
    ProposalAction,
    ProposalSource,
    ProposalStatus,
    SourceSpan,
)


ENGINE_VERSION = "proofpick-natural-constraints-v1"
_NUMBER = r"(?:\d+(?:\.\d+)?\s*[kK千]?|[零〇一二两三四五六七八九十百千万]+)"
_BRANDS = {
    "dell": "Dell",
    "戴尔": "Dell",
    "asus": "ASUS",
    "华硕": "ASUS",
    "lg": "LG",
    "benq": "BenQ",
    "明基": "BenQ",
}
_RESOLUTIONS = {
    "1440p": "2560x1440",
    "wqhd": "2560x1440",
    "qhd": "2560x1440",
    "2k": "2560x1440",
    "3840×2160": "3840x2160",
    "3840x2160": "3840x2160",
    "uhd": "3840x2160",
    "4k": "3840x2160",
    "5k": "5120x2880",
    "8k": "7680x4320",
}
_BOUNDS = {
    "price_cny": (0.0, 10_000_000.0),
    "display_size_inch": (10.0, 100.0),
    "refresh_rate_hz": (20.0, 1_000.0),
    "usb_c_power_delivery_w": (0.0, 500.0),
    "width_mm": (50.0, 10_000.0),
}


def _chinese_number(token: str) -> float:
    compact = token.strip().replace(" ", "")
    if re.fullmatch(r"\d+(?:\.\d+)?[kK]", compact):
        return float(compact[:-1]) * 1000.0
    if re.fullmatch(r"\d+(?:\.\d+)?千", compact):
        return float(compact[:-1]) * 1000.0
    if re.fullmatch(r"\d+(?:\.\d+)?", compact):
        return float(compact)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    colloquial = re.fullmatch(r"([一二两三四五六七八九])千([一二三四五六七八九])", compact)
    if colloquial:
        return float(digits[colloquial.group(1)] * 1000 + digits[colloquial.group(2)] * 100)
    total = section = number = 0
    units = {"十": 10, "百": 100, "千": 1000, "万": 10_000}
    for char in compact:
        if char in digits:
            number = digits[char]
            continue
        unit = units.get(char)
        if unit is None:
            raise ValueError("unsupported numeric token")
        if unit == 10_000:
            section = (section + number) * unit
            total += section
            section = number = 0
        else:
            section += (number or 1) * unit
            number = 0
    return float(total + section + number)


def _proposal_id(query: str, field: str, action: ProposalAction, span: SourceSpan) -> str:
    raw = f"{query}\0{field}\0{action.value}\0{span.start}\0{span.end}\0{span.text}"
    return "cp-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class ConstraintProposalValidator:
    """Validate rule/LLM proposals against exact text and the active Domain Pack."""

    def __init__(self, pack: LoadedDomainPack) -> None:
        self.pack = pack

    def validate(
        self,
        query: str,
        raw: dict[str, Any],
        *,
        source: ProposalSource,
        source_turn: int,
    ) -> ConstraintProposal:
        field = str(raw.get("field", "unknown"))[:80] or "unknown"
        action_raw = str(raw.get("action", "add"))
        try:
            action = ProposalAction(action_raw)
        except ValueError:
            action = ProposalAction.ADD
        span = self._span(query, raw)
        if span is None:
            fallback = SourceSpan(start=0, end=max(1, min(len(query), 1)), text=query[:1] or "?")
            return self._invalid(field, action, fallback, source, source_turn, "source_span_invalid")
        proposal_id = _proposal_id(query, field, action, span)
        if action == ProposalAction.CANCEL:
            try:
                canonical = self.pack.canonical_field(field)
            except DomainPackValidationError:
                canonical = field
                status = ProposalStatus.UNSUPPORTED
                reason = "field_not_declared_by_domain_pack"
            else:
                status = ProposalStatus.SUPPORTED
                reason = "validated_cancel"
            return ConstraintProposal(
                proposal_id=proposal_id,
                field=canonical,
                status=status,
                action=action,
                source=source,
                source_span=span,
                source_turn=source_turn,
                confidence=float(raw.get("confidence", 1.0)),
                reason=reason,
            )
        try:
            canonical = self.pack.canonical_field(field)
        except DomainPackValidationError:
            return ConstraintProposal(
                proposal_id=proposal_id,
                field=field,
                operator=self._operator_or_none(raw.get("operator")),
                normalized_value=raw.get("value", raw.get("normalized_value")),
                unit=raw.get("unit"),
                strength=self._strength(raw.get("strength")),
                action=action,
                status=(
                    ProposalStatus.UNSUPPORTED
                    if source == ProposalSource.RULE
                    else ProposalStatus.INVALID
                ),
                source=source,
                source_span=span,
                source_turn=source_turn,
                confidence=float(raw.get("confidence", 0.0)),
                reason="field_not_declared_by_domain_pack",
            )
        operator = self._operator_or_none(raw.get("operator"))
        if operator is None:
            return self._invalid(canonical, action, span, source, source_turn, "operator_invalid")
        try:
            self.pack.validate_operator(canonical, operator.value)
        except DomainPackValidationError:
            return self._invalid(canonical, action, span, source, source_turn, "operator_not_allowed")
        status_raw = str(raw.get("status", "supported"))
        try:
            status = ProposalStatus(status_raw)
        except ValueError:
            status = ProposalStatus.INVALID
        value = raw.get("value", raw.get("normalized_value"))
        unit = raw.get("unit")
        if status in {ProposalStatus.AMBIGUOUS, ProposalStatus.NEEDS_CONFIRMATION}:
            normalized = self._normalize_if_present(canonical, operator, value, unit)
            return ConstraintProposal(
                proposal_id=proposal_id,
                field=canonical,
                operator=operator,
                normalized_value=normalized,
                unit=self.pack.fields[canonical].unit,
                strength=self._strength(raw.get("strength")),
                action=action,
                status=status,
                source=source,
                source_span=span,
                source_turn=source_turn,
                confidence=float(raw.get("confidence", 0.5)),
                reason=str(raw.get("reason") or "clarification_required")[:240],
            )
        try:
            normalized = self._normalize(canonical, operator, value, unit)
            self._validate_bounds(canonical, normalized)
        except (DomainPackValidationError, TypeError, ValueError):
            return self._invalid(canonical, action, span, source, source_turn, "value_or_unit_invalid")
        return ConstraintProposal(
            proposal_id=proposal_id,
            field=canonical,
            operator=operator,
            normalized_value=normalized,
            unit=self.pack.fields[canonical].unit,
            strength=self._strength(raw.get("strength")),
            action=action,
            status=ProposalStatus.SUPPORTED,
            source=source,
            source_span=span,
            source_turn=source_turn,
            confidence=float(raw.get("confidence", 1.0)),
            active=True,
            reason="schema_and_domain_pack_validated",
        )

    @staticmethod
    def _span(query: str, raw: dict[str, Any]) -> SourceSpan | None:
        try:
            start = int(raw["span_start"])
            end = int(raw["span_end"])
            text = str(raw["span_text"])
        except (KeyError, TypeError, ValueError):
            return None
        if start < 0 or end <= start or end > len(query) or query[start:end] != text:
            return None
        return SourceSpan(start=start, end=end, text=text)

    @staticmethod
    def _operator_or_none(value: Any) -> ConstraintOperator | None:
        try:
            return ConstraintOperator(str(value))
        except ValueError:
            return None

    @staticmethod
    def _strength(value: Any) -> ConstraintStrength:
        try:
            return ConstraintStrength(str(value or "hard"))
        except ValueError:
            return ConstraintStrength.HARD

    def _normalize_if_present(
        self, field: str, operator: ConstraintOperator, value: Any, unit: str | None
    ) -> Any:
        if value is None:
            return None
        try:
            return self._normalize(field, operator, value, unit)
        except (DomainPackValidationError, TypeError, ValueError):
            return None

    def _normalize(
        self, field: str, operator: ConstraintOperator, value: Any, unit: str | None
    ) -> Any:
        if operator == ConstraintOperator.RANGE:
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError("range requires two values")
            values = [self.pack.normalize_value(field, item, unit=unit) for item in value]
            return sorted(values)
        if operator in {ConstraintOperator.IN, ConstraintOperator.NOT_IN, ConstraintOperator.CONTAINS_ALL}:
            if not isinstance(value, list) or not value:
                raise ValueError("list operator requires values")
            return [self.pack.normalize_value(field, item, unit=unit) for item in value]
        return self.pack.normalize_value(field, value, unit=unit)

    @staticmethod
    def _validate_bounds(field: str, value: Any) -> None:
        if field not in _BOUNDS:
            return
        low, high = _BOUNDS[field]
        values = value if isinstance(value, list) else [value]
        if any(not isinstance(item, (int, float)) or not low <= float(item) <= high for item in values):
            raise ValueError("numeric value outside supported range")

    @staticmethod
    def _invalid(
        field: str,
        action: ProposalAction,
        span: SourceSpan,
        source: ProposalSource,
        source_turn: int,
        reason: str,
    ) -> ConstraintProposal:
        return ConstraintProposal(
            proposal_id=_proposal_id(span.text, field, action, span),
            field=field,
            status=ProposalStatus.INVALID,
            action=action,
            source=source,
            source_span=span,
            source_turn=source_turn,
            confidence=0.0,
            reason=reason,
        )


class DeterministicConstraintParser:
    def __init__(self, pack: LoadedDomainPack) -> None:
        self.validator = ConstraintProposalValidator(pack)

    def parse(
        self,
        query: str,
        *,
        source_turn: int,
        previous_fields: Iterable[str] = (),
    ) -> list[ConstraintProposal]:
        previous = set(previous_fields)
        raws: list[dict[str, Any]] = []

        def add(
            field: str,
            operator: str | None,
            value: Any,
            match: re.Match[str],
            *,
            unit: str | None = None,
            strength: str = "hard",
            status: str = "supported",
            action: str | None = None,
            reason: str | None = None,
        ) -> None:
            chosen_action = action or ("override" if field in previous else "add")
            raws.append(
                {
                    "field": field,
                    "operator": operator,
                    "value": value,
                    "unit": unit,
                    "strength": strength,
                    "status": status,
                    "action": chosen_action,
                    "span_start": match.start(),
                    "span_end": match.end(),
                    "span_text": match.group(0),
                    "confidence": 1.0 if status == "supported" else 0.6,
                    "reason": reason,
                }
            )

        compact = query.casefold()
        cancelled: set[str] = set()
        cancel_patterns = {
            "price_cny": r"(?:取消预算(?:限制)?|预算不限|不再限制价格)",
            "display_size_inch": r"(?:取消尺寸(?:限制)?|尺寸不限|不再限制尺寸)",
            "resolution": r"(?:分辨率不限|取消分辨率)",
            "refresh_rate_hz": r"(?:刷新率不限|取消刷新率)",
            "is_oled": r"(?:不再要求非\s*oled|不再要求\s*oled|不排斥\s*oled|oled\s*不限)",
            "has_usb_c": r"(?:(?:usb[\s_-]?c|type[\s_-]?c)不限|取消(?:usb[\s_-]?c|type[\s_-]?c)限制)",
            "usb_c_video": r"(?:不再需要(?:usb[\s_-]?c|type[\s_-]?c)视频|取消(?:usb[\s_-]?c|type[\s_-]?c)视频)",
            "usb_c_power_delivery_w": r"(?:供电不限|取消供电要求|不再要求供电)",
            "width_mm": r"(?:宽度不限|取消宽度限制)",
            "brand": r"(?:品牌不限|不限品牌|取消品牌限制)",
            "stand_adjustment": r"(?:支架不限|取消支架要求)",
            "region": r"(?:地区不限|版本不限)",
        }
        for field, pattern in cancel_patterns.items():
            if match := re.search(pattern, query, flags=re.I):
                cancelled.add(field)
                add(field, None, None, match, action="cancel")

        if match := re.search(r"([一二两三四五六七八九])([一二三四五六七八九])千", query):
            low = _chinese_number(match.group(1) + "千")
            high = _chinese_number(match.group(2) + "千")
            add(
                "price_cny", "range", sorted([low, high]), match, unit="CNY",
                status="needs_confirmation", reason="colloquial_price_range",
            )
        elif any(token in compact for token in ("预算", "价格", "元", "以内", "以下")):
            range_match = re.search(
                rf"({_NUMBER})\s*(?:元)?\s*(?:到|至|[-~～])\s*({_NUMBER})\s*元?",
                query,
                flags=re.I,
            )
            if range_match:
                add(
                    "price_cny", "range",
                    sorted([_chinese_number(range_match.group(1)), _chinese_number(range_match.group(2))]),
                    range_match, unit="CNY",
                )
            else:
                upper = re.search(
                    rf"(?:(?:预算|价格)(?:上限|改成|调整为)?\s*)?(?:不超过|最多|控制在)?\s*({_NUMBER})\s*元?\s*(?:以内|以下)",
                    query,
                    flags=re.I,
                ) or re.search(
                    rf"(?:预算|价格)?\s*(?:不超过|最多|控制在)\s*({_NUMBER})\s*元?",
                    query,
                    flags=re.I,
                ) or re.search(
                    rf"(?:预算|价格)(?:上限|改成|调整为)?\s*({_NUMBER})\s*元",
                    query,
                    flags=re.I,
                )
                if upper:
                    add("price_cny", "lte", _chinese_number(upper.group(1)), upper, unit="CNY")

        if "display_size_inch" not in cancelled:
            if vague := re.search(r"(?:屏幕|尺寸)?\s*不要太大", query, flags=re.I):
                add(
                    "display_size_inch", "lte", None, vague, unit="inch",
                    status="ambiguous", reason="size_limit_missing",
                )
            size_range = re.search(
                rf"({_NUMBER})\s*(?:到|至|[-~～])\s*({_NUMBER})\s*(?:英寸|寸|inch)",
                query,
                flags=re.I,
            )
            if size_range:
                add(
                    "display_size_inch", "range",
                    sorted([_chinese_number(size_range.group(1)), _chinese_number(size_range.group(2))]),
                    size_range, unit="inch",
                )
            else:
                size = re.search(
                    rf"(?:(至少|不低于)\s*)?({_NUMBER})\s*(?:英寸|寸|inch)\s*(左右|以下|以内)?",
                    query,
                    flags=re.I,
                )
                if size:
                    suffix = (size.group(3) or "").casefold()
                    operator = "gte" if size.group(1) else ("lte" if suffix in {"以下", "以内"} else "eq")
                    status = "needs_confirmation" if suffix == "左右" else "supported"
                    add(
                        "display_size_inch", operator, _chinese_number(size.group(2)), size,
                        unit="inch", strength="soft" if suffix == "左右" else "hard",
                        status=status, reason="approximate_size" if status != "supported" else None,
                    )

        if "resolution" not in cancelled:
            for alias in sorted(_RESOLUTIONS, key=len, reverse=True):
                match = re.search(re.escape(alias), query, flags=re.I)
                if match:
                    prefix = query[max(0, match.start() - 8):match.start()].casefold()
                    suffix = query[match.end():match.end() + 6].casefold()
                    operator = "gte" if any(x in prefix + suffix for x in ("至少", "不低于", "更高")) else "eq"
                    add("resolution", operator, _RESOLUTIONS[alias], match)
                    break

        if "refresh_rate_hz" not in cancelled:
            if high_refresh := re.search(r"高刷就行", query):
                add(
                    "refresh_rate_hz", "gte", None, high_refresh, unit="Hz",
                    status="ambiguous", reason="refresh_threshold_missing",
                )
            refresh = re.search(
                rf"(?:(至少|不低于|不少于)\s*)?({_NUMBER})\s*(?:hz|赫兹)",
                query,
                flags=re.I,
            )
            if refresh:
                add(
                    "refresh_rate_hz", "gte" if refresh.group(1) else "eq",
                    _chinese_number(refresh.group(2)), refresh, unit="Hz",
                )

        if "is_oled" not in cancelled:
            if match := re.search(r"不能不要\s*oled", query, flags=re.I):
                add("is_oled", "eq", True, match)
            elif match := re.search(r"(?:不要|别给我|非|排除|不考虑)\s*oled", query, flags=re.I):
                add("is_oled", "eq", False, match)
            elif match := re.search(r"\boled\b", query, flags=re.I):
                add("is_oled", "eq", True, match)

        usb_pattern = r"(?:usb[\s_-]?c|type[\s_-]?c)"
        usb_match = re.search(usb_pattern, query, flags=re.I)
        if usb_match and "has_usb_c" not in cancelled:
            double_negative = re.search(rf"不要不带\s*{usb_pattern}\s*的", query, flags=re.I)
            negative = re.search(rf"(?:不需要|不要|无|排除)\s*{usb_pattern}", query, flags=re.I)
            if double_negative:
                add("has_usb_c", "eq", True, double_negative)
            elif negative:
                add("has_usb_c", "eq", False, negative)
            elif re.search(r"(?:一线通|传视频|视频)", query[usb_match.start():], flags=re.I):
                video = re.search(rf"{usb_pattern}[^，。；]*?(?:一线通|传视频|视频)", query, flags=re.I)
                assert video is not None
                add("usb_c_video", "eq", True, video)
                add("has_usb_c", "eq", True, video)
            elif not re.search(r"(?:供电|充电|\bpd\b|瓦|\bw\b)", query, flags=re.I):
                add("has_usb_c", "eq", True, usb_match)
        power = re.search(
            rf"(?:(?:{usb_pattern})[^，。；]*?)?(?:(?:至少|不少于|不低于|别低于)\s*)?({_NUMBER})\s*(?:w|瓦)(?:供电|pd)?",
            query,
            flags=re.I,
        )
        if power and any(token in compact for token in ("供电", "pd", "type-c", "type c", "usb-c", "usb c")):
            add(
                "usb_c_power_delivery_w", "gte", _chinese_number(power.group(1)), power,
                unit="W",
            )
            # A terse "USB-C PD 65W" also explicitly requires the interface.
            # Natural-language power requirements such as "USB-C 至少 90 瓦供电"
            # remain one field: the PD constraint already implies what must be
            # checked, while avoiding an extra proposal the user did not state.
            if (
                usb_match
                and re.search(r"(?:\bpd\b|别低于)", query, flags=re.I)
                and not any(item["field"] == "has_usb_c" for item in raws)
            ):
                add("has_usb_c", "eq", True, usb_match)
        elif usb_match and re.search(r"给笔记本充电|为笔记本充电", query):
            charging = re.search(rf"{usb_pattern}[^，。；]*?(?:给|为)笔记本充电", query, flags=re.I)
            assert charging is not None
            add(
                "usb_c_power_delivery_w", "gte", None, charging, unit="W",
                status="needs_confirmation", reason="power_threshold_missing",
            )

        if "width_mm" not in cancelled:
            width = re.search(
                rf"(?:机身宽度|机身宽|宽度)\s*(?:不超过|最多|小于等于)?\s*({_NUMBER})\s*(mm|毫米|cm|厘米)",
                query,
                flags=re.I,
            )
            if width:
                raw_value = _chinese_number(width.group(1))
                unit = width.group(2).casefold()
                factor = 10.0 if unit in {"cm", "厘米"} else 1.0
                add("width_mm", "lte", raw_value * factor, width, unit="mm")

        if "brand" not in cancelled:
            for alias, brand in _BRANDS.items():
                match = re.search(re.escape(alias), query, flags=re.I)
                if not match:
                    continue
                prefix = query[max(0, match.start() - 8):match.start()].casefold()
                if any(token in prefix for token in ("排除", "不要", "不考虑", "拒绝")):
                    add("brand", "not_in", [brand], match)
                elif any(token in prefix for token in ("只考虑", "只要", "仅限")):
                    add("brand", "in", [brand], match)
                elif any(token in prefix for token in ("优先", "偏好", "更喜欢")):
                    add("brand", "in", [brand], match, strength="soft")
                break

        if "stand_adjustment" not in cancelled:
            stand = re.search(r"(?:支架[^，。；]*)?(升降|高度调节)(?:和|、)?(旋转|竖屏)?", query)
            if stand:
                values = ["高度"]
                if stand.group(2):
                    values.append("旋转")
                soft = any(token in query[max(0, stand.start() - 6):stand.end()] for token in ("最好", "希望", "偏好"))
                add(
                    "stand_adjustment", "contains_all", values, stand,
                    strength="soft" if soft else "hard",
                )

        if "region" not in cancelled:
            regions = ((r"(?:国行|中国大陆|中国版)", "CN"), (r"美国版", "US"), (r"加拿大版", "CA"))
            for pattern, value in regions:
                if match := re.search(pattern, query):
                    add("region", "eq", value, match)
                    break

        unsupported = {
            r"摄像头": ("camera", True),
            r"蓝牙": ("bluetooth", True),
            r"hdr\s*1000": ("hdr_certification", "HDR1000"),
            r"色彩(?:一定要)?准|颜色准确": ("color_accuracy", True),
        }
        for pattern, (field, value) in unsupported.items():
            if match := re.search(pattern, query, flags=re.I):
                add(field, "eq", value, match, status="unsupported", reason="field_not_declared_by_domain_pack")

        proposals = [
            self.validator.validate(query, raw, source=ProposalSource.RULE, source_turn=source_turn)
            for raw in raws
        ]
        return self._deduplicate_and_mark_conflicts(proposals)

    @staticmethod
    def _deduplicate_and_mark_conflicts(
        proposals: list[ConstraintProposal],
    ) -> list[ConstraintProposal]:
        unique: list[ConstraintProposal] = []
        seen: set[str] = set()
        for item in proposals:
            signature = json.dumps(
                [item.field, item.operator, item.normalized_value, item.action, item.status, item.strength],
                default=str,
                sort_keys=True,
            )
            if signature not in seen:
                seen.add(signature)
                unique.append(item)
        by_field: dict[str, list[ConstraintProposal]] = {}
        for item in unique:
            if item.active and item.action != ProposalAction.CANCEL:
                by_field.setdefault(item.field, []).append(item)
        conflicted = {
            field
            for field, items in by_field.items()
            if len({json.dumps(item.normalized_value, sort_keys=True) for item in items}) > 1
        }
        if not conflicted:
            return unique
        output: list[ConstraintProposal] = []
        for item in unique:
            if item.field in conflicted:
                output.append(
                    item.model_copy(
                        update={
                            "status": ProposalStatus.NEEDS_CONFIRMATION,
                            "active": False,
                            "reason": "current_input_constraints_conflict",
                        }
                    )
                )
            else:
                output.append(item)
        return output


class NaturalConstraintEngine:
    def __init__(
        self,
        pack: LoadedDomainPack,
        provider: Any | None = None,
        *,
        max_provider_calls: int = 1,
        max_cost_cny: float = 0.05,
    ) -> None:
        self.pack = pack
        self.parser = DeterministicConstraintParser(pack)
        self.validator = ConstraintProposalValidator(pack)
        self.provider = provider
        self.max_provider_calls = max_provider_calls
        self.max_cost_cny = max_cost_cny
        self.legacy = ConstraintNormalizer()

    async def resolve(
        self,
        query: str,
        *,
        source_turn: int,
        previous: ConstraintSet | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> ConstraintResolution:
        started = time.perf_counter()
        previous_fields = [item.field for item in previous.active()] if previous else []
        proposals = self.parser.parse(
            query, source_turn=source_turn, previous_fields=previous_fields
        )
        provider_calls = input_tokens = output_tokens = 0
        cost = provider_latency = 0.0
        if (
            not proposals
            and self.provider is not None
            and self.max_provider_calls > 0
            and self._needs_fallback(query)
        ):
            result = await self.provider.propose(query, self.pack)
            provider_calls = 1
            input_tokens = int(result.get("input_tokens", 0))
            output_tokens = int(result.get("output_tokens", 0))
            cost = float(result.get("estimated_cost_cny", 0.0))
            if cost > self.max_cost_cny:
                raise RuntimeError("constraint proposal cost limit exceeded")
            provider_latency = float(result.get("latency_ms", 0.0))
            proposals = [
                self.validator.validate(
                    query, raw, source=ProposalSource.LLM, source_turn=source_turn
                )
                for raw in result.get("proposals", [])
            ]
        base = self.legacy.build(
            "",
            source_turn=source_turn,
            previous=previous,
            preferences=preferences or {},
        )
        constraint_set, activated, diffs = self._apply(base, proposals)
        pending = [
            item.proposal_id
            for item in activated
            if item.status in {ProposalStatus.AMBIGUOUS, ProposalStatus.NEEDS_CONFIRMATION}
        ]
        return ConstraintResolution(
            query=query,
            source_turn=source_turn,
            proposals=activated,
            constraint_set=constraint_set,
            clarification_state=(
                ClarificationState.PENDING if pending else ClarificationState.NOT_REQUIRED
            ),
            clarification_question=self._question(activated) if pending else None,
            pending_proposal_ids=pending,
            diff=diffs,
            provider_calls=provider_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=round(max((time.perf_counter() - started) * 1000, provider_latency), 3),
            estimated_cost_cny=cost,
        )

    def confirm(self, resolution: ConstraintResolution, answer: Any) -> ConstraintResolution:
        accepted = self._affirmative(answer)
        proposals: list[ConstraintProposal] = []
        for item in resolution.proposals:
            if item.proposal_id not in resolution.pending_proposal_ids:
                proposals.append(item)
                continue
            if accepted:
                if item.normalized_value is None:
                    proposals.append(
                        item.model_copy(
                            update={
                                "status": ProposalStatus.INVALID,
                                "active": False,
                                "reason": "confirmation_missing_concrete_value",
                            }
                        )
                    )
                else:
                    proposals.append(
                        item.model_copy(
                            update={
                                "status": ProposalStatus.SUPPORTED,
                                "active": True,
                                "action": ProposalAction.CONFIRM,
                                "reason": "explicitly_confirmed",
                            }
                        )
                    )
            else:
                proposals.append(
                    item.model_copy(
                        update={
                            "status": ProposalStatus.INVALID,
                            "active": False,
                            "reason": "user_rejected_clarification",
                        }
                    )
                )
        constraint_set, proposals, diffs = self._apply(
            resolution.constraint_set, proposals, only_confirmed=True
        )
        return resolution.model_copy(
            update={
                "proposals": proposals,
                "constraint_set": constraint_set,
                "clarification_state": (
                    ClarificationState.CONFIRMED if accepted else ClarificationState.REJECTED
                ),
                "clarification_question": None,
                "pending_proposal_ids": [],
                "diff": [*resolution.diff, *diffs],
            }
        )

    @staticmethod
    def _needs_fallback(query: str) -> bool:
        lowered = query.casefold()
        return any(
            token in lowered
            for token in ("必须", "不要", "至少", "不超过", "偏好", "需要", "最好", "限制")
        )

    @staticmethod
    def _affirmative(answer: Any) -> bool:
        if isinstance(answer, bool):
            return answer
        if isinstance(answer, dict):
            return bool(answer.get("confirmed", False))
        return str(answer).strip().casefold() in {
            "是", "确认", "确定", "可以", "yes", "true", "作为硬约束", "继续"
        }

    @staticmethod
    def _question(proposals: list[ConstraintProposal]) -> str:
        pending = [
            item
            for item in proposals
            if item.status in {ProposalStatus.AMBIGUOUS, ProposalStatus.NEEDS_CONFIRMATION}
        ]
        descriptions = "；".join(
            f"{item.source_span.text} → {item.field} {item.operator or ''} {item.normalized_value}"
            for item in pending[:4]
        )
        return f"请确认这些条件是否应进入筛选：{descriptions}。缺少具体数值时请直接补充数值。"

    @staticmethod
    def _apply(
        base: ConstraintSet,
        proposals: list[ConstraintProposal],
        *,
        only_confirmed: bool = False,
    ) -> tuple[ConstraintSet, list[ConstraintProposal], list[ConstraintDiff]]:
        constraints = [deepcopy(item) for item in base.constraints]
        cancelled = set(base.cancelled_fields)
        output: list[ConstraintProposal] = []
        diffs: list[ConstraintDiff] = []
        for original in proposals:
            item = original
            if only_confirmed and item.action != ProposalAction.CONFIRM:
                output.append(item)
                continue
            before_items = [
                current.model_dump(mode="json")
                for current in constraints
                if current.active and current.field == item.field
            ]
            if item.status != ProposalStatus.SUPPORTED:
                output.append(item.model_copy(update={"active": False}))
                continue
            for current in constraints:
                if current.field == item.field and current.active:
                    current.active = False
            if item.action == ProposalAction.CANCEL:
                cancelled.add(item.field)
                output.append(item.model_copy(update={"active": False}))
                diffs.append(
                    ConstraintDiff(
                        field=item.field,
                        action=item.action,
                        before=before_items,
                        after=[],
                        proposal_id=item.proposal_id,
                    )
                )
                continue
            assert item.operator is not None
            constraint = NormalizedConstraint(
                field=item.field,
                operator=item.operator,
                normalized_value=item.normalized_value,
                unit=item.unit,
                hard_or_soft=item.strength,
                provenance=ConstraintProvenance.CURRENT_INPUT,
                source_text=item.source_span.text,
                source_turn=item.source_turn,
                confidence=item.confidence,
                supported=True,
                active=True,
                ambiguous=False,
                note=None,
            )
            constraints.append(constraint)
            item = item.model_copy(update={"active": True})
            output.append(item)
            # Proposal action describes the user's language. Replacing a system
            # default is recorded in the diff but is not rewritten into an
            # explicit user override. Explicit session overrides are already
            # assigned by the parser from previous_fields.
            action = item.action
            diff_action = (
                ProposalAction.OVERRIDE
                if action == ProposalAction.ADD and before_items
                else action
            )
            diffs.append(
                ConstraintDiff(
                    field=item.field,
                    action=diff_action,
                    before=before_items,
                    after=[constraint.model_dump(mode="json")],
                    proposal_id=item.proposal_id,
                )
            )
        return (
            ConstraintSet(
                constraints=constraints,
                cancelled_fields=sorted(cancelled),
                rejected_model_constraints=list(base.rejected_model_constraints),
            ),
            output,
            diffs,
        )
