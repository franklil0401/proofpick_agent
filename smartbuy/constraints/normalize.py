"""Deterministic, provenance-aware normalization for the supported constraint vocabulary."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Iterable

from .models import (
    ConstraintOperator,
    ConstraintProvenance,
    ConstraintSet,
    ConstraintStrength,
    NormalizedConstraint,
)


SUPPORTED_FIELDS = frozenset(
    {
        "price_cny",
        "display_size_inch",
        "resolution",
        "refresh_rate_hz",
        "is_oled",
        "has_usb_c",
        "usb_c_video",
        "usb_c_power_delivery_w",
        "width_mm",
        "brand",
        "stand_adjustment",
        "region",
    }
)

_RESOLUTION_ALIASES = {
    "2k": "2560x1440",
    "qhd": "2560x1440",
    "wqhd": "2560x1440",
    "1440p": "2560x1440",
    "4k": "3840x2160",
    "uhd": "3840x2160",
    "3840x2160": "3840x2160",
    "3840×2160": "3840x2160",
    "5k": "5120x2880",
    "8k": "7680x4320",
}

_BRAND_ALIASES = {
    "dell": "Dell",
    "戴尔": "Dell",
    "asus": "ASUS",
    "华硕": "ASUS",
    "lg": "LG",
    "benq": "BenQ",
    "明基": "BenQ",
}

_PREFERENCE_MAPPING = {
    "budget_min_cny": ("price_cny", ConstraintOperator.GTE, "CNY", ConstraintStrength.HARD),
    "budget_max_cny": ("price_cny", ConstraintOperator.LTE, "CNY", ConstraintStrength.HARD),
    "display_size_inch": ("display_size_inch", ConstraintOperator.EQ, "inch", ConstraintStrength.HARD),
    "resolution": ("resolution", ConstraintOperator.EQ, None, ConstraintStrength.HARD),
    "min_refresh_rate_hz": ("refresh_rate_hz", ConstraintOperator.GTE, "Hz", ConstraintStrength.HARD),
    "exclude_oled": ("is_oled", ConstraintOperator.EQ, None, ConstraintStrength.HARD),
    "excluded_brands": ("brand", ConstraintOperator.NOT_IN, None, ConstraintStrength.HARD),
    "primary_use": ("primary_use", ConstraintOperator.EQ, None, ConstraintStrength.SOFT),
}


def normalize_resolution(value: Any) -> str:
    token = str(value).strip().lower().replace(" ", "")
    return _RESOLUTION_ALIASES.get(token, token.replace("×", "x"))


class ConstraintNormalizer:
    """Build a ConstraintSet without trusting model-generated constraint values."""

    def build(
        self,
        query: str,
        *,
        source_turn: int,
        previous: ConstraintSet | None = None,
        preferences: dict[str, Any] | None = None,
        model_proposals: Iterable[dict[str, Any]] = (),
    ) -> ConstraintSet:
        constraints: list[NormalizedConstraint] = []
        constraints.extend(self._system_defaults(source_turn))
        constraints.extend(self._from_preferences(preferences or {}, source_turn))
        if previous:
            constraints.extend(self._from_session(previous))
        current, cancelled = self._from_current_input(query, source_turn)
        constraints.extend(current)

        cancel_all = "__all__" in cancelled
        cancelled.discard("__all__")
        current_fields = {item.field for item in current if item.active}
        for item in constraints:
            if item.provenance == ConstraintProvenance.CURRENT_INPUT:
                continue
            if cancel_all or item.field in cancelled or item.field in current_fields:
                item.active = False

        priority = {
            ConstraintProvenance.SYSTEM_DEFAULT: 0,
            ConstraintProvenance.LONG_TERM_PREFERENCE: 1,
            ConstraintProvenance.SESSION_CONFIRMED: 2,
            ConstraintProvenance.CURRENT_INPUT: 3,
        }
        highest_by_field: dict[str, int] = {}
        for item in constraints:
            if item.active:
                highest_by_field[item.field] = max(
                    highest_by_field.get(item.field, -1), priority[item.provenance]
                )
        for item in constraints:
            if item.active and priority[item.provenance] < highest_by_field[item.field]:
                item.active = False

        active_signatures = {
            (
                item.field,
                item.operator.value,
                self._value_signature(item.normalized_value),
                item.hard_or_soft.value,
            )
            for item in constraints
            if item.active
        }
        rejected: list[str] = []
        for proposal in model_proposals:
            field = str(proposal.get("field", ""))
            operator = str(proposal.get("operator", "eq"))
            value = proposal.get("value", proposal.get("normalized_value"))
            strength = "hard" if bool(proposal.get("hard", True)) else "soft"
            signature = (field, operator, self._value_signature(value), strength)
            if field not in {"model_id", "model_name"} and signature not in active_signatures:
                rejected.append(field or "unknown")

        return ConstraintSet(
            constraints=constraints,
            cancelled_fields=sorted(cancelled),
            rejected_model_constraints=list(dict.fromkeys(rejected)),
        )

    @staticmethod
    def _value_signature(value: Any) -> str:
        if isinstance(value, list):
            return "|".join(str(item).lower() for item in value)
        return str(value).lower()

    @staticmethod
    def _system_defaults(source_turn: int) -> list[NormalizedConstraint]:
        return [
            NormalizedConstraint(
                field="region",
                operator=ConstraintOperator.EQ,
                normalized_value="CN",
                hard_or_soft=ConstraintStrength.SOFT,
                provenance=ConstraintProvenance.SYSTEM_DEFAULT,
                source_text="默认展示中国大陆市场；未作为硬约束",
                source_turn=source_turn,
                confidence=1.0,
                supported=True,
            )
        ]

    @staticmethod
    def _from_session(previous: ConstraintSet) -> list[NormalizedConstraint]:
        output: list[NormalizedConstraint] = []
        for item in previous.active():
            if item.provenance == ConstraintProvenance.SYSTEM_DEFAULT:
                continue
            copied = deepcopy(item)
            copied.provenance = ConstraintProvenance.SESSION_CONFIRMED
            copied.active = True
            output.append(copied)
        return output

    @staticmethod
    def _from_preferences(preferences: dict[str, Any], source_turn: int) -> list[NormalizedConstraint]:
        output: list[NormalizedConstraint] = []
        for key, value in preferences.items():
            mapping = _PREFERENCE_MAPPING.get(key)
            if mapping is None:
                continue
            field, operator, unit, strength = mapping
            normalized = value
            if key == "exclude_oled":
                if not bool(value):
                    continue
                normalized = False
            elif key == "resolution":
                normalized = normalize_resolution(value)
            elif key == "excluded_brands":
                values = value if isinstance(value, list) else [value]
                normalized = [_BRAND_ALIASES.get(str(item).lower(), str(item)) for item in values]
            output.append(
                NormalizedConstraint(
                    field=field,
                    operator=operator,
                    normalized_value=normalized,
                    unit=unit,
                    hard_or_soft=strength,
                    provenance=ConstraintProvenance.LONG_TERM_PREFERENCE,
                    source_text=f"已启用的长期偏好：{key}",
                    source_turn=source_turn,
                    confidence=1.0,
                    supported=field in SUPPORTED_FIELDS,
                    note=None if field in SUPPORTED_FIELDS else "该偏好仅供解释，不参与确定性淘汰。",
                )
            )
        return output

    def _from_current_input(
        self, query: str, source_turn: int
    ) -> tuple[list[NormalizedConstraint], set[str]]:
        compact = query.lower().replace(" ", "").replace("，", ",")
        output: list[NormalizedConstraint] = []
        cancelled = self._cancelled_fields(compact)

        def add(
            field: str,
            operator: ConstraintOperator,
            value: Any,
            *,
            unit: str | None = None,
            strength: ConstraintStrength = ConstraintStrength.HARD,
            source_text: str | None = None,
            confidence: float = 1.0,
            supported: bool = True,
            ambiguous: bool = False,
            note: str | None = None,
        ) -> None:
            if field in cancelled:
                return
            output.append(
                NormalizedConstraint(
                    field=field,
                    operator=operator,
                    normalized_value=value,
                    unit=unit,
                    hard_or_soft=strength,
                    provenance=ConstraintProvenance.CURRENT_INPUT,
                    source_text=(source_text or query)[:300],
                    source_turn=source_turn,
                    confidence=confidence,
                    supported=supported and field in SUPPORTED_FIELDS,
                    ambiguous=ambiguous,
                    note=note,
                )
            )

        if "中国版" in compact or "中国大陆" in compact or "国行" in compact:
            add("region", ConstraintOperator.EQ, "CN", source_text="中国大陆/国行版本")

        price_range = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|到|至|~|～)\s*(\d+(?:\.\d+)?)元", query)
        if price_range:
            low, high = sorted((float(price_range.group(1)), float(price_range.group(2))))
            add("price_cny", ConstraintOperator.RANGE, [low, high], unit="CNY", source_text=price_range.group(0))
        else:
            budget = re.search(
                r"(?:预算(?:上限|改成|调整为)?|不超过|最多|控制在)(\d+(?:\.\d+)?)元",
                compact,
            )
            within = budget or re.search(r"(\d+(?:\.\d+)?)元(?:以内|以下)", compact)
            if within:
                add("price_cny", ConstraintOperator.LTE, float(within.group(1)), unit="CNY", source_text=within.group(0))
        if "再便宜一点" in compact and not any(item.field == "price_cny" for item in output):
            add(
                "price_cny", ConstraintOperator.LTE, None, unit="CNY", strength=ConstraintStrength.SOFT,
                source_text="再便宜一点", confidence=0.5, ambiguous=True,
                note="缺少可确定执行的预算数值，需要用户补充。",
            )

        size_range = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|到|至|~|～)\s*(\d+(?:\.\d+)?)\s*(?:英寸|寸)", query)
        if size_range:
            low, high = sorted((float(size_range.group(1)), float(size_range.group(2))))
            add("display_size_inch", ConstraintOperator.RANGE, [low, high], unit="inch", source_text=size_range.group(0))
        else:
            size = re.search(r"(\d+(?:\.\d+)?)\s*(?:英寸|寸)(左右)?", query)
            if size:
                vague = bool(size.group(2))
                add(
                    "display_size_inch", ConstraintOperator.EQ, float(size.group(1)), unit="inch",
                    strength=ConstraintStrength.SOFT if vague else ConstraintStrength.HARD,
                    source_text=size.group(0), confidence=0.7 if vague else 1.0, ambiguous=vague,
                    note="“左右”作为软偏好，不参与确定性淘汰。" if vague else None,
                )

        if "resolution" not in cancelled:
            for alias in sorted(_RESOLUTION_ALIASES, key=len, reverse=True):
                if alias in compact:
                    prefix = compact[max(0, compact.index(alias) - 4):compact.index(alias)]
                    operator = ConstraintOperator.GTE if any(token in prefix for token in ("至少", "不低于")) else ConstraintOperator.EQ
                    add("resolution", operator, _RESOLUTION_ALIASES[alias], source_text=alias.upper())
                    break

        refresh = re.search(r"(?:至少|不低于)(\d+(?:\.\d+)?)hz", compact)
        if refresh:
            add("refresh_rate_hz", ConstraintOperator.GTE, float(refresh.group(1)), unit="Hz", source_text=refresh.group(0))
        elif exact_refresh := re.search(r"(\d+(?:\.\d+)?)hz", compact):
            add("refresh_rate_hz", ConstraintOperator.EQ, float(exact_refresh.group(1)), unit="Hz", source_text=exact_refresh.group(0))

        if "is_oled" not in cancelled:
            if any(token in compact for token in ("不要oled", "非oled", "排除oled", "不考虑oled")):
                add("is_oled", ConstraintOperator.EQ, False, source_text="排除 OLED")
            elif "oled" in compact:
                add("is_oled", ConstraintOperator.EQ, True, source_text="要求 OLED")

        if "has_usb_c" not in cancelled:
            if any(token in compact for token in ("没有usb-c", "无usb-c", "不要usb-c", "排除usb-c")):
                add("has_usb_c", ConstraintOperator.EQ, False, source_text="不需要 USB-C")
            elif any(token in compact for token in ("需要usb-c", "有usb-c", "支持usb-c")):
                add("has_usb_c", ConstraintOperator.EQ, True, source_text="需要 USB-C")

        if "usb_c_video" not in cancelled and any(
            token in compact for token in ("usb-c视频", "usb-c输入视频", "usb-c视频输入", "usb-c传视频")
        ):
            add("usb_c_video", ConstraintOperator.EQ, True, source_text="USB-C 视频输入")
            if not any(item.field == "has_usb_c" for item in output):
                add("has_usb_c", ConstraintOperator.EQ, True, source_text="USB-C 视频输入隐含需要物理 USB-C")

        power = re.search(r"(?:至少|不少于|不低于)(\d+(?:\.\d+)?)w", compact)
        if power:
            add("usb_c_power_delivery_w", ConstraintOperator.GTE, float(power.group(1)), unit="W", source_text=power.group(0))
        elif exact_power := re.search(r"(\d+(?:\.\d+)?)w(?:供电|pd)", compact):
            add("usb_c_power_delivery_w", ConstraintOperator.GTE, float(exact_power.group(1)), unit="W", source_text=exact_power.group(0))
        if any(token in compact for token in ("不支持任何usb-c供电", "完全不支持usb-c供电")):
            add("usb_c_power_delivery_w", ConstraintOperator.EQ, None, unit="W", source_text="不支持 USB-C 供电")

        width_mm = re.search(r"(?:宽度|机身宽)(?:不超过|最多|小于等于)(\d+(?:\.\d+)?)mm", compact)
        width_cm = re.search(r"(?:宽度|机身宽)(?:不超过|最多|小于等于)(\d+(?:\.\d+)?)cm", compact)
        if width_mm:
            add("width_mm", ConstraintOperator.LTE, float(width_mm.group(1)), unit="mm", source_text=width_mm.group(0))
        elif width_cm:
            add("width_mm", ConstraintOperator.LTE, float(width_cm.group(1)) * 10.0, unit="mm", source_text=width_cm.group(0))

        brand_exclusions: list[str] = []
        brand_inclusions: list[str] = []
        brand_preferences: list[str] = []
        for alias, canonical in _BRAND_ALIASES.items():
            if alias not in compact:
                continue
            if any(token + alias in compact for token in ("不要", "排除", "不考虑", "拒绝")):
                brand_exclusions.append(canonical)
            elif any(token + alias in compact for token in ("只要", "只考虑", "仅限")):
                brand_inclusions.append(canonical)
            elif any(token + alias in compact for token in ("偏好", "更喜欢", "优先")):
                brand_preferences.append(canonical)
        if brand_exclusions:
            add("brand", ConstraintOperator.NOT_IN, list(dict.fromkeys(brand_exclusions)), source_text="品牌排除条件")
        if brand_inclusions:
            add("brand", ConstraintOperator.IN, list(dict.fromkeys(brand_inclusions)), source_text="品牌包含条件")
        if brand_preferences:
            add(
                "brand", ConstraintOperator.IN, list(dict.fromkeys(brand_preferences)),
                strength=ConstraintStrength.SOFT, source_text="品牌软偏好",
            )

        stand_features: list[str] = []
        if any(token in compact for token in ("升降", "高度调节")):
            stand_features.append("高度")
        if "旋转" in compact or "竖屏" in compact:
            stand_features.append("垂直旋转" if "竖屏" in compact else "旋转")
        if "俯仰" in compact:
            stand_features.append("俯仰")
        if stand_features and "stand_adjustment" not in cancelled:
            stand_is_soft = any(token in compact for token in ("希望", "偏好", "最好")) and not any(
                token in compact for token in ("必须", "需要")
            )
            add(
                "stand_adjustment", ConstraintOperator.CONTAINS_ALL,
                list(dict.fromkeys(stand_features)), source_text="支架调节要求",
                strength=ConstraintStrength.SOFT if stand_is_soft else ConstraintStrength.HARD,
            )

        unsupported_markers = {
            "摄像头": "camera",
            "人脸识别": "face_recognition",
            "十年都不会烧屏": "ten_year_burn_in_guarantee",
            "终身零坏点": "lifetime_zero_dead_pixel_guarantee",
            "hdr1000": "hdr_certification",
        }
        for marker, field in unsupported_markers.items():
            if marker in compact:
                add(
                    field, ConstraintOperator.EQ, True, source_text=marker,
                    supported=False, note="当前确定性复核器未声明支持该字段。",
                )
        return output, cancelled

    @staticmethod
    def _cancelled_fields(compact: str) -> set[str]:
        cancelled: set[str] = set()
        if any(token in compact for token in ("取消之前所有条件", "清空之前条件", "重新开始不继承")):
            cancelled.add("__all__")
        markers = {
            "price_cny": ("预算不限", "取消预算", "不再限制价格"),
            "display_size_inch": ("尺寸不限", "取消尺寸", "不再限制尺寸"),
            "resolution": ("分辨率不限", "取消分辨率"),
            "refresh_rate_hz": ("刷新率不限", "取消刷新率"),
            "is_oled": ("oled不限", "取消oled限制", "不再要求非oled", "不再要求oled"),
            "has_usb_c": ("usb-c不限", "取消usb-c限制"),
            "usb_c_video": ("不再需要usb-c视频", "取消usb-c视频"),
            "usb_c_power_delivery_w": ("供电不限", "取消供电要求", "不再要求供电"),
            "width_mm": ("宽度不限", "取消宽度限制"),
            "brand": ("品牌不限", "不限品牌", "取消品牌限制"),
            "stand_adjustment": ("支架不限", "取消支架要求"),
            "region": ("地区不限", "版本不限"),
        }
        for field, tokens in markers.items():
            if any(token in compact for token in tokens):
                cancelled.add(field)
        return cancelled
