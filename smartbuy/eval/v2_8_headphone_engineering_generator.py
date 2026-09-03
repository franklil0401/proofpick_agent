"""Generate and freeze the V2-8 Headphone engineering evaluation before execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from smartbuy.domain_packs import DomainConstraintEvaluator, DomainPackLoader
from smartbuy.product_packs import ProductPackLoader


ROOT = Path(__file__).resolve().parents[2]
DOMAIN = ROOT / "smartbuy" / "domain_packs" / "headphone"
PACK = ROOT / "smartbuy" / "product_packs" / "examples" / "headphone-v1" / "pack.json"
CASES = ROOT / "smartbuy" / "eval" / "v2_8_headphone_engineering_cases.jsonl"
POLICY = ROOT / "smartbuy" / "eval" / "v2_8_headphone_engineering_policy.json"
SCHEMA = ROOT / "smartbuy" / "eval" / "v2_8_headphone_engineering.schema.json"


def _c(field: str, operator: str, value: Any, unit: str | None = None) -> dict[str, Any]:
    return {"field": field, "operator": operator, "value": value, "unit": unit}


def _case(
    case_id: str,
    category: str,
    question: str,
    *,
    constraints: list[dict[str, Any]] | None = None,
    expected_kind: str = "eligible",
    expected_ids: list[str] | None = None,
    gold_fields: list[str] | None = None,
    required_tools: list[str] | None = None,
    fault: str | None = None,
    ranking_scenario: str | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "category": category,
        "question": question,
        "constraints": constraints or [],
        "gold_fields": gold_fields or [item["field"] for item in constraints or []],
        "expected_kind": expected_kind,
        "expected_product_ids": expected_ids or [],
        "required_tools": required_tools or [],
        "fault": fault,
        "ranking_scenario": ranking_scenario,
        "frozen_status": "frozen_unrun",
    }


def specifications() -> list[dict[str, Any]]:
    query_tools = ["domain_product_query", "domain_evidence_check", "domain_constraint_checker"]
    fact_tools = ["domain_kb_search", "domain_evidence_check"]
    return [
        _case("headphone-e2e-001", "codec", "耳机必须支持 LDAC。", constraints=[_c("supported_codecs", "contains_all", ["LDAC"])], required_tools=query_tools),
        _case("headphone-e2e-002", "platform", "必须支持 PS5 的耳机。", constraints=[_c("supported_platforms", "contains_all", ["PS5"])], required_tools=query_tools),
        _case("headphone-e2e-003", "platform", "找能用于 Xbox 的无线耳机。", constraints=[_c("supported_platforms", "contains_all", ["Xbox"])], required_tools=query_tools),
        _case("headphone-e2e-004", "commute", "需要主动降噪，重量不要超过 250 克。", constraints=[_c("active_noise_cancellation", "eq", True), _c("weight_g", "lte", 250, "g")], required_tools=query_tools, ranking_scenario="commute"),
        _case("headphone-e2e-005", "form_factor", "不要入耳式，并且重量不超过 250 克。", constraints=[_c("wearing_style", "eq", "headband"), _c("weight_g", "lte", 250, "g")], required_tools=query_tools),
        _case("headphone-e2e-006", "portable", "真无线并且防护等级为 IPX4。", constraints=[_c("form_factor", "eq", "in_ear_true_wireless"), _c("water_resistance", "eq", "IPX4")], required_tools=query_tools),
        _case("headphone-e2e-007", "connection", "需要支持 USB 音频的耳机。", constraints=[_c("usb_audio", "eq", True)], required_tools=query_tools),
        _case("headphone-e2e-008", "gaming", "需要 2.4G 接收器和可拆卸麦克风。", constraints=[_c("wireless_dongle", "eq", True), _c("detachable_microphone", "eq", True)], required_tools=query_tools, ranking_scenario="gaming"),
        _case("headphone-e2e-009", "battery", "续航至少 50 小时。", constraints=[_c("battery_hours", "gte", 50, "h")], required_tools=query_tools),
        _case("headphone-e2e-010", "meeting", "开会用，必须有麦克风并支持同时连电脑和手机。", constraints=[_c("microphone", "eq", True), _c("multipoint", "eq", True)], required_tools=query_tools, ranking_scenario="meeting"),
        _case("headphone-e2e-011", "region", "只看加拿大版 WH-1000XM5。", constraints=[_c("region", "eq", "CA")], required_tools=query_tools),
        _case("headphone-e2e-012", "configuration", "只看配置 NOVA-PRO-WL-XBOX-B-US。", constraints=[_c("configuration_id", "eq", "NOVA-PRO-WL-XBOX-B-US")], required_tools=query_tools),
        _case("headphone-e2e-013", "codec", "真无线耳机里必须支持 LDAC。", constraints=[_c("form_factor", "eq", "in_ear_true_wireless"), _c("supported_codecs", "contains_all", ["LDAC"])], required_tools=query_tools),
        _case("headphone-e2e-014", "gaming", "需要 PS5 兼容并带主动降噪。", constraints=[_c("supported_platforms", "contains_all", ["PS5"]), _c("active_noise_cancellation", "eq", True)], required_tools=query_tools, ranking_scenario="gaming"),
        _case("headphone-e2e-015", "connection", "不要有线连接的头戴式耳机。", constraints=[_c("wired_connection", "eq", False), _c("form_factor", "eq", "over_ear")], required_tools=query_tools),
        _case("headphone-e2e-016", "negative", "必须达到 IPX7 的耳机。", constraints=[_c("water_resistance", "eq", "IPX7")], expected_kind="abstain", required_tools=query_tools),
        _case("headphone-e2e-017", "unknown", "预算不超过 1000 元。", constraints=[_c("price_cny", "lte", 1000, "CNY")], expected_kind="abstain", required_tools=query_tools),
        _case("headphone-e2e-018", "unknown", "实测延迟不超过 50 毫秒。", constraints=[_c("measured_latency_ms", "lte", 50, "ms")], expected_kind="abstain", required_tools=query_tools),
        _case("headphone-e2e-019", "clarification", "主要听流行，不要低频太轰。", expected_kind="clarify", gold_fields=["sound_signature"]),
        _case("headphone-e2e-020", "clarification", "WH-1000XM5 是哪个地区版本？", expected_kind="clarify", gold_fields=["region"]),
        _case("headphone-e2e-021", "exact_fact", "核验 WH1000XM5-B-US 开启 ANC 的续航。", expected_kind="referenced", expected_ids=["sony-wh-1000xm5-black-us"], gold_fields=["battery_hours_anc"], required_tools=fact_tools),
        _case("headphone-e2e-022", "exact_fact", "核验 WF1000XM5-B-US 支持哪些蓝牙编码。", expected_kind="referenced", expected_ids=["sony-wf-1000xm5-black-us"], gold_fields=["supported_codecs"], required_tools=fact_tools),
        _case("headphone-e2e-023", "comparison", "比较 NOVA-PRO-WL-PS-B-US 和 NOVA-PRO-WL-XBOX-B-US 的支持平台。", expected_kind="referenced", expected_ids=["steelseries-arctis-nova-pro-wireless-ps-us", "steelseries-arctis-nova-pro-wireless-xbox-us"], gold_fields=["supported_platforms"], required_tools=fact_tools),
        _case("headphone-e2e-024", "exact_fact", "G735-WHITE-US 的麦克风能否拆卸？", expected_kind="referenced", expected_ids=["logitech-g735-white-us"], gold_fields=["detachable_microphone"], required_tools=fact_tools),
        _case("headphone-e2e-025", "exact_fact", "QCUH2-BLACK-US 是否支持 USB 音频？", expected_kind="referenced", expected_ids=["bose-qc-ultra-headphones-2g-black-us"], gold_fields=["usb_audio"], required_tools=fact_tools),
        _case("headphone-e2e-026", "unsupported", "必须是骨传导耳机。", expected_kind="abstain", gold_fields=["unsupported"]),
        _case("headphone-e2e-027", "clarification", "打游戏延迟不能太高。", expected_kind="clarify", gold_fields=["measured_latency_ms"]),
        _case("headphone-e2e-028", "clarification", "开会用，麦克风要清楚。", expected_kind="clarify", gold_fields=["call_quality_observation"]),
        _case("headphone-e2e-029", "tool_failure", "核验 WH1000XM5-B-US 的重量。", expected_kind="degraded_referenced", expected_ids=["sony-wh-1000xm5-black-us"], gold_fields=["weight_g"], required_tools=fact_tools, fault="reranker_failure"),
        _case("headphone-e2e-030", "tool_failure", "需要支持 LDAC 的耳机。", constraints=[_c("supported_codecs", "contains_all", ["LDAC"])], expected_kind="safety_blocked", required_tools=query_tools, fault="checker_failure"),
    ]


def _eligible_ids(case: dict[str, Any], products: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> list[str]:
    if not case["constraints"] or case["expected_kind"] not in {"eligible", "safety_blocked"}:
        return case["expected_product_ids"]
    pack = DomainPackLoader().load(DOMAIN)
    evaluator = DomainConstraintEvaluator(pack)
    by_product: dict[str, set[str]] = {}
    for item in evidence:
        by_product.setdefault(item["product_id"], set()).add(item["field_id"])
    result = []
    for product in products:
        _, eligible = evaluator.evaluate(
            product, case["constraints"],
            evidenced_fields=by_product.get(product["product_id"], set()),
        )
        if eligible:
            result.append(product["product_id"])
    if case["expected_kind"] == "safety_blocked":
        return result
    if not result:
        raise RuntimeError(f"positive case has no deterministic candidate: {case['case_id']}")
    return sorted(result)


def main() -> int:
    loaded = ProductPackLoader(domain_pack_path=DOMAIN).load(PACK)
    cases = specifications()
    if len(cases) != 30 or len({item["case_id"] for item in cases}) != 30:
        raise RuntimeError("engineering set must contain 30 unique cases")
    for item in cases:
        item["expected_product_ids"] = _eligible_ids(
            item, loaded.normalized_products, loaded.normalized_evidence
        )
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ProofPick V2-8 Headphone engineering case",
        "type": "object",
        "required": ["case_id", "category", "question", "constraints", "gold_fields", "expected_kind", "expected_product_ids", "required_tools", "frozen_status"],
        "properties": {
            "case_id": {"type": "string", "pattern": "^headphone-e2e-[0-9]{3}$"},
            "category": {"type": "string"}, "question": {"type": "string", "minLength": 2},
            "constraints": {"type": "array"}, "gold_fields": {"type": "array", "items": {"type": "string"}},
            "expected_kind": {"enum": ["eligible", "referenced", "degraded_referenced", "clarify", "abstain", "safety_blocked"]},
            "expected_product_ids": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
            "required_tools": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
            "fault": {"type": ["string", "null"]}, "ranking_scenario": {"type": ["string", "null"]},
            "frozen_status": {"const": "frozen_unrun"},
        },
        "additionalProperties": False,
    }
    SCHEMA.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CASES.write_text("".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in cases), encoding="utf-8")
    case_hash = hashlib.sha256(CASES.read_bytes()).hexdigest()
    policy = {
        "schema_version": "proofpick-v2-8-headphone-engineering-policy-v1",
        "case_sha256": case_hash,
        "domain_pack_version": "1.0.0",
        "data_version": "headphone-governed-2026-09-03-v1",
        "index_version": "headphone-governed-2026-09-03-v1-embedding1024-v1",
        "thresholds": {
            "task_accuracy_min": 0.8, "clear_constraint_f1_min": 0.9,
            "recommendation_evidence_coverage_min": 0.95,
            "negative_rejection_min": 0.9, "explicit_violation_recommendations_max": 0,
            "subjective_hard_fact_overrides_max": 0, "wrong_configuration_recommendations_max": 0,
            "wrong_region_recommendations_max": 0, "scope_leakage_max": 0,
            "checker_leakage_max": 0, "report_leakage_max": 0,
            "unknown_overclaims_max": 0, "clarification_bypasses_max": 0,
        },
        "case_count": 30,
        "evaluation_independence": "工程评测集；首次运行前冻结，不宣称第三方盲测。",
    }
    POLICY.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"case_count": len(cases), "case_sha256": case_hash}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
