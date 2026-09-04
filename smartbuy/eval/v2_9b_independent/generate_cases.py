"""Generate the independent V2-9B release evaluation definitions.

This evaluator intentionally reads only the frozen governed data.  It does
not import the production constraint evaluator, identity resolver, Agent, or
Checker when deriving gold labels.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
CASES = OUT / "trusted_cases.jsonl"
ONLINE_CASES = OUT / "online_cases.jsonl"
MANIFEST = OUT / "case_manifest.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def _fact(
    case_id: str,
    domain: str,
    question: str,
    product_id: str,
    fields: list[str],
    all_ids: list[str],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "domain_id": domain,
        "category": "exact_fact",
        "question": question,
        "expected_kind": "referenced",
        "expected_product_ids": [product_id],
        "expected_constraints": [],
        "required_evidence": [
            {"product_id": product_id, "field_id": field, "status": "matched"}
            for field in fields
        ],
        "forbidden_product_ids": sorted(set(all_ids) - {product_id}),
        "hard_negative": False,
        "evaluation_state": "frozen_unrun",
        "run_count": 0,
    }


def _filter(
    case_id: str,
    domain: str,
    question: str,
    constraints: list[tuple[str, str, Any, str | None]],
    expected: list[str],
    *,
    all_ids: list[str],
    category: str = "catalog_filter",
) -> dict[str, Any]:
    fields = [field for field, *_ in constraints]
    return {
        "case_id": case_id,
        "domain_id": domain,
        "category": category,
        "question": question,
        "expected_kind": "eligible" if expected else "abstain",
        "expected_product_ids": sorted(expected),
        "expected_constraints": [
            {"field": field, "operator": operator, "value": value, "unit": unit}
            for field, operator, value, unit in constraints
        ],
        "required_evidence": [
            {"product_id": product_id, "field_id": field, "status": "matched"}
            for product_id in sorted(expected)
            for field in fields
        ],
        "forbidden_product_ids": sorted(set(all_ids) - set(expected)),
        "hard_negative": not expected,
        "evaluation_state": "frozen_unrun",
        "run_count": 0,
    }


def _comparison(
    case_id: str,
    domain: str,
    question: str,
    products: list[str],
    fields: list[str],
    all_ids: list[str],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "domain_id": domain,
        "category": "explicit_comparison",
        "question": question,
        "expected_kind": "referenced",
        "expected_product_ids": sorted(products),
        "expected_constraints": [],
        "required_evidence": [
            {"product_id": product_id, "field_id": field, "status": "matched"}
            for product_id in sorted(products)
            for field in fields
        ],
        "forbidden_product_ids": sorted(set(all_ids) - set(products)),
        "hard_negative": False,
        "evaluation_state": "frozen_unrun",
        "run_count": 0,
    }


def _negative(
    case_id: str,
    domain: str,
    question: str,
    *,
    kind: str,
    category: str,
    constraints: list[tuple[str, str, Any, str | None]] | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "domain_id": domain,
        "category": category,
        "question": question,
        "expected_kind": kind,
        "expected_product_ids": [],
        "expected_constraints": [
            {"field": field, "operator": operator, "value": value, "unit": unit}
            for field, operator, value, unit in (constraints or [])
        ],
        "required_evidence": [],
        "forbidden_product_ids": [],
        "hard_negative": True,
        "evaluation_state": "frozen_unrun",
        "run_count": 0,
    }


def _monitor_cases(ids: list[str]) -> list[dict[str, Any]]:
    facts = [
        ("dell-u2723qe-cn", "请核对中国版 U2723QE 的分辨率和 USB-C 供电瓦数。", ["resolution", "usb_c_power_delivery_w"]),
        ("dell-s2722qc-cn", "S2722QC 中国版的面板类型与 USB-C 视频输入能力分别是什么？", ["panel_type", "usb_c_video"]),
        ("dell-g2724d-cn", "只查 G2724D 中国版：刷新率和是否带 USB-C。", ["refresh_rate_hz", "has_usb_c"]),
        ("dell-u2724d-cn", "U2724D 中国配置的 USB-C 视频与供电规格请给证据。", ["usb_c_video", "usb_c_power_delivery_w"]),
        ("asus-pa279crv-cn", "核验 PA279CRV 中国版的重量和 USB-C 供电。", ["weight_kg", "usb_c_power_delivery_w"]),
        ("asus-pg27aqdm-cn", "PG27AQDM 中国版是不是 OLED，刷新率是多少？", ["is_oled", "refresh_rate_hz"]),
        ("asus-pa27jcv-cn", "PA27JCV 中国版的原生分辨率和机身宽度是多少？", ["resolution", "width_mm"]),
        ("lg-27up850k-w-cn", "请查 27UP850K-W 中国版的 USB-C 视频能力和重量。", ["usb_c_video", "weight_kg"]),
        ("lg-27gs95qe-b-cn", "27GS95QE-B 中国版的尺寸及刷新率是多少？", ["display_size_inch", "refresh_rate_hz"]),
        ("benq-pd2705u-us", "只引用美国版 PD2705U 的地区与 USB-C 供电证据。", ["region", "usb_c_power_delivery_w"]),
        ("benq-pd2725u-ca", "加拿大版 PD2725U 的重量和分辨率请分别核验。", ["weight_kg", "resolution"]),
        ("benq-ex2710u-cn", "EX2710U 中国版的刷新率以及是否支持 USB-C 是什么？", ["refresh_rate_hz", "has_usb_c"]),
    ]
    rows = [_fact(f"v2-9b-mon-{i:03d}", "monitor", q, p, f, ids) for i, (p, q, f) in enumerate(facts, 1)]
    filters = [
        ("只看中国大陆版：27 英寸、4K、USB-C 能传视频且供电不少于 90W。", [("region","eq","CN",None),("display_size_inch","eq",27,"inch"),("resolution","eq","3840x2160",None),("usb_c_video","eq",True,None),("usb_c_power_delivery_w","gte",90,"W")], ["dell-u2723qe-cn","asus-pa279crv-cn","lg-27up850k-w-cn"]),
        ("中国大陆在售配置里，找 OLED 且至少 240Hz 的显示器。", [("region","eq","CN",None),("is_oled","eq",True,None),("refresh_rate_hz","gte",240,"Hz")], ["asus-pg27aqdm-cn","lg-27gs95qe-b-cn"]),
        ("中国版中筛刷新率不低于 144Hz、同时不要 USB-C 接口的型号。", [("region","eq","CN",None),("refresh_rate_hz","gte",144,"Hz"),("has_usb_c","eq",False,None)], ["dell-g2724d-cn","asus-pg27aqdm-cn","lg-27gs95qe-b-cn","benq-ex2710u-cn"]),
        ("桌面只能放宽度 610mm 以内的中国版显示器。", [("region","eq","CN",None),("width_mm","lte",610,"mm")], ["asus-pg27aqdm-cn","lg-27gs95qe-b-cn","benq-ex2710u-cn"]),
        ("中国版、重量最多 6kg，而且 USB-C 必须能传视频。", [("region","eq","CN",None),("weight_kg","lte",6,"kg"),("usb_c_video","eq",True,None)], ["asus-pa279crv-cn","asus-pa27jcv-cn","lg-27up850k-w-cn"]),
        ("中国大陆版里只要 5120×2880 分辨率。", [("region","eq","CN",None),("resolution","eq","5120x2880",None)], ["asus-pa27jcv-cn"]),
        ("找中国版 IPS Black 面板的显示器。", [("region","eq","CN",None),("panel_type","eq","IPS Black",None)], ["dell-u2723qe-cn","dell-u2724d-cn"]),
        ("美国版、27 英寸、4K，并要求 USB-C 供电至少 65W。", [("region","eq","US",None),("display_size_inch","eq",27,"inch"),("resolution","eq","3840x2160",None),("usb_c_power_delivery_w","gte",65,"W")], ["benq-pd2705u-us"]),
    ]
    for offset, (q, c, e) in enumerate(filters, 13):
        rows.append(_filter(f"v2-9b-mon-{offset:03d}", "monitor", q, c, e, all_ids=ids))
    rows.extend([
        _comparison("v2-9b-mon-021", "monitor", "对比 U2723QE 与 U2724D 中国版的 USB-C 视频和供电，不要混型号。", ["dell-u2723qe-cn","dell-u2724d-cn"], ["usb_c_video","usb_c_power_delivery_w"], ids),
        _comparison("v2-9b-mon-022", "monitor", "PA279CRV 和 PA27JCV 中国版在分辨率、重量上有什么差别？", ["asus-pa279crv-cn","asus-pa27jcv-cn"], ["resolution","weight_kg"], ids),
        _comparison("v2-9b-mon-023", "monitor", "比较 PG27AQDM 与 27GS95QE-B 中国版的尺寸和刷新率。", ["asus-pg27aqdm-cn","lg-27gs95qe-b-cn"], ["display_size_inch","refresh_rate_hz"], ids),
        _comparison("v2-9b-mon-024", "monitor", "分别核验美国版 PD2705U 和加拿大版 PD2725U 的地区与 USB-C 供电。", ["benq-pd2705u-us","benq-pd2725u-ca"], ["region","usb_c_power_delivery_w"], ids),
        _negative("v2-9b-mon-025", "monitor", "中国大陆版里找 7680×4320 的 8K 显示器。", kind="abstain", category="no_match", constraints=[("region","eq","CN",None),("resolution","eq","7680x4320",None)]),
        _negative("v2-9b-mon-026", "monitor", "U2724D 中国版必须支持 USB-C 视频并至少供电 90W。", kind="abstain", category="known_violation", constraints=[("usb_c_video","eq",True,None),("usb_c_power_delivery_w","gte",90,"W")]),
        _negative("v2-9b-mon-027", "monitor", "只推荐支持 Windows Hello 人脸识别摄像头的显示器。", kind="abstain", category="unsupported_field"),
        _negative("v2-9b-mon-028", "monitor", "U272 系列的屏幕参数怎么样？", kind="clarify", category="ambiguous_identity"),
        _negative("v2-9b-mon-029", "monitor", "我想要尺寸别太大的显示器。", kind="clarify", category="ambiguous_constraint"),
        _negative("v2-9b-mon-030", "monitor", "刷新率高一点就行，其他没有要求。", kind="clarify", category="ambiguous_constraint"),
    ])
    return rows


def _laptop_cases(ids: list[str]) -> list[dict[str, Any]]:
    facts = [
        ("dell-xps13-9350-usexchcto9350lnl06-us", "核对配置 usexchcto9350lnl06 的屏幕分辨率和内存。", ["resolution","memory_gb"]),
        ("dell-xps13-9350-caexchcto9350lnl02-ca", "caexchcto9350lnl02 的地区和面板类型分别是什么？", ["region","panel_type"]),
        ("dell-xps13-9350-usexcpcto9350lnl04-us", "只查 usexcpcto9350lnl04 的处理器与内存容量。", ["cpu_model","memory_gb"]),
        ("asus-proart-p16-h7606wx-cn", "H7606WX 的显卡型号和显存是多少？", ["gpu_model","gpu_vram_gb"]),
        ("asus-proart-p16-h7606ww-cn", "请给 H7606WW 的 GPU 与显存证据。", ["gpu_model","gpu_vram_gb"]),
        ("asus-proart-p16-h7606wi-cn", "H7606WI 的存储容量和重量请核验。", ["storage_gb","weight_kg"]),
        ("hp-elitebook-840-g11-9g0c0et-il", "9G0C0ET 配置的 CPU 与电池容量是什么？", ["cpu_model","battery_wh"]),
        ("hp-zbook-firefly14-g11-98n14et-il", "98N14ET 的处理器和内存容量请给来源。", ["cpu_model","memory_gb"]),
        ("hp-zbook-power-g9-6b8c1ea-global", "6B8C1EA 的显卡型号及电池容量是多少？", ["gpu_model","battery_wh"]),
        ("lenovo-thinkpad-t14-g5-21ml000fgr-de", "核对 21ML000FGR 的 CPU 和最大内存。", ["cpu_model","max_memory_gb"]),
        ("lenovo-x1-carbon-g13-21nx00k4ph-ph", "21NX00K4PH 的重量与内存请分别核验。", ["weight_kg","memory_gb"]),
        ("lenovo-thinkpad-t14s-g7-21yw0042us-us", "21YW0042US 配置的处理器与硬盘容量是什么？", ["cpu_model","storage_gb"]),
    ]
    rows = [_fact(f"v2-9b-lap-{i:03d}", "laptop", q, p, f, ids) for i, (p, q, f) in enumerate(facts, 1)]
    filters = [
        ("中国版 H7606 中只要 RTX 5090 Laptop GPU 且显存 24GB 的配置。", [("region","eq","CN",None),("gpu_model","eq","GeForce RTX 5090 Laptop GPU",None),("gpu_vram_gb","eq",24,"GB")], ["asus-proart-p16-h7606wx-cn"]),
        ("中国版 H7606 要 4TB 存储，并且显存至少 16GB。", [("region","eq","CN",None),("storage_gb","gte",4096,"GB"),("gpu_vram_gb","gte",16,"GB")], ["asus-proart-p16-h7606wx-cn","asus-proart-p16-h7606ww-cn"]),
        ("美国版 XPS 13：OLED、内存不少于 32GB。", [("region","eq","US",None),("panel_type","eq","OLED",None),("memory_gb","gte",32,"GB")], ["dell-xps13-9350-usexchcto9350lnl06-us"]),
        ("以色列地区、Windows 11 Pro、存储至少 1TB 的笔记本。", [("region","eq","IL",None),("operating_system","eq","Windows 11 Pro",None),("storage_gb","gte",1024,"GB")], ["hp-elitebook-840-g11-9g0c0et-il","hp-zbook-firefly14-g11-98n14et-il"]),
        ("重量不超过 1.2kg 且内存至少 32GB，不限地区。", [("weight_kg","lte",1.2,"kg"),("memory_gb","gte",32,"GB")], ["dell-xps13-9350-usexchcto9350lnl06-us","dell-xps13-9350-caexchcto9350lnl02-ca","lenovo-x1-carbon-g13-21nx00k4ph-ph"]),
        ("要雷电接口，并且电池容量至少 80Wh。", [("thunderbolt","eq",True,None),("battery_wh","gte",80,"Wh")], ["hp-zbook-power-g9-6b8c1ea-global"]),
        ("中国版、USB4、内存至少 64GB。", [("region","eq","CN",None),("usb4","eq",True,None),("memory_gb","gte",64,"GB")], ["asus-proart-p16-h7606wx-cn","asus-proart-p16-h7606ww-cn","asus-proart-p16-h7606wi-cn"]),
        ("美国版且内存至少 24GB、存储至少 512GB。", [("region","eq","US",None),("memory_gb","gte",24,"GB"),("storage_gb","gte",512,"GB")], ["dell-xps13-9350-usexchcto9350lnl06-us","lenovo-thinkpad-t14s-g7-21yw0042us-us"]),
    ]
    for offset, (q, c, e) in enumerate(filters, 13):
        rows.append(_filter(f"v2-9b-lap-{offset:03d}", "laptop", q, c, e, all_ids=ids))
    rows.extend([
        _comparison("v2-9b-lap-021", "laptop", "对比 usexchcto9350lnl06 和 usexcpcto9350lnl04 的 CPU、内存和分辨率。", ["dell-xps13-9350-usexchcto9350lnl06-us","dell-xps13-9350-usexcpcto9350lnl04-us"], ["cpu_model","memory_gb","resolution"], ids),
        _comparison("v2-9b-lap-022", "laptop", "H7606WX 与 H7606WW 的显卡和显存有什么不同？", ["asus-proart-p16-h7606wx-cn","asus-proart-p16-h7606ww-cn"], ["gpu_model","gpu_vram_gb"], ids),
        _comparison("v2-9b-lap-023", "laptop", "分别查 98N14ET 和 6B8C1EA 的 GPU 与内存，不要串配置。", ["hp-zbook-firefly14-g11-98n14et-il","hp-zbook-power-g9-6b8c1ea-global"], ["gpu_model","memory_gb"], ids),
        _comparison("v2-9b-lap-024", "laptop", "比较 21ML000FGR 与 21YW0042US 的地区、CPU 和存储。", ["lenovo-thinkpad-t14-g5-21ml000fgr-de","lenovo-thinkpad-t14s-g7-21yw0042us-us"], ["region","cpu_model","storage_gb"], ids),
        _negative("v2-9b-lap-025", "laptop", "预算一万元以内，推荐一台满足条件的笔记本。", kind="abstain", category="unknown_price", constraints=[("price_cny","lte",10000,"CNY")]),
        _negative("v2-9b-lap-026", "laptop", "H7606WI 必须是 4K OLED 屏幕。", kind="abstain", category="unknown_field", constraints=[("resolution","eq","3840x2400",None),("panel_type","eq","OLED",None)]),
        _negative("v2-9b-lap-027", "laptop", "只要预装 macOS 的笔记本。", kind="abstain", category="no_match", constraints=[("operating_system","eq","macOS",None)]),
        _negative("v2-9b-lap-028", "laptop", "XPS 13 的屏幕怎么样？", kind="clarify", category="ambiguous_identity"),
        _negative("v2-9b-lap-029", "laptop", "H7606 给我高配一点的。", kind="clarify", category="ambiguous_constraint"),
        _negative("v2-9b-lap-030", "laptop", "想要轻一点的笔记本，别的没想好。", kind="clarify", category="ambiguous_constraint"),
    ])
    return rows


def _headphone_cases(ids: list[str]) -> list[dict[str, Any]]:
    facts = [
        ("sony-wh-1000xm5-black-us", "美国版 WH-1000XM5 的总续航和开启降噪后的续航是多少？", ["battery_hours","battery_hours_anc"]),
        ("sony-wh-1000xm5-black-ca", "加拿大版 WH1000XM5-B-CA 的配置号和地区请核验。", ["configuration_id","region"]),
        ("sony-wf-1000xm5-black-us", "WF1000XM5-B-US 的防水等级与续航是多少？", ["water_resistance","battery_hours"]),
        ("sony-inzone-h9-white-us", "WH-G900N-W-US 支持哪些平台，是否带无线接收器？", ["supported_platforms","wireless_dongle"]),
        ("bose-qc-ultra-headphones-2g-black-us", "QCUH2-BLACK-US 是否支持 USB 音频和空间音频？", ["usb_audio","spatial_audio"]),
        ("bose-qc-headphones-2g-black-us", "QC2G-BLACK-US 的重量和续航分别是多少？", ["weight_g","battery_hours"]),
        ("bose-qc-ultra-earbuds-2g-black-us", "QCUE2-BLACK-US 的防水等级与降噪续航请给证据。", ["water_resistance","battery_hours_anc"]),
        ("steelseries-arctis-nova-pro-wireless-ps-us", "NOVA-PRO-WL-PS-B-US 的平台兼容性和配置号是什么？", ["supported_platforms","configuration_id"]),
        ("steelseries-arctis-nova-pro-wireless-xbox-us", "NOVA-PRO-WL-XBOX-B-US 支持的平台与 USB 音频能力。", ["supported_platforms","usb_audio"]),
        ("steelseries-arctis-nova-7p-black-us", "NOVA-7P-WL-B-US 是否有主动降噪，最长续航多久？", ["active_noise_cancellation","battery_hours"]),
        ("logitech-g735-white-us", "G735-WHITE-US 的重量和电池续航是多少？", ["weight_g","battery_hours"]),
        ("logitech-astro-a50x-black-us", "939-002126-US 支持哪些平台，能不能走 USB 音频？", ["supported_platforms","usb_audio"]),
    ]
    rows = [_fact(f"v2-9b-hph-{i:03d}", "headphone", q, p, f, ids) for i, (p, q, f) in enumerate(facts, 1)]
    filters = [
        ("美国版耳机中，必须支持 LDAC。", [("region","eq","US",None),("supported_codecs","contains_all",["LDAC"],None)], ["sony-wh-1000xm5-black-us","sony-wf-1000xm5-black-us"]),
        ("美国版、兼容 PS5，并且要带无线接收器。", [("region","eq","US",None),("supported_platforms","contains_all",["PS5"],None),("wireless_dongle","eq",True,None)], ["sony-inzone-h9-white-us","steelseries-arctis-nova-pro-wireless-ps-us","steelseries-arctis-nova-pro-wireless-xbox-us","steelseries-arctis-nova-7p-black-us","logitech-astro-a50x-black-us"]),
        ("美国版里找兼容 Xbox 且支持 USB 音频的无线耳机。", [("region","eq","US",None),("supported_platforms","contains_all",["Xbox"],None),("usb_audio","eq",True,None)], ["steelseries-arctis-nova-pro-wireless-xbox-us","logitech-astro-a50x-black-us"]),
        ("美国版头戴式，必须有 ANC，最长续航至少 40 小时。", [("region","eq","US",None),("form_factor","eq","over_ear",None),("active_noise_cancellation","eq",True,None),("battery_hours","gte",40,"h")], ["sony-wh-1000xm5-black-us","steelseries-arctis-nova-pro-wireless-ps-us","steelseries-arctis-nova-pro-wireless-xbox-us"]),
        ("美国版真无线入耳式，要 ANC 且达到 IPX4。", [("region","eq","US",None),("form_factor","eq","in_ear_true_wireless",None),("active_noise_cancellation","eq",True,None),("water_resistance","eq","IPX4",None)], ["sony-wf-1000xm5-black-us","bose-qc-ultra-earbuds-2g-black-us"]),
        ("美国版头戴耳机，同时支持 USB 音频和有线连接。", [("region","eq","US",None),("form_factor","eq","over_ear",None),("usb_audio","eq",True,None),("wired_connection","eq",True,None)], ["bose-qc-ultra-headphones-2g-black-us","bose-qc-headphones-2g-black-us","steelseries-arctis-nova-pro-wireless-ps-us","steelseries-arctis-nova-pro-wireless-xbox-us"]),
        ("美国版头戴式 ANC 耳机，重量最多 250g。", [("region","eq","US",None),("form_factor","eq","over_ear",None),("active_noise_cancellation","eq",True,None),("weight_g","lte",250,"g")], ["sony-wh-1000xm5-black-us","bose-qc-headphones-2g-black-us"]),
        ("美国版、支持多设备连接，并且续航至少 50 小时。", [("region","eq","US",None),("multipoint","eq",True,None),("battery_hours","gte",50,"h")], ["logitech-g735-white-us"]),
    ]
    for offset, (q, c, e) in enumerate(filters, 13):
        rows.append(_filter(f"v2-9b-hph-{offset:03d}", "headphone", q, c, e, all_ids=ids))
    rows.extend([
        _comparison("v2-9b-hph-021", "headphone", "比较美国版和加拿大版 WH-1000XM5 的配置号、地区与续航。", ["sony-wh-1000xm5-black-us","sony-wh-1000xm5-black-ca"], ["configuration_id","region","battery_hours"], ids),
        _comparison("v2-9b-hph-022", "headphone", "Bose Ultra 二代头戴与 QC 二代头戴的续航和空间音频有何不同？", ["bose-qc-ultra-headphones-2g-black-us","bose-qc-headphones-2g-black-us"], ["battery_hours","spatial_audio"], ids),
        _comparison("v2-9b-hph-023", "headphone", "对比 Nova Pro Wireless 的 PS 与 Xbox 两个配置支持的平台。", ["steelseries-arctis-nova-pro-wireless-ps-us","steelseries-arctis-nova-pro-wireless-xbox-us"], ["supported_platforms","configuration_id"], ids),
        _comparison("v2-9b-hph-024", "headphone", "WF-1000XM5 与 Bose QC Ultra Earbuds 二代的续航和防水等级。", ["sony-wf-1000xm5-black-us","bose-qc-ultra-earbuds-2g-black-us"], ["battery_hours","water_resistance"], ids),
        _negative("v2-9b-hph-025", "headphone", "美国版真无线入耳式耳机，必须支持 USB 音频。", kind="abstain", category="no_match", constraints=[("region","eq","US",None),("form_factor","eq","in_ear_true_wireless",None),("usb_audio","eq",True,None)]),
        _negative("v2-9b-hph-026", "headphone", "美国版耳机要主动降噪，续航至少 60 小时。", kind="abstain", category="no_match", constraints=[("region","eq","US",None),("active_noise_cancellation","eq",True,None),("battery_hours","gte",60,"h")]),
        _negative("v2-9b-hph-027", "headphone", "价格不超过 2000 元，给我推荐耳机。", kind="abstain", category="unknown_price", constraints=[("price_cny","lte",2000,"CNY")]),
        _negative("v2-9b-hph-028", "headphone", "Sony XM5 戴着舒服吗？", kind="clarify", category="ambiguous_identity"),
        _negative("v2-9b-hph-029", "headphone", "我只想要续航久一点的耳机。", kind="clarify", category="ambiguous_constraint"),
        _negative("v2-9b-hph-030", "headphone", "Nova Pro Wireless 哪个版本适合我？", kind="clarify", category="ambiguous_identity"),
    ])
    return rows


def _online_cases() -> list[dict[str, Any]]:
    rows = [
        ("web-mon-001","monitor","BenQ PD3226G official US 4K 144Hz Thunderbolt 90W","PD3226G","US",["benq.com"],["resolution","refresh_rate_hz","usb_c_power_delivery_w"]),
        ("web-mon-002","monitor","Dell P2725QE official China USB-C display power","P2725QE","CN",["dell.com"],["resolution","usb_c_video","usb_c_power_delivery_w"]),
        ("web-mon-003","monitor","ASUS ProArt PA32UCXR official China specs","PA32UCXR","CN",["asus.com.cn","asus.com"],["resolution","display_size_inch","usb_c_power_delivery_w"]),
        ("web-mon-004","monitor","LG 32GS95UE official China OLED refresh rate","32GS95UE","CN",["lg.com"],["resolution","refresh_rate_hz","is_oled"]),
        ("web-mon-005","monitor","BenQ PD3225U official Canada Thunderbolt power","PD3225U","CA",["benq.com"],["resolution","usb_c_video","usb_c_power_delivery_w"]),
        ("web-lap-001","laptop","ASUS Zenbook S 14 UX5406 official US specs memory battery","UX5406","US",["asus.com"],["resolution","memory_gb","battery_wh","weight_kg"]),
        ("web-lap-002","laptop","Dell XPS 14 9440 official US specs memory display","XPS 14 9440","US",["dell.com"],["resolution","memory_gb","weight_kg"]),
        ("web-lap-003","laptop","HP Spectre x360 14 eu0000 official US specifications","14-eu0000","US",["hp.com"],["resolution","memory_gb","battery_wh"]),
        ("web-lap-004","laptop","Lenovo ThinkPad X1 Carbon Gen 13 official US specifications","X1 Carbon Gen 13","US",["lenovo.com"],["resolution","memory_gb","weight_kg"]),
        ("web-lap-005","laptop","ASUS ROG Zephyrus G14 GA403 official US specs","GA403","US",["asus.com"],["resolution","refresh_rate_hz","memory_gb","battery_wh"]),
        ("web-hph-001","headphone","Apple AirPods Max official Ireland ANC battery spatial audio","AirPods Max","IE",["apple.com"],["active_noise_cancellation","battery_hours","spatial_audio"]),
        ("web-hph-002","headphone","Sony WH-1000XM6 official US specifications","WH-1000XM6","US",["sony.com"],["active_noise_cancellation","battery_hours","weight_g"]),
        ("web-hph-003","headphone","Bose QuietComfort Ultra Earbuds 2nd Gen official Canada","QuietComfort Ultra Earbuds 2nd Gen","CA",["bose.ca","bose.com"],["active_noise_cancellation","battery_hours","water_resistance"]),
        ("web-hph-004","headphone","SteelSeries Arctis Nova Pro Wireless official US Xbox specs","Arctis Nova Pro Wireless Xbox","US",["steelseries.com"],["supported_platforms","usb_audio","battery_hours"]),
        ("web-hph-005","headphone","Logitech ASTRO A50 Gen 5 official US specifications","ASTRO A50 Gen 5","US",["logitechg.com","logitech.com"],["supported_platforms","usb_audio","battery_hours"]),
    ]
    return [
        {
            "case_id": case_id,
            "domain_id": domain,
            "query": query,
            "target_model": model,
            "region": region,
            "allowed_domains": domains,
            "target_fields": fields,
            "expected_safety": {
                "official_domain_only": True,
                "exact_model_required": True,
                "exact_region_required_for_usable": True,
                "lineage_complete_if_evidence": True,
                "trusted_eligible": False,
                "checker_entries": 0,
            },
            "evaluation_state": "frozen_unrun",
            "run_count": 0,
        }
        for case_id, domain, query, model, region, domains, fields in rows
    ]


def main() -> int:
    monitor = json.loads((ROOT / "smartbuy/data/catalog/monitors_v1.json").read_text(encoding="utf-8"))
    laptop = json.loads((ROOT / "smartbuy/product_packs/examples/laptop-v1/pack.json").read_text(encoding="utf-8"))
    headphone = json.loads((ROOT / "smartbuy/product_packs/examples/headphone-v1/pack.json").read_text(encoding="utf-8"))
    ids = {
        "monitor": [item["model_id"] for item in monitor["products"]],
        "laptop": [item["product_id"] for item in laptop["products"]],
        "headphone": [item["product_id"] for item in headphone["products"]],
    }
    rows = _monitor_cases(ids["monitor"]) + _laptop_cases(ids["laptop"]) + _headphone_cases(ids["headphone"])
    online = _online_cases()
    if len(rows) != 90 or any(sum(row["domain_id"] == d for row in rows) != 30 for d in ids):
        raise RuntimeError("trusted evaluation must be 90 cases, 30 per domain")
    if len(online) != 15 or any(sum(row["domain_id"] == d for row in online) != 5 for d in ids):
        raise RuntimeError("online evaluation must be 15 cases, 5 per domain")
    case_ids = [row["case_id"] for row in [*rows, *online]]
    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError("duplicate case_id")
    historical_questions: set[str] = set()
    for path in (ROOT / "smartbuy/eval").glob("*.jsonl"):
        if path.resolve() in {CASES.resolve(), ONLINE_CASES.resolve()}:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and isinstance(item.get("question"), str):
                historical_questions.add(item["question"].strip())
    duplicates = sorted({row["question"] for row in rows} & historical_questions)
    if duplicates:
        raise RuntimeError(f"new trusted questions duplicate historical inputs: {duplicates}")
    _write_jsonl(CASES, rows)
    _write_jsonl(ONLINE_CASES, online)
    manifest = {
        "schema_version": "proofpick-v2-9b-independent-case-freeze-v1",
        "classification": "independently authored pre-run release evaluation",
        "trusted_case_count": len(rows),
        "trusted_domain_counts": {d: sum(row["domain_id"] == d for row in rows) for d in ids},
        "trusted_case_sha256": _sha(CASES),
        "online_case_count": len(online),
        "online_domain_counts": {d: sum(row["domain_id"] == d for row in online) for d in ids},
        "online_case_sha256": _sha(ONLINE_CASES),
        "exact_historical_question_duplicates": 0,
        "first_run_completed": False,
        "gold_source": "frozen governed records, independently read without production evaluator",
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
