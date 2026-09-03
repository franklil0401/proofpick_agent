"""Deterministic mapping from extracted official-page snippets to Domain Pack fields."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from smartbuy.domain_packs.loader import DomainPackValidationError, LoadedDomainPack
from smartbuy.open_research.models import (
    OpenEvidenceRecord,
    OpenEvidenceStatus,
    WebExtractionResult,
)


_FIELD_TERMS: dict[str, set[str]] = {
    "brand": {"brand", "品牌"},
    "region": {"region", "地区", "market"},
    "display_size_inch": {"screen size", "display size", "inch", "inches", "屏幕尺寸", "英寸"},
    "resolution": {"resolution", "4k uhd", "5k", "分辨率"},
    "refresh_rate_hz": {"refresh rate", "refresh", "hz", "刷新率"},
    "panel_type": {"panel type", "panel", "面板"},
    "is_oled": {"oled", "显示技术"},
    "has_usb_c": {"usb-c", "usb type-c", "type-c", "thunderbolt"},
    "usb_c_video": {"usb-c", "usb type-c", "thunderbolt", "displayport alt mode", "video"},
    "usb_c_power_delivery_w": {"power delivery", "power", "usb-c", "thunderbolt", "供电"},
    "stand_adjustment": {"stand", "height adjustment", "pivot", "swivel", "tilt", "支架"},
    "width_mm": {"width", "dimensions", "宽度"},
    "weight_kg": {"weight", "重量"},
    "memory_gb": {"memory", "ram", "内存"},
    "storage_gb": {"storage", "ssd", "solid state drive", "存储", "固态"},
    "battery_wh": {"battery", "watt hour", "wh", "电池"},
    "charger_w": {"adapter", "charger", "power supply", "适配器", "充电器"},
    "cpu_model": {"processor", "cpu", "处理器"},
    "gpu_model": {"graphics", "gpu", "显卡"},
    "usb_c": {"usb-c", "usb type-c", "type-c"},
    "thunderbolt": {"thunderbolt", "雷电", "雷雳"},
    "hdmi": {"hdmi"},
    "operating_system": {"operating system", "windows", "ubuntu", "操作系统"},
    "warranty": {"warranty", "保修"},
    "release_date": {"release date", "发布日期"},
}


def field_terms(pack: LoadedDomainPack, target_fields: list[str]) -> set[str]:
    output: set[str] = set()
    for requested in target_fields:
        try:
            field_id = pack.canonical_field(requested)
        except DomainPackValidationError:
            continue
        definition = pack.fields[field_id]
        output.add(definition.label)
        output.update(definition.aliases)
        output.update(_FIELD_TERMS.get(field_id, set()))
    return output


def _number(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _capacity_nearest_terms(text: str, terms: tuple[str, ...]) -> tuple[float, str] | None:
    folded = text.casefold()
    term_positions = [folded.find(term) for term in terms if term in folded]
    matches = list(re.finditer(r"(?<!\d)(\d{1,4}(?:\.\d+)?)\s*(tb|gb)\b", text, re.I))
    if not term_positions or not matches:
        return None
    match = min(
        matches,
        key=lambda item: min(abs(item.start() - position) for position in term_positions),
    )
    return float(match.group(1)), match.group(2).upper()


def _propose(field_id: str, text: str, target_model: str) -> tuple[Any, str | None] | None:
    folded = text.casefold()
    if field_id == "display_size_inch":
        value = _number(
            r"(?<!\d)(\d{2}(?:\.\d+)?)\s*(?:[\"”“″]|inch(?:es)?\b|英寸)",
            text,
        )
        return (value, "inch") if value is not None else None
    if field_id == "resolution":
        explicit = re.search(r"(?<!\d)(\d{3,5})\s*[x×]\s*(\d{3,5})(?!\d)", text)
        if explicit:
            return (f"{explicit.group(1)}x{explicit.group(2)}", None)
        if "resolution" in folded or "分辨率" in folded or target_model.casefold() in folded:
            for token in ("8k", "5k", "4k", "3k", "qhd", "wqhd", "1440p"):
                if token in folded:
                    return (token, None)
        return None
    if field_id == "refresh_rate_hz":
        if "refresh" not in folded and "刷新率" not in folded and target_model.casefold() not in folded:
            return None
        value = _number(r"(?<!\d)(\d{2,3}(?:\.\d+)?)\s*hz\b", text)
        return (value, "Hz") if value is not None else None
    if field_id == "usb_c_power_delivery_w":
        if not any(token in folded for token in ("usb-c", "usb type-c", "thunderbolt", "power delivery", "供电")):
            return None
        values = [float(item) for item in re.findall(r"(?<!\d)(\d{2,3}(?:\.\d+)?)\s*w\b", text, re.IGNORECASE)]
        if not values:
            return None
        nearby = max(values)
        return nearby, "W"
    if field_id == "has_usb_c":
        if any(token in folded for token in ("usb-c", "usb type-c", "type-c", "thunderbolt")):
            return True, None
        return None
    if field_id == "usb_c_video":
        has_port = any(token in folded for token in ("usb-c", "usb type-c", "thunderbolt"))
        video = any(token in folded for token in ("displayport", "video", "image", "monitor"))
        return (True, None) if has_port and video else None
    if field_id == "is_oled":
        if re.search(r"\b(?:woled|qd-oled|oled)\b", folded):
            return True, None
        if re.search(r"\b(?:ips|va|tn)\b", folded) and "panel" in folded:
            return False, None
        return None
    if field_id == "panel_type":
        match = re.search(r"\b(ips|va|tn|woled|qd-oled|oled)\b", folded)
        return (match.group(1).upper(), None) if match else None
    if field_id == "width_mm":
        if "width" not in folded and "宽" not in text:
            return None
        value = _number(r"(?:width|宽度?)\D{0,30}(\d{2,4}(?:\.\d+)?)\s*mm\b", text)
        return (value, "mm") if value is not None else None
    if field_id == "weight_kg":
        if "weight" not in folded and "重量" not in text:
            return None
        value = _number(r"(?:weight|重量)\D{0,30}(\d{1,3}(?:\.\d+)?)\s*kg\b", text)
        if value is not None:
            return value, "kg"
        pounds = _number(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*(?:lb|lbs|pounds?)\b", text)
        return (round(pounds * 0.45359237, 6), "kg") if pounds is not None else None
    if field_id in {"memory_gb", "storage_gb"}:
        terms = (
            ("memory", "ram", "内存")
            if field_id == "memory_gb"
            else ("storage", "ssd", "solid state", "存储", "固态")
        )
        if not any(token in folded for token in terms):
            return None
        capacity = _capacity_nearest_terms(text, terms)
        if capacity is None:
            return None
        value, unit = capacity
        return (value * 1024 if unit == "TB" else value), "GB"
    if field_id == "battery_wh":
        if "battery" not in folded and "电池" not in text:
            return None
        value = _number(r"(?<!\d)(\d{2,3}(?:\.\d+)?)\s*w(?:att)?[- ]?h(?:our)?s?\b", text)
        return (value, "Wh") if value is not None else None
    if field_id == "charger_w":
        if not any(token in folded for token in ("adapter", "charger", "power supply")):
            return None
        value = _number(r"(?<!\d)(\d{2,3}(?:\.\d+)?)\s*w\b", text)
        return (value, "W") if value is not None else None
    if field_id in {"usb_c", "thunderbolt", "hdmi"}:
        tokens = {
            "usb_c": ("usb-c", "usb type-c", "type-c"),
            "thunderbolt": ("thunderbolt",),
            "hdmi": ("hdmi",),
        }[field_id]
        return (True, None) if any(token in folded for token in tokens) else None
    if field_id == "operating_system":
        match = re.search(r"\b(windows\s+1[01](?:\s+(?:home|pro))?|ubuntu(?:\s+linux)?)\b", folded)
        return (match.group(1).title(), None) if match else None
    if field_id == "stand_adjustment":
        abilities = [
            label
            for token, label in (
                ("height", "height"), ("pivot", "pivot"), ("swivel", "swivel"), ("tilt", "tilt")
            )
            if token in folded
        ]
        return (", ".join(abilities), None) if abilities else None
    if field_id == "warranty":
        match = re.search(r"(?:warranty|保修|质保)\D{0,20}(\d+)\s*(year|years|年)", text, re.IGNORECASE)
        return (f"{match.group(1)} years", None) if match else None
    if field_id == "brand" and "benq" in folded:
        return "BenQ", None
    if field_id == "region":
        return None
    return None


class EvidenceNormalizer:
    def __init__(self, pack: LoadedDomainPack, *, ttl_seconds: int = 86_400) -> None:
        self.pack = pack
        self.ttl_seconds = ttl_seconds

    def normalize(
        self,
        extraction: WebExtractionResult,
        *,
        user_scope: str,
        session_scope: str,
        thread_scope: str,
        request_scope: str,
        provisional_product_id: str,
        target_model: str,
        product_region: str,
        target_fields: list[str],
        configuration: str | None = None,
    ) -> tuple[list[OpenEvidenceRecord], list[str]]:
        if (
            extraction.status.value != "success"
            or not extraction.final_url
            or not extraction.content_hash
            or extraction.detected_region != product_region
            or not extraction.title
        ):
            return [], list(dict.fromkeys(target_fields))
        expires = (
            datetime.fromisoformat(extraction.fetched_at.replace("Z", "+00:00"))
            + timedelta(seconds=self.ttl_seconds)
        ).astimezone(UTC).isoformat().replace("+00:00", "Z")
        output: list[OpenEvidenceRecord] = []
        unsupported: list[str] = []
        seen: set[tuple[str, str, str]] = set()
        for requested in list(dict.fromkeys(target_fields)):
            try:
                field_id = self.pack.canonical_field(requested)
            except DomainPackValidationError:
                unsupported.append(requested)
                continue
            field_records = 0
            for snippet in extraction.snippets:
                # Marketing comparison carousels often contain dimensions and
                # resolutions for neighbouring models. For these identity-
                # sensitive fields, visible text is accepted only when the same
                # bounded snippet names the target model. Structured table/JSON
                # rows remain eligible without repeating the page model.
                if snippet.kind == "visible_text" and field_id in {
                    "display_size_inch",
                    "resolution",
                }:
                    compact_model = re.sub(
                        r"[^a-z0-9]", "", target_model.casefold()
                    )
                    compact_snippet = re.sub(
                        r"[^a-z0-9]", "", snippet.text.casefold()
                    )
                    if compact_model not in compact_snippet:
                        continue
                proposal = _propose(field_id, snippet.text, target_model)
                if proposal is None:
                    continue
                raw_value, unit = proposal
                if raw_value is None or raw_value == "":
                    continue
                try:
                    normalized = self.pack.normalize_value(field_id, raw_value, unit=unit)
                except DomainPackValidationError:
                    continue
                signature = (field_id, repr(normalized), snippet.text)
                if signature in seen:
                    continue
                seen.add(signature)
                digest = hashlib.sha256(
                    "|".join(
                        [
                            request_scope,
                            provisional_product_id,
                            field_id,
                            repr(normalized),
                            extraction.content_hash,
                            snippet.locator,
                        ]
                    ).encode("utf-8")
                ).hexdigest()[:24]
                output.append(
                    OpenEvidenceRecord(
                        evidence_id=f"open-{digest}",
                        user_scope=user_scope,
                        session_scope=session_scope,
                        thread_scope=thread_scope,
                        request_scope=request_scope,
                        provisional_product_id=provisional_product_id,
                        field_name=field_id,
                        raw_value=raw_value,
                        normalized_value=normalized,
                        unit=self.pack.fields[field_id].unit,
                        source_url=extraction.requested_url,
                        final_url=extraction.final_url,
                        source_title=extraction.title,
                        source_region=extraction.detected_region,
                        product_region=product_region,
                        configuration=configuration,
                        exact_snippet=snippet.text,
                        snippet_locator=snippet.locator,
                        fetched_at=extraction.fetched_at,
                        observed_at=extraction.fetched_at,
                        content_hash=extraction.content_hash,
                        expires_at=expires,
                        confidence=(
                            "high"
                            if snippet.kind in {"json_ld", "specification"}
                            else "medium"
                        ),
                        status=OpenEvidenceStatus.MATCHED,
                    )
                )
                field_records += 1
                if field_records >= 5:
                    break
        return output, unsupported
