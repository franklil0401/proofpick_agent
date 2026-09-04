"""Generate a fresh independent release set for ProofPick RC2.

Gold labels are authored against frozen governed records.  Production intent,
scope, constraint, orchestration, and checker implementations are not imported.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def _fact(case_id: str, domain: str, question: str, product: str, fields: list[str], ids: list[str]) -> dict[str, Any]:
    return {
        "case_id": case_id, "domain_id": domain, "category": "exact_fact", "question": question,
        "expected_kind": "referenced", "expected_product_ids": [product], "expected_constraints": [],
        "required_evidence": [{"product_id": product, "field_id": field, "status": "matched"} for field in fields],
        "forbidden_product_ids": sorted(set(ids) - {product}), "hard_negative": False,
        "evaluation_state": "frozen_unrun", "run_count": 0,
    }


def _filter(
    case_id: str, domain: str, question: str, constraints: list[tuple[str, str, Any, str | None]],
    expected: list[str], ids: list[str], *, category: str = "catalog_filter",
) -> dict[str, Any]:
    fields = [item[0] for item in constraints]
    return {
        "case_id": case_id, "domain_id": domain, "category": category, "question": question,
        "expected_kind": "eligible" if expected else "abstain", "expected_product_ids": sorted(expected),
        "expected_constraints": [
            {"field": field, "operator": operator, "value": value, "unit": unit}
            for field, operator, value, unit in constraints
        ],
        "required_evidence": [
            {"product_id": product, "field_id": field, "status": "matched"}
            for product in sorted(expected) for field in fields
        ],
        "forbidden_product_ids": sorted(set(ids) - set(expected)), "hard_negative": not expected,
        "evaluation_state": "frozen_unrun", "run_count": 0,
    }


def _comparison(case_id: str, domain: str, question: str, products: list[str], fields: list[str], ids: list[str]) -> dict[str, Any]:
    return {
        "case_id": case_id, "domain_id": domain, "category": "explicit_comparison", "question": question,
        "expected_kind": "referenced", "expected_product_ids": sorted(products), "expected_constraints": [],
        "required_evidence": [
            {"product_id": product, "field_id": field, "status": "matched"}
            for product in sorted(products) for field in fields
        ],
        "forbidden_product_ids": sorted(set(ids) - set(products)), "hard_negative": False,
        "evaluation_state": "frozen_unrun", "run_count": 0,
    }


def _negative(
    case_id: str, domain: str, question: str, *, kind: str, category: str,
    constraints: list[tuple[str, str, Any, str | None]] | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id, "domain_id": domain, "category": category, "question": question,
        "expected_kind": kind, "expected_product_ids": [],
        "expected_constraints": [
            {"field": field, "operator": operator, "value": value, "unit": unit}
            for field, operator, value, unit in (constraints or [])
        ],
        "required_evidence": [], "forbidden_product_ids": [], "hard_negative": True,
        "evaluation_state": "frozen_unrun", "run_count": 0,
    }


def _monitor(ids: list[str]) -> list[dict[str, Any]]:
    facts = [
        ("dell-u2723qe-cn", "只核验中国版 U2723QE 的面板类型和机身宽度。", ["panel_type", "width_mm"]),
        ("dell-s2722qc-cn", "S2722QC 中国配置的机身宽度与 USB-C 供电是多少？", ["width_mm", "usb_c_power_delivery_w"]),
        ("dell-g2724d-cn", "请给 G2724D 中国版的分辨率和面板类型证据。", ["resolution", "panel_type"]),
        ("dell-u2724d-cn", "U2724D 中国版刷新率、面板类型分别是什么？", ["refresh_rate_hz", "panel_type"]),
        ("asus-pa279crv-cn", "PA279CRV 中国版的分辨率与支架调节能力是什么？", ["resolution", "stand_adjustment"]),
        ("asus-pg27aqdm-cn", "仅查 PG27AQDM 中国版的分辨率和宽度。", ["resolution", "width_mm"]),
        ("asus-pa27jcv-cn", "PA27JCV 中国版的供电瓦数和面板类型请给来源。", ["usb_c_power_delivery_w", "panel_type"]),
        ("lg-27up850k-w-cn", "核验 27UP850K-W 中国版的分辨率和支架调节。", ["resolution", "stand_adjustment"]),
        ("lg-27gs95qe-b-cn", "27GS95QE-B 中国版是什么面板，机身有多宽？", ["panel_type", "width_mm"]),
        ("benq-ex2710u-cn", "EX2710U 中国版的分辨率和整机重量是多少？", ["resolution", "weight_kg"]),
    ]
    rows = [_fact(f"v2-9d-mon-{i:03d}", "monitor", q, p, f, ids) for i, (p, q, f) in enumerate(facts, 1)]
    filters = [
        ("在中国版 4K 显示器中，机身宽度不能超过 613mm。", [("region","eq","CN",None),("resolution","eq","3840x2160",None),("width_mm","lte",613,"mm")], ["dell-u2723qe-cn","dell-s2722qc-cn","asus-pa279crv-cn","benq-ex2710u-cn"]),
        ("中国版至少 120Hz，同时机身宽度不超过 612mm。", [("region","eq","CN",None),("refresh_rate_hz","gte",120,"Hz"),("width_mm","lte",612,"mm")], ["dell-g2724d-cn","asus-pg27aqdm-cn","lg-27gs95qe-b-cn","benq-ex2710u-cn"]),
        ("中国版、非 OLED、USB-C 可传视频且供电至少 90W。", [("region","eq","CN",None),("is_oled","eq",False,None),("usb_c_video","eq",True,None),("usb_c_power_delivery_w","gte",90,"W")], ["dell-u2723qe-cn","asus-pa279crv-cn","asus-pa27jcv-cn","lg-27up850k-w-cn"]),
        ("中国版 4K 显示器里，重量最多 6kg。", [("region","eq","CN",None),("resolution","eq","3840x2160",None),("weight_kg","lte",6,"kg")], ["asus-pa279crv-cn","lg-27up850k-w-cn"]),
        ("只筛中国版 IPS 面板且 USB-C 能传视频的型号。", [("region","eq","CN",None),("panel_type","eq","IPS",None),("usb_c_video","eq",True,None)], ["dell-s2722qc-cn","asus-pa279crv-cn","asus-pa27jcv-cn","lg-27up850k-w-cn"]),
        ("加拿大版 4K 显示器，USB-C 必须支持视频输入。", [("region","eq","CA",None),("resolution","eq","3840x2160",None),("usb_c_video","eq",True,None)], ["benq-pd2725u-ca"]),
        ("美国版显示器，重量不超过 10kg 且 USB-C 能传视频。", [("region","eq","US",None),("weight_kg","lte",10,"kg"),("usb_c_video","eq",True,None)], ["benq-pd2705u-us"]),
        ("中国版 2560×1440 显示器，刷新率至少 120Hz。", [("region","eq","CN",None),("resolution","eq","2560x1440",None),("refresh_rate_hz","gte",120,"Hz")], ["dell-g2724d-cn","dell-u2724d-cn","asus-pg27aqdm-cn","lg-27gs95qe-b-cn"]),
        ("中国版里不要 USB-C，机身宽度还要在 610mm 以内。", [("region","eq","CN",None),("has_usb_c","eq",False,None),("width_mm","lte",610,"mm")], ["asus-pg27aqdm-cn","lg-27gs95qe-b-cn","benq-ex2710u-cn"]),
        ("中国版 27 英寸显示器，USB-C 供电至少 90W。", [("region","eq","CN",None),("display_size_inch","eq",27,"inch"),("usb_c_power_delivery_w","gte",90,"W")], ["dell-u2723qe-cn","asus-pa279crv-cn","asus-pa27jcv-cn","lg-27up850k-w-cn"]),
    ]
    rows += [_filter(f"v2-9d-mon-{i:03d}", "monitor", q, c, e, ids) for i, (q, c, e) in enumerate(filters, 11)]
    rows += [
        _comparison("v2-9d-mon-021","monitor","对比 U2723QE 和 S2722QC 中国版的宽度、USB-C 供电。",["dell-u2723qe-cn","dell-s2722qc-cn"],["width_mm","usb_c_power_delivery_w"],ids),
        _comparison("v2-9d-mon-022","monitor","G2724D 与 U2724D 中国版的面板和刷新率有何差别？",["dell-g2724d-cn","dell-u2724d-cn"],["panel_type","refresh_rate_hz"],ids),
        _comparison("v2-9d-mon-023","monitor","PA279CRV 和 27UP850K-W 中国版的重量、支架调节分别怎样？",["asus-pa279crv-cn","lg-27up850k-w-cn"],["weight_kg","stand_adjustment"],ids),
        _comparison("v2-9d-mon-024","monitor","PA27JCV 与 EX2710U 中国版的分辨率和 USB-C 能力对比。",["asus-pa27jcv-cn","benq-ex2710u-cn"],["resolution","has_usb_c"],ids),
        _comparison("v2-9d-mon-025","monitor","比较美国版 PD2705U 与加拿大版 PD2725U 的宽度和重量。",["benq-pd2705u-us","benq-pd2725u-ca"],["width_mm","weight_kg"],ids),
        _negative("v2-9d-mon-026","monitor","中国版 4K 显示器，刷新率至少 240Hz。",kind="abstain",category="no_match",constraints=[("region","eq","CN",None),("resolution","eq","3840x2160",None),("refresh_rate_hz","gte",240,"Hz")]),
        _negative("v2-9d-mon-027","monitor","美国版显示器机身宽度必须在 610mm 以内。",kind="abstain",category="no_match",constraints=[("region","eq","US",None),("width_mm","lte",610,"mm")]),
        _negative("v2-9d-mon-028","monitor","ProArt 27 英寸那款屏幕具体怎么样？",kind="clarify",category="ambiguous_identity"),
        _negative("v2-9d-mon-029","monitor","显示器机身窄一点就可以。",kind="clarify",category="ambiguous_constraint"),
        _negative("v2-9d-mon-030","monitor","只推荐自带 KVM 切换器的显示器。",kind="abstain",category="unsupported_field"),
    ]
    return rows


def _laptop(ids: list[str]) -> list[dict[str, Any]]:
    facts = [
        ("dell-xps13-9350-usexchcto9350lnl06-us","美国 OLED 配置 usexchcto9350lnl06 的重量和显卡型号是什么？",["weight_kg","gpu_model"]),
        ("dell-xps13-9350-caexchcto9350lnl02-ca","加拿大配置 caexchcto9350lnl02 的系统与存储容量请核验。",["operating_system","storage_gb"]),
        ("dell-xps13-9350-usexcpcto9350lnl04-us","usexcpcto9350lnl04 的面板类型和分辨率分别是什么？",["panel_type","resolution"]),
        ("asus-proart-p16-h7606wx-cn","H7606WX 的充电器功率和电池容量是多少？",["charger_w","battery_wh"]),
        ("asus-proart-p16-h7606ww-cn","H7606WW 的机身宽度和内存容量请给证据。",["width_mm","memory_gb"]),
        ("asus-proart-p16-h7606wi-cn","H7606WI 的显存与充电器功率分别是多少？",["gpu_vram_gb","charger_w"]),
        ("hp-elitebook-840-g11-9g0c0et-il","9G0C0ET 的重量和充电器功率是什么？",["weight_kg","charger_w"]),
        ("hp-zbook-firefly14-g11-98n14et-il","98N14ET 的屏幕分辨率和雷电接口能力请核验。",["resolution","thunderbolt"]),
        ("hp-zbook-power-g9-6b8c1ea-global","6B8C1EA 的机身宽度及充电器功率是多少？",["width_mm","charger_w"]),
        ("lenovo-x1-carbon-g13-21nx00k4ph-ph","21NX00K4PH 的重量与保修期请给来源。",["weight_kg","warranty"]),
    ]
    rows = [_fact(f"v2-9d-lap-{i:03d}", "laptop", q, p, f, ids) for i, (p, q, f) in enumerate(facts, 1)]
    filters = [
        ("中国版 H7606 中，充电器功率至少 220W。",[("region","eq","CN",None),("charger_w","gte",220,"W")],["asus-proart-p16-h7606wx-cn","asus-proart-p16-h7606ww-cn"]),
        ("中国版 H7606，重量不超过 1.9kg 且内存 64GB。",[("region","eq","CN",None),("weight_kg","lte",1.9,"kg"),("memory_gb","eq",64,"GB")],["asus-proart-p16-h7606wi-cn"]),
        ("美国版 XPS 13，要 2880×1800 屏幕和 32GB 内存。",[("region","eq","US",None),("resolution","eq","2880x1800",None),("memory_gb","eq",32,"GB")],["dell-xps13-9350-usexchcto9350lnl06-us"]),
        ("美国版、Windows 11 Pro、内存至少 16GB。",[("region","eq","US",None),("operating_system","eq","Windows 11 Pro",None),("memory_gb","gte",16,"GB")],["dell-xps13-9350-usexcpcto9350lnl04-us","lenovo-thinkpad-t14s-g7-21yw0042us-us"]),
        ("以色列版 14 英寸笔记本，必须支持雷电接口。",[("region","eq","IL",None),("display_size_inch","eq",14,"inch"),("thunderbolt","eq",True,None)],["hp-elitebook-840-g11-9g0c0et-il","hp-zbook-firefly14-g11-98n14et-il"]),
        ("全球版、电池至少 80Wh、显存至少 8GB。",[("region","eq","GLOBAL",None),("battery_wh","gte",80,"Wh"),("gpu_vram_gb","gte",8,"GB")],["hp-zbook-power-g9-6b8c1ea-global"]),
        ("德国版、内存可更换并支持雷电接口。",[("region","eq","DE",None),("memory_soldered","eq",False,None),("thunderbolt","eq",True,None)],["lenovo-thinkpad-t14-g5-21ml000fgr-de"]),
        ("存储至少 2TB 且内存 64GB 的笔记本。",[("storage_gb","gte",2048,"GB"),("memory_gb","eq",64,"GB")],["asus-proart-p16-h7606wx-cn","asus-proart-p16-h7606ww-cn","asus-proart-p16-h7606wi-cn"]),
        ("重量最多 1.2kg，同时预装 Windows 11 Home。",[("weight_kg","lte",1.2,"kg"),("operating_system","eq","Windows 11 Home",None)],["dell-xps13-9350-usexchcto9350lnl06-us","dell-xps13-9350-caexchcto9350lnl02-ca"]),
        ("充电器不超过 65W 且支持雷电接口。",[("charger_w","lte",65,"W"),("thunderbolt","eq",True,None)],["hp-elitebook-840-g11-9g0c0et-il","lenovo-thinkpad-t14-g5-21ml000fgr-de"]),
    ]
    rows += [_filter(f"v2-9d-lap-{i:03d}", "laptop", q, c, e, ids) for i, (q, c, e) in enumerate(filters, 11)]
    rows += [
        _comparison("v2-9d-lap-021","laptop","对比 XPS 13 美国和加拿大 OLED 配置的地区、配置号。",["dell-xps13-9350-usexchcto9350lnl06-us","dell-xps13-9350-caexchcto9350lnl02-ca"],["region","configuration_id"],ids),
        _comparison("v2-9d-lap-022","laptop","美国版 XPS 13 OLED 与 FHD+ 配置的系统、分辨率和内存对比。",["dell-xps13-9350-usexchcto9350lnl06-us","dell-xps13-9350-usexcpcto9350lnl04-us"],["operating_system","resolution","memory_gb"],ids),
        _comparison("v2-9d-lap-023","laptop","H7606WW 和 H7606WI 的 GPU、存储和重量有什么差异？",["asus-proart-p16-h7606ww-cn","asus-proart-p16-h7606wi-cn"],["gpu_model","storage_gb","weight_kg"],ids),
        _comparison("v2-9d-lap-024","laptop","9G0C0ET 与 98N14ET 的处理器和显卡对比。",["hp-elitebook-840-g11-9g0c0et-il","hp-zbook-firefly14-g11-98n14et-il"],["cpu_model","gpu_model"],ids),
        _comparison("v2-9d-lap-025","laptop","21ML000FGR 和 21YW0042US 的地区、CPU 与内存分别是什么？",["lenovo-thinkpad-t14-g5-21ml000fgr-de","lenovo-thinkpad-t14s-g7-21yw0042us-us"],["region","cpu_model","memory_gb"],ids),
        _negative("v2-9d-lap-026","laptop","中国版 H7606，内存至少 128GB。",kind="abstain",category="no_match",constraints=[("region","eq","CN",None),("memory_gb","gte",128,"GB")]),
        _negative("v2-9d-lap-027","laptop","只推荐重量不超过 0.9kg 的笔记本。",kind="abstain",category="no_match",constraints=[("weight_kg","lte",0.9,"kg")]),
        _negative("v2-9d-lap-028","laptop","XPS 13 OLED 那一款的续航怎么样？",kind="clarify",category="ambiguous_identity"),
        _negative("v2-9d-lap-029","laptop","给我一台性能强一点的笔记本。",kind="clarify",category="ambiguous_constraint"),
        _negative("v2-9d-lap-030","laptop","只要预装 Fedora Linux 的笔记本。",kind="abstain",category="no_match",constraints=[("operating_system","eq","Fedora Linux",None)]),
    ]
    return rows


def _headphone(ids: list[str]) -> list[dict[str, Any]]:
    facts = [
        ("sony-wh-1000xm5-black-us","美国版 WH-1000XM5 的重量与支持的编解码器是什么？",["weight_g","supported_codecs"]),
        ("sony-wh-1000xm5-black-ca","加拿大版 WH1000XM5-B-CA 的蓝牙版本和 USB 音频能力请核验。",["bluetooth_version","usb_audio"]),
        ("sony-wf-1000xm5-black-us","WF1000XM5-B-US 支持哪些编解码器，开启降噪续航多久？",["supported_codecs","battery_hours_anc"]),
        ("sony-inzone-h9-white-us","WH-G900N-W-US 的重量和多设备连接能力是什么？",["weight_g","multipoint"]),
        ("bose-qc-ultra-headphones-2g-black-us","QCUH2-BLACK-US 的蓝牙版本与重量是多少？",["bluetooth_version","weight_g"]),
        ("bose-qc-headphones-2g-black-us","QC2G-BLACK-US 是否支持空间音频和 USB 音频？",["spatial_audio","usb_audio"]),
        ("bose-qc-ultra-earbuds-2g-black-us","QCUE2-BLACK-US 的整机和降噪续航分别是多少？",["battery_hours","battery_hours_anc"]),
        ("steelseries-arctis-nova-pro-wireless-ps-us","NOVA-PRO-WL-PS-B-US 的重量和降噪能力请给证据。",["weight_g","active_noise_cancellation"]),
        ("steelseries-arctis-nova-pro-wireless-xbox-us","NOVA-PRO-WL-XBOX-B-US 是否支持有线连接与无线接收器？",["wired_connection","wireless_dongle"]),
        ("steelseries-arctis-nova-7p-black-us","NOVA-7P-WL-B-US 的重量和支持平台是什么？",["weight_g","supported_platforms"]),
    ]
    rows = [_fact(f"v2-9d-hph-{i:03d}", "headphone", q, p, f, ids) for i, (p, q, f) in enumerate(facts, 1)]
    filters = [
        ("美国版头戴式耳机，蓝牙版本至少 5.4。",[("region","eq","US",None),("form_factor","eq","over_ear",None),("bluetooth_version","gte",5.4,None)],["bose-qc-ultra-headphones-2g-black-us","bose-qc-headphones-2g-black-us"]),
        ("美国版头戴耳机，重量最多 275g 且支持有线连接。",[("region","eq","US",None),("form_factor","eq","over_ear",None),("weight_g","lte",275,"g"),("wired_connection","eq",True,None)],["sony-wh-1000xm5-black-us","bose-qc-ultra-headphones-2g-black-us","bose-qc-headphones-2g-black-us","logitech-g735-white-us"]),
        ("美国版、带无线接收器，续航至少 40 小时。",[("region","eq","US",None),("wireless_dongle","eq",True,None),("battery_hours","gte",40,"h")],["steelseries-arctis-nova-pro-wireless-ps-us","steelseries-arctis-nova-pro-wireless-xbox-us","logitech-g735-white-us"]),
        ("美国版、兼容 PS5、必须有主动降噪。",[("region","eq","US",None),("supported_platforms","contains_all",["PS5"],None),("active_noise_cancellation","eq",True,None)],["sony-inzone-h9-white-us","steelseries-arctis-nova-pro-wireless-ps-us","steelseries-arctis-nova-pro-wireless-xbox-us"]),
        ("美国版、兼容 Xbox 且带无线接收器。",[("region","eq","US",None),("supported_platforms","contains_all",["Xbox"],None),("wireless_dongle","eq",True,None)],["steelseries-arctis-nova-pro-wireless-xbox-us","logitech-astro-a50x-black-us"]),
        ("美国版真无线入耳式，并且支持空间音频。",[("region","eq","US",None),("form_factor","eq","in_ear_true_wireless",None),("spatial_audio","eq",True,None)],["sony-wf-1000xm5-black-us","bose-qc-ultra-earbuds-2g-black-us"]),
        ("加拿大版耳机，必须支持 LDAC。",[("region","eq","CA",None),("supported_codecs","contains_all",["LDAC"],None)],["sony-wh-1000xm5-black-ca"]),
        ("美国版、支持 USB 音频和空间音频。",[("region","eq","US",None),("usb_audio","eq",True,None),("spatial_audio","eq",True,None)],["bose-qc-ultra-headphones-2g-black-us","steelseries-arctis-nova-pro-wireless-ps-us","steelseries-arctis-nova-pro-wireless-xbox-us","logitech-astro-a50x-black-us"]),
        ("美国版主动降噪耳机，重量不超过 265g。",[("region","eq","US",None),("active_noise_cancellation","eq",True,None),("weight_g","lte",265,"g")],["sony-wh-1000xm5-black-us","sony-wf-1000xm5-black-us","bose-qc-ultra-headphones-2g-black-us","bose-qc-headphones-2g-black-us","bose-qc-ultra-earbuds-2g-black-us"]),
        ("美国版、不带主动降噪但有无线接收器。",[("region","eq","US",None),("active_noise_cancellation","eq",False,None),("wireless_dongle","eq",True,None)],["steelseries-arctis-nova-7p-black-us","logitech-g735-white-us","logitech-astro-a50x-black-us"]),
    ]
    rows += [_filter(f"v2-9d-hph-{i:03d}", "headphone", q, c, e, ids) for i, (q, c, e) in enumerate(filters, 11)]
    rows += [
        _comparison("v2-9d-hph-021","headphone","比较 WH-1000XM5 美国版与加拿大版的编解码器和重量。",["sony-wh-1000xm5-black-us","sony-wh-1000xm5-black-ca"],["supported_codecs","weight_g"],ids),
        _comparison("v2-9d-hph-022","headphone","WH-1000XM5 与 WF-1000XM5 美国版的形态和重量差多少？",["sony-wh-1000xm5-black-us","sony-wf-1000xm5-black-us"],["form_factor","weight_g"],ids),
        _comparison("v2-9d-hph-023","headphone","Bose Ultra 二代头戴和耳塞的形态、续航对比。",["bose-qc-ultra-headphones-2g-black-us","bose-qc-ultra-earbuds-2g-black-us"],["form_factor","battery_hours"],ids),
        _comparison("v2-9d-hph-024","headphone","Nova 7P 与 Nova Pro Wireless PS 版的降噪和续航有何不同？",["steelseries-arctis-nova-7p-black-us","steelseries-arctis-nova-pro-wireless-ps-us"],["active_noise_cancellation","battery_hours"],ids),
        _comparison("v2-9d-hph-025","headphone","G735 与 ASTRO A50 X 的平台、续航和 USB 音频对比。",["logitech-g735-white-us","logitech-astro-a50x-black-us"],["supported_platforms","battery_hours","usb_audio"],ids),
        _negative("v2-9d-hph-026","headphone","美国版头戴降噪耳机，续航至少 50 小时。",kind="abstain",category="no_match",constraints=[("region","eq","US",None),("form_factor","eq","over_ear",None),("active_noise_cancellation","eq",True,None),("battery_hours","gte",50,"h")]),
        _negative("v2-9d-hph-027","headphone","美国版真无线入耳式耳机，必须带 2.4G 接收器。",kind="abstain",category="no_match",constraints=[("region","eq","US",None),("form_factor","eq","in_ear_true_wireless",None),("wireless_dongle","eq",True,None)]),
        _negative("v2-9d-hph-028","headphone","Bose QC Ultra 那款到底有哪些参数？",kind="clarify",category="ambiguous_identity"),
        _negative("v2-9d-hph-029","headphone","我想要通话好一点的耳机。",kind="clarify",category="ambiguous_constraint"),
        _negative("v2-9d-hph-030","headphone","只推荐支持心率监测的耳机。",kind="abstain",category="unsupported_field"),
    ]
    return rows


def _online() -> list[dict[str, Any]]:
    definitions = [
        ("web2-mon-001","monitor","Dell Alienware AW3225QF official US resolution refresh OLED","AW3225QF","US",["dell.com"],["resolution","refresh_rate_hz","is_oled"]),
        ("web2-mon-002","monitor","ASUS ProArt PA32QCV official US resolution size USB-C power","PA32QCV","US",["asus.com"],["resolution","display_size_inch","usb_c_power_delivery_w"]),
        ("web2-mon-003","monitor","LG 32UQ850V-W official US resolution panel USB-C power","32UQ850V-W","US",["lg.com"],["resolution","panel_type","usb_c_power_delivery_w"]),
        ("web2-mon-004","monitor","BenQ RD280U official US resolution size USB-C power","RD280U","US",["benq.com"],["resolution","display_size_inch","usb_c_power_delivery_w"]),
        ("web2-mon-005","monitor","Sony INZONE M9 II SDM-27U9M2 official US resolution refresh panel","SDM-27U9M2","US",["sony.com"],["resolution","refresh_rate_hz","panel_type"]),
        ("web2-lap-001","laptop","ASUS Zenbook A14 UX3407 official US memory storage USB4","UX3407","US",["asus.com"],["memory_gb","storage_gb","usb4"]),
        ("web2-lap-002","laptop","Dell Pro Max 16 Premium MA16250 official US memory GPU battery","MA16250","US",["dell.com"],["memory_gb","gpu_model","battery_wh"]),
        ("web2-lap-003","laptop","HP OmniBook Ultra Flip 14 fh0000 official US display memory battery","14-fh0000","US",["hp.com"],["resolution","memory_gb","battery_wh"]),
        ("web2-lap-004","laptop","Lenovo Yoga Pro 9i Aura Edition 16IAH10 official US display memory weight","16IAH10","US",["lenovo.com"],["resolution","memory_gb","weight_kg"]),
        ("web2-lap-005","laptop","Microsoft Surface Laptop 13.8 official US display memory weight","Surface Laptop 13.8","US",["microsoft.com"],["resolution","memory_gb","weight_kg"]),
        ("web2-hph-001","headphone","Sony INZONE H9 II WH-G910N official US battery Bluetooth weight","WH-G910N","US",["sony.com"],["battery_hours","bluetooth_version","weight_g"]),
        ("web2-hph-002","headphone","Bose QuietComfort Ultra Headphones 2nd Gen official US battery Bluetooth ANC","QuietComfort Ultra Headphones 2nd Gen","US",["bose.com"],["battery_hours","bluetooth_version","active_noise_cancellation"]),
        ("web2-hph-003","headphone","Logitech G522 LIGHTSPEED official US battery wireless dongle weight","G522","US",["logitechg.com","logitech.com"],["battery_hours","wireless_dongle","weight_g"]),
        ("web2-hph-004","headphone","SteelSeries Arctis Nova Elite official US battery USB audio platforms","Arctis Nova Elite","US",["steelseries.com"],["battery_hours","usb_audio","supported_platforms"]),
        ("web2-hph-005","headphone","Apple AirPods Pro 3 official Ireland battery ANC water resistance","AirPods Pro 3","IE",["apple.com"],["battery_hours_anc","active_noise_cancellation","water_resistance"]),
    ]
    safety = {
        "official_domain_only": True, "exact_model_required": True,
        "exact_region_required_for_usable": True, "lineage_complete_if_evidence": True,
        "trusted_eligible": False, "checker_entries": 0,
    }
    return [
        {
            "case_id": case_id, "domain_id": domain, "query": query, "target_model": model,
            "region": region, "allowed_domains": domains, "target_fields": fields,
            "expected_safety": safety, "evaluation_state": "frozen_unrun", "run_count": 0,
        }
        for case_id, domain, query, model, region, domains, fields in definitions
    ]


def _questions(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {json.loads(line)["question"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def main() -> int:
    monitor = json.loads((ROOT / "smartbuy/data/catalog/monitors_v1.json").read_text(encoding="utf-8"))
    laptop = json.loads((ROOT / "smartbuy/product_packs/examples/laptop-v1/pack.json").read_text(encoding="utf-8"))
    headphone = json.loads((ROOT / "smartbuy/product_packs/examples/headphone-v1/pack.json").read_text(encoding="utf-8"))
    ids = {
        "monitor": [row["model_id"] for row in monitor["products"]],
        "laptop": [row["product_id"] for row in laptop["products"]],
        "headphone": [row["product_id"] for row in headphone["products"]],
    }
    trusted = [*_monitor(ids["monitor"]), *_laptop(ids["laptop"]), *_headphone(ids["headphone"])]
    online = _online()
    if len(trusted) != 90 or len(online) != 15 or len({row["case_id"] for row in trusted}) != 90:
        raise RuntimeError("case cardinality or IDs are invalid")
    historical = _questions(ROOT / "smartbuy/eval/v2_9b_independent/trusted_cases.jsonl")
    duplicates = sorted({row["question"] for row in trusted} & historical)
    if duplicates:
        raise RuntimeError(f"historical question duplicates: {duplicates}")
    _write_jsonl(HERE / "trusted_cases.jsonl", trusted)
    _write_jsonl(HERE / "online_cases.jsonl", online)
    manifest = {
        "schema_version": "proofpick-v2-9d-independent-case-freeze-v1",
        "classification": "independently authored pre-run RC2 release evaluation",
        "trusted_case_count": len(trusted),
        "trusted_domain_counts": {domain: sum(row["domain_id"] == domain for row in trusted) for domain in ids},
        "trusted_case_sha256": _sha(HERE / "trusted_cases.jsonl"),
        "online_case_count": len(online),
        "online_domain_counts": {domain: sum(row["domain_id"] == domain for row in online) for domain in ids},
        "online_case_sha256": _sha(HERE / "online_cases.jsonl"),
        "exact_historical_question_duplicates": 0,
        "first_run_completed": False,
        "gold_source": "frozen governed records, independently read without production evaluator",
    }
    (HERE / "case_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
