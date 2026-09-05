"""Independent, data-only gold construction. No Agent/Checker/Parser imports."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def canonical(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        return sorted((canonical(x) for x in value), key=str)
    return str(value).casefold().replace("×", "x")


def matches(actual, operator, value):
    if actual is None:
        return False
    a, b = canonical(actual), canonical(value)
    if operator == "eq":
        return a == b
    if operator == "lte":
        return a <= b
    if operator == "gte":
        return a >= b
    if operator == "contains_all":
        return set(b).issubset(set(a))
    if operator == "not_in":
        return a not in b
    raise ValueError(operator)


def read_catalog():
    catalog = {}
    db = sqlite3.connect("file:C:/ppv2rc3evalrun/monitor/smartbuy_monitors_v1.sqlite?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    sources = {x["source_id"]: dict(x) for x in db.execute("select * from source_records")}
    evidence = [dict(x) for x in db.execute("select * from evidence_records")]
    mon = []
    for row in db.execute("select * from products"):
        p = dict(row)
        facts = dict(p)
        for key in ["is_oled", "has_usb_c", "usb_c_video"]:
            facts[key] = None if facts[key] is None else bool(facts[key])
        refs = []
        for e in evidence:
            if e["model_id"] != p["model_id"]:
                continue
            s = sources[e["source_id"]]
            value = json.loads(e["normalized_value"])
            refs.append({"id": e["evidence_id"], "source_id": e["source_id"], "field": e["normalized_field"],
                         "value": value, "region": s["region"], "url": s["url"], "official": bool(s["is_official"]),
                         "conflict_group": e["conflict_group"]})
        mon.append({"id": p["model_id"], "name": p["model_name"], "region": p["region"],
                    "configuration": p["model_id"], "facts": facts, "evidence": refs})
    db.close()
    catalog["monitor"] = mon
    for domain in ["laptop", "headphone"]:
        raw = json.loads((ROOT / f"smartbuy/product_packs/examples/{domain}-v1/pack.json").read_text(encoding="utf8"))
        sources = {s["source_id"]: s for s in raw["sources"]}
        products = []
        for p in raw["products"]:
            facts = {k: v["value"] for k, v in p["attributes"].items()}
            facts.update(product_id=p["product_id"], brand=p["brand"], region=p["market"], model_name=p["canonical_name"])
            refs = []
            for e in raw["evidence"]:
                if e["product_id"] != p["product_id"]:
                    continue
                s = sources[e["source_id"]]
                refs.append({"id": e["evidence_id"], "source_id": e["source_id"], "field": e["field_id"],
                             "value": e["normalized_value"], "region": e["market"], "url": s["uri"],
                             "official": s["is_official"], "conflict_group": e.get("conflict_group")})
            products.append({"id": p["product_id"], "name": p["canonical_name"], "region": p["market"],
                             "configuration": p["variant_key"], "facts": facts, "evidence": refs})
        catalog[domain] = products
    return catalog


def reliable(p, field):
    value = p["facts"].get(field)
    refs = [e for e in p["evidence"] if e["field"] == field and e["region"] == p["region"]]
    conflict = len({json.dumps(canonical(e["value"]), sort_keys=True) for e in refs if e["value"] is not None}) > 1
    return value is not None and not conflict and any(e["official"] and canonical(e["value"]) == canonical(value) for e in refs)


def create():
    catalog = read_catalog()
    cases = []
    labels = {
        "monitor": [("width_mm", "机身宽度"), ("refresh_rate_hz", "刷新率"), ("resolution", "分辨率"),
                    ("display_size_inch", "屏幕尺寸"), ("usb_c_video", "USB-C视频输入能力"), ("is_oled", "是否OLED")],
        "laptop": [("memory_gb", "内存容量"), ("storage_gb", "SSD容量"), ("cpu_model", "处理器型号"),
                   ("gpu_model", "显卡型号"), ("memory_slots", "内存插槽数量"), ("usb_c", "USB-C接口")],
        "headphone": [("weight_g", "重量"), ("bluetooth", "蓝牙连接"), ("active_noise_cancellation", "主动降噪"),
                      ("battery_hours", "最长续航"), ("wired_connection", "有线音频连接"), ("microphone", "麦克风")],
    }
    nouns = {"monitor": "显示器", "laptop": "笔记本", "headphone": "耳机"}

    def add(domain, kind, query, ids=None, fields=None, constraints=None, negative=None):
        products = catalog[domain]
        ids = ids or []
        fields = fields or []
        constraints = constraints or []
        if kind == "filter":
            ids = [p["id"] for p in products if all(reliable(p, c[0]) and matches(p["facts"].get(c[0]), c[1], c[2]) for c in constraints)]
            assert ids, (domain, query)
        gold_facts = []
        for p in products:
            if p["id"] not in ids:
                continue
            for f in fields or [c[0] for c in constraints]:
                refs = [e for e in p["evidence"] if e["field"] == f and e["region"] == p["region"]]
                gold_facts.append({"product_id": p["id"], "field": f, "value": p["facts"].get(f),
                                   "known": reliable(p, f), "evidence_ids": [e["id"] for e in refs]})
        idx = sum(x["domain"] == domain for x in cases) + 1
        cases.append({"case_id": f"rc3i-{domain}-{idx:03d}", "domain": domain, "kind": kind, "query": query,
                      "gold": {"allowed_ids": ids, "fields": fields, "constraints": constraints,
                               "negative": negative, "facts": gold_facts}})

    for domain, products in catalog.items():
        # Deliberately combine pairs of facts, rather than quote existing eval prompts.
        for i, p in enumerate(products[:10]):
            known = [(f, label) for f, label in labels[domain] if reliable(p, f)]
            assert len(known) >= 2
            a, b = known[i % len(known)], known[(i + 2) % len(known)]
            if a == b:
                b = known[(i + 1) % len(known)]
            ref = p["id"] if i % 2 else f"{p['name']}（{p['region']}地区；配置标识 {p['configuration']}）"
            add(domain, "fact", f"请做资料核对：{ref}的{a[1]}和{b[1]}各是什么？分别附上证据，不用给购买建议。",
                [p["id"]], [a[0], b[0]])

    filters = {
        "monitor": [
            ("刷新率至少144Hz，机身宽度最多610毫米", [("refresh_rate_hz", "gte", 144), ("width_mm", "lte", 610)]),
            ("尺寸正好27英寸，必须支持USB-C视频输入", [("display_size_inch", "eq", 27), ("usb_c_video", "eq", True)]),
            ("不要OLED，刷新率至少120Hz", [("is_oled", "eq", False), ("refresh_rate_hz", "gte", 120)]),
            ("USB-C供电至少90W，宽度最多613毫米", [("usb_c_power_delivery_w", "gte", 90), ("width_mm", "lte", 613)]),
            ("要OLED，机身宽度最多605毫米", [("is_oled", "eq", True), ("width_mm", "lte", 605)]),
            ("刷新率至少165Hz，尺寸最多27英寸", [("refresh_rate_hz", "gte", 165), ("display_size_inch", "lte", 27)]),
            ("分辨率必须为5120x2880，USB-C供电至少90W", [("resolution", "eq", "5120x2880"), ("usb_c_power_delivery_w", "gte", 90)]),
            ("宽度最多615毫米，USB-C供电至少96W", [("width_mm", "lte", 615), ("usb_c_power_delivery_w", "gte", 96)]),
            ("分辨率必须为3840x2160，刷新率至少100Hz", [("resolution", "eq", "3840x2160"), ("refresh_rate_hz", "gte", 100)]),
            ("没有USB-C接口也可以，但必须是OLED且刷新率至少240Hz", [("is_oled", "eq", True), ("refresh_rate_hz", "gte", 240)]),
        ],
        "laptop": [
            ("内存至少24GB，SSD至少1024GB", [("memory_gb", "gte", 24), ("storage_gb", "gte", 1024)]),
            ("内存至少32GB，重量最多1.5kg", [("memory_gb", "gte", 32), ("weight_kg", "lte", 1.5)]),
            ("显存至少16GB，电池至少85Wh", [("gpu_vram_gb", "gte", 16), ("battery_wh", "gte", 85)]),
            ("内存插槽至少2个，重量最多2kg", [("memory_slots", "gte", 2), ("weight_kg", "lte", 2)]),
            ("内存至少64GB，SSD至少4096GB", [("memory_gb", "gte", 64), ("storage_gb", "gte", 4096)]),
            ("重量最多1.2kg，内存至少24GB", [("weight_kg", "lte", 1.2), ("memory_gb", "gte", 24)]),
            ("必须有HDMI，SSD至少2048GB", [("hdmi", "eq", True), ("storage_gb", "gte", 2048)]),
            ("内存必须16GB，SSD至少1024GB", [("memory_gb", "eq", 16), ("storage_gb", "gte", 1024)]),
            ("内存至少32GB，电池至少80Wh", [("memory_gb", "gte", 32), ("battery_wh", "gte", 80)]),
            ("必须支持USB4，显存至少8GB", [("usb4", "eq", True), ("gpu_vram_gb", "gte", 8)]),
        ],
        "headphone": [
            ("重量最多265克，必须支持有线连接", [("weight_g", "lte", 265), ("wired_connection", "eq", True)]),
            ("必须主动降噪，重量最多8克", [("active_noise_cancellation", "eq", True), ("weight_g", "lte", 8)]),
            ("必须支持USB音频，重量最多270克", [("usb_audio", "eq", True), ("weight_g", "lte", 270)]),
            ("必须兼容PS5，重量最多340克", [("supported_platforms", "contains_all", ["PS5"]), ("weight_g", "lte", 340)]),
            ("必须支持LDAC，蓝牙版本至少5.3", [("supported_codecs", "contains_all", ["LDAC"]), ("bluetooth_version", "gte", 5.3)]),
            ("必须同时支持Xbox和PS5，重量最多350克", [("supported_platforms", "contains_all", ["Xbox", "PS5"]), ("weight_g", "lte", 350)]),
            ("重量最多280克，最长续航至少24小时", [("weight_g", "lte", 280), ("battery_hours", "gte", 24)]),
            ("必须支持多点连接，重量最多255克", [("multipoint", "eq", True), ("weight_g", "lte", 255)]),
            ("必须有2.4G接收器，重量最多330克", [("wireless_dongle", "eq", True), ("weight_g", "lte", 330)]),
            ("必须支持主动降噪，蓝牙版本至少5.4", [("active_noise_cancellation", "eq", True), ("bluetooth_version", "gte", 5.4)]),
        ],
    }
    for domain, rows in filters.items():
        for text, cs in rows:
            add(domain, "filter", f"请从已收录的{nouns[domain]}中挑选：{text}。不限制地区，保持各配置独立，给出符合条件的选择及依据。", constraints=cs)
        products = catalog[domain]
        for i, (ai, bi) in enumerate([(0, 2), (3, 5), (6, 8), (1, 10), (7, 11)]):
            a, b = products[ai], products[bi]
            known = [(f, label) for f, label in labels[domain] if reliable(a, f) and reliable(b, f)]
            assert len(known) >= 2
            pair = [known[i % len(known)], known[(i + 1) % len(known)]]
            add(domain, "comparison", f"把 {a['id']} 与 {b['id']} 放在一起比较，只核对{pair[0][1]}、{pair[1][1]}，逐个列证据；这是参数对照，不要把对象当作推荐商品。",
                [a["id"], b["id"]], [x[0] for x in pair])

    negatives = {
        "monitor": [
            ("准备买显示器，宽度不能太大。请先问清楚具体能放多宽，再开始筛选。", "clarify", [], []),
            ("我要求显示器具有经过认证的血糖测量功能，必须满足才推荐。", "unsupported", [], []),
            ("查询 dell-u2724d-cn 的机身宽度；只接受此配置的资料，没有记录就说未知。", "unknown", ["dell-u2724d-cn"], ["width_mm"]),
            ("只查 benq-pd2705u-us 的USB-C供电。不同来源若有不同值请一起保留，别直接判定为65W并推荐。", "conflict", ["benq-pd2705u-us"], ["usb_c_power_delivery_w"]),
            ("我要32英寸且刷新率至少500Hz的显示器，只能从本地数据中选；不存在就明确告知。", "no_match", [], []),
        ],
        "laptop": [
            ("想选一台笔记本，重量必须很轻。你先问清我的重量上限，确认前不要查询商品。", "clarify", [], []),
            ("我要笔记本可以做医学级血氧监测，这是必须条件；不支持此字段就说明。", "unsupported", [], []),
            ("请查 lenovo-x1-carbon-g13-21nx00k4ph-ph 的屏幕尺寸，没证据就不要用同系列配置补上。", "unknown", ["lenovo-x1-carbon-g13-21nx00k4ph-ph"], ["display_size_inch"]),
            ("预算5000元以内，给我本地笔记本的购买建议；没有价格记录的配置不能说符合预算。", "no_match", [], []),
            ("选购笔记本需要内存至少128GB、SSD至少8192GB，严格检查现有库，不存在就别推荐。", "no_match", [], []),
        ],
        "headphone": [
            ("耳机延迟必须很低。先问我可接受的毫秒上限，别现在就搜索和推荐。", "clarify", [], []),
            ("耳机必须可以测量血糖，只有证据证明了该功能才能推荐，否则解释不能支持。", "unsupported", [], []),
            ("请核对 logitech-astro-a50x-black-us 的实测延迟是多少毫秒，没有测量记录就标未知。", "unknown", ["logitech-astro-a50x-black-us"], ["measured_latency_ms"]),
            ("在本地耳机库找预算600元以内的产品，不能根据常识猜价格，价格未知的别列为符合。", "no_match", [], []),
            ("想买重量最多1克且续航至少100小时的耳机，只依据已治理数据，不要放宽要求。", "no_match", [], []),
        ],
    }
    for domain, rows in negatives.items():
        for q, neg, ids, fs in rows:
            add(domain, "negative", q, ids, fs, negative=neg)
    cases.sort(key=lambda x: (list(catalog).index(x["domain"]), x["case_id"]))
    assert len(cases) == 90 and len({x["query"] for x in cases}) == 90
    online_specs = {
        "monitor": [("Dell P3424WEB", "dell.com"), ("ASUS PA32UCXR", "asus.com"), ("LG 32GS95UE-B", "lg.com"), ("BenQ RD280U", "benq.com"), ("Sony SDM-27Q10S", "sony.com")],
        "laptop": [("Dell Latitude 7450", "dell.com"), ("ASUS UX7602", "asus.com"), ("HP OmniBook Ultra Flip 14", "hp.com"), ("Lenovo ThinkPad P1 Gen 7", "lenovo.com"), ("ASUS GU605", "asus.com")],
        "headphone": [("Sony WH-CH720N", "sony.com"), ("Bose QuietComfort Headphones", "bose.com"), ("Logitech Zone Vibe 100", "logitech.com"), ("SteelSeries Arctis Nova 5", "steelseries.com"), ("Sony WF-L910", "sony.com")],
    }
    target_fields = {"monitor": ["display_size_inch", "resolution", "refresh_rate_hz"],
                     "laptop": ["display_size_inch", "weight_kg", "usb_c"],
                     "headphone": ["weight_g", "battery_hours", "bluetooth"]}
    online = [{"case_id": f"rc3i-web-{d}-{i+1:03d}", "domain": d, "model": m, "region": "US",
               "allowed_domains": [site], "fields": target_fields[d],
               "query": f"{m} US official specifications"} for d, rows in online_specs.items() for i, (m, site) in enumerate(rows)]
    for name, data in [("gold_catalog.json", catalog), ("trusted_cases.jsonl", cases), ("online_cases.jsonl", online)]:
        payload = ("\n".join(json.dumps(x, ensure_ascii=False, sort_keys=True) for x in data) + "\n") if name.endswith("jsonl") else json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        with (OUT / name).open("x", encoding="utf8", newline="\n") as f:
            f.write(payload)
        print(name, hashlib.sha256(payload.encode()).hexdigest())
    print("90 Trusted / 15 Online; source-derived gold; no production imports/calls")


if __name__ == "__main__":
    create()
