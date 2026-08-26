"""Derive normalized rows and public fact cards from the canonical catalog."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from .loader import Catalog


PRODUCT_FIELDS = (
    "model_id",
    "brand",
    "model_name",
    "region",
    "display_size_inch",
    "resolution",
    "refresh_rate_hz",
    "panel_type",
    "is_oled",
    "has_usb_c",
    "usb_c_video",
    "usb_c_power_delivery_w",
    "stand_adjustment",
    "width_mm",
    "weight_kg",
    "warranty",
    "release_date",
    "official_source_id",
    "source_updated_at",
)
EVIDENCE_FIELDS = tuple(field for field in PRODUCT_FIELDS if field not in {"official_source_id", "source_updated_at"})


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def display_value(field_name: str, value: Any) -> str:
    if value is None:
        return "未知"
    if isinstance(value, bool):
        return "是" if value else "否"
    units = {
        "display_size_inch": " 英寸",
        "refresh_rate_hz": " Hz",
        "usb_c_power_delivery_w": " W",
        "width_mm": " mm",
        "weight_kg": " kg",
    }
    return f"{value:g}{units.get(field_name, '')}" if isinstance(value, (int, float)) else str(value)


def source_rows(catalog: Catalog) -> list[dict[str, Any]]:
    rows = []
    for source in catalog.source_records:
        row = {key: value for key, value in source.items() if key != "governed_summary"}
        row["content_hash"] = catalog.source_hash(source)
        row["notes"] = f"{source['notes']} 治理摘要：{source['governed_summary']}"
        rows.append(row)
    return rows


def evidence_rows(catalog: Catalog) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for product in catalog.products:
        for field_name in EVIDENCE_FIELDS:
            value = product[field_name]
            if value is None:
                continue
            conflict_group = None
            if product["model_id"] == "benq-pd2705u-us" and field_name == "usb_c_power_delivery_w":
                conflict_group = "cg-benq-pd2705u-usb-c-pd"
            rows.append(
                {
                    "evidence_id": f"ev-{product['model_id']}-{slug(field_name)}",
                    "source_id": product["official_source_id"],
                    "model_id": product["model_id"],
                    "normalized_field": field_name,
                    "normalized_value": value,
                    "original_value": display_value(field_name, value),
                    "evidence_location": "官方资料对应规格项；公开仓库仅保留自制摘要",
                    "confidence_level": "high",
                    "effective_time": product["source_updated_at"],
                    "conflict_group": conflict_group,
                }
            )
    rows.extend(catalog.conflict_evidence)
    return rows


def fact_card(product: dict[str, Any], sources: Iterable[dict[str, Any]], price: dict[str, Any] | None) -> str:
    source_list = list(sources)
    price_text = "未知（没有可核验的价格观察）"
    if price:
        price_text = (
            f"CNY {price['price_cny']:.2f}；{price['seller']}；库存状态 {price['stock_status']}；"
            f"观察时间 {price['observed_at']}。动态价格只代表该次观察。"
        )
    usb_text = (
        f"有 USB-C：{display_value('has_usb_c', product['has_usb_c'])}；"
        f"USB-C 视频输入：{display_value('usb_c_video', product['usb_c_video'])}；"
        f"USB-C 供电：{display_value('usb_c_power_delivery_w', product['usb_c_power_delivery_w'])}。"
    )
    if product["model_id"] == "dell-u2724d-cn":
        usb_text += " 15W 是下行附件供电，不表示 USB-C 视频输入或笔记本上行充电。"
    if product["model_id"] == "dell-g2724d-cn":
        usb_text += " 随附或可用的 USB-C 转 DisplayPort 线材不等于显示器配有 USB-C 端口。"
    if product["model_id"] == "benq-pd2705u-us":
        usb_text += (
            " 官方规格页给出 65W，官方介绍素材另有 60W 描述；主值采用更具体的规格页并保留冲突。"
            " 零售标题还出现 Thunderbolt 3 描述，但官方规格仅列 USB-C，因此零售说法不能覆盖官方字段。"
        )
    source_lines = "\n".join(
        f"- [{source['title']}]({source['url']})（{source['region']}，访问 {source['accessed_at']}）"
        for source in source_list
    )
    unknowns = [
        field_name
        for field_name in ("weight_kg", "warranty", "release_date")
        if product[field_name] is None
    ]
    unknown_text = "、".join(unknowns) if unknowns else "无"
    return f"""# {product['brand']} {product['model_name']}（{product['region']}）

> 自制事实卡；数据版本 `monitor-cn-2026-08-26-v1`。这是对公开资料的结构化概括，不是原网页或手册副本。

## 型号与显示

- 稳定型号 ID：`{product['model_id']}`
- 地区/版本：{product['region']}
- 尺寸：{display_value('display_size_inch', product['display_size_inch'])}
- 分辨率：{display_value('resolution', product['resolution'])}
- 刷新率：{display_value('refresh_rate_hz', product['refresh_rate_hz'])}
- 面板：{display_value('panel_type', product['panel_type'])}；OLED：{display_value('is_oled', product['is_oled'])}

## USB-C 与接口判断

{usb_text}

## 支架与机身

- 支架：{display_value('stand_adjustment', product['stand_adjustment'])}
- 宽度：{display_value('width_mm', product['width_mm'])}
- 重量：{display_value('weight_kg', product['weight_kg'])}

## 价格与时间边界

{price_text}

## 来源与未知项

{source_lines}

- 当前未知字段：{unknown_text}。
- 不同地区版本不自动合并；动态价格不得当作长期事实。
"""


def jsonl(records: Iterable[dict[str, Any]]) -> str:
    return "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
