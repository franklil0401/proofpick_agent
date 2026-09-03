"""Generate the post-freeze V2-6C-R3 Laptop validation round deterministically.

This module is evaluation-only.  It never imports the production Agent and it
does not call a model provider.  Gold records are derived from the already
governed Product Pack and are validated with the read-only repository and
deterministic Checker before the files are frozen.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from smartbuy.domain_packs import DomainPackLoader
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.tools.domain import DomainConstraintCheckerTool, DomainReadonlyRepository

from .v2_6c_r2_laptop_scorer import (
    _active_hard_constraints,
    _validate_constraints,
    _validate_evidence,
    _validate_scope,
)


ROOT = Path(__file__).resolve().parents[2]
CODE_FREEZE_COMMIT = "8859dcbe7cf346600c7fdfe4fe95d342a9f1f5e3"
ROUND = 1
SOURCE_CASES = ROOT / "smartbuy/eval/v2_6c_r2_laptop_holdout.jsonl"
ORIGINAL_CASES = ROOT / "smartbuy/eval/v2_6a_laptop_cases.jsonl"
SCHEMA = ROOT / "smartbuy/eval/v2_6c_r3_validation.schema.json"
DOMAIN_PACK = ROOT / "smartbuy/domain_packs/laptop"
PRODUCT_PACK = ROOT / "smartbuy/product_packs/examples/laptop-v1/pack.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# Each blueprint reuses only a deterministically verified semantic gold record;
# the input expression, case id, category and freeze metadata are new.
BLUEPRINTS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("exact_configuration", "laptop-r2-001", "仅核对 H7606WI 的显卡型号和固态容量，H7606WW、H7606WX 都不要混进来。", ("H7606WI",)),
    ("exact_configuration", "laptop-r2-002", "21YW0042US 这一个料号属于哪个地区、内存多大？不要扩展到其他 ThinkPad。", ("21YW0042US",)),
    ("family_multi_configuration", "laptop-r2-005", "H7606 系列中筛选 RTX 5080 Laptop GPU 和 16GB 显存的配置，并返回配置号。", ("H7606", "RTX 5080 Laptop GPU", "16GB")),
    ("family_multi_configuration", "laptop-r2-007", "XPS 13 9350 家族里只找 16GB 内存、1920x1200 的版本，给出 Order Code。", ("XPS 13 9350", "16GB", "1920x1200")),
    ("family_cross_region", "laptop-r2-008", "XPS 13 9350 的 32GB 版本要买哪个地区我还没决定，请先让我确认 US 或 CA。", ("XPS 13 9350", "32GB")),
    ("family_cross_region", "laptop-r2-009", "caexchcto9350lnl02 仅接受 CA 资料并排除 US 地区证据，请核验屏幕分辨率。", ("caexchcto9350lnl02",)),
    ("explicit_comparison", "laptop-r2-011", "比较 H7606WI 和 H7606WX 的显卡、显存、存储；不要 H7606WW。", ("H7606WI", "H7606WX")),
    ("explicit_comparison", "laptop-r2-012", "对比 caexchcto9350lnl02 与 usexchcto9350lnl06 的地区和系统，排除 usexcpcto9350lnl04。", ("caexchcto9350lnl02", "usexchcto9350lnl06")),
    ("catalog_filter", "laptop-r2-013", "不指定型号：从完整目录筛选内存至少 32GB 且机身不重于 1.2kg 的配置。", ()),
    ("catalog_filter", "laptop-r2-014", "全目录查找 16 英寸、分辨率至少 3840x2400、固态不低于 4TB 的配置。", ()),
    ("include_exclude", "laptop-r2-011", "只把 H7606WI、H7606WX 放进比较范围，H7606WW 明确排除；列显卡、显存和存储。", ("H7606WI", "H7606WX")),
    ("include_exclude", "laptop-r2-012", "比较 caexchcto9350lnl02 和 usexchcto9350lnl06，别把 usexcpcto9350lnl04 加进候选。", ("caexchcto9350lnl02", "usexchcto9350lnl06")),
    ("fact_verification", "laptop-r2-003", "请确认 xps13-9350-oled-ca 对应哪套配置，并核对分辨率与操作系统。", ("xps13-9350-oled-ca",)),
    ("fact_verification", "laptop-r2-004", "只查询 9G0C0ET：是否有雷电接口，内存和硬盘能否升级？", ("9G0C0ET",)),
    ("numeric_and_unit", "laptop-r2-013", "全库找内存最低 32.0GB、重量上限 1200g 的配置。", ()),
    ("numeric_and_unit", "laptop-r2-014", "目录中筛选 16.0 英寸、至少 3840×2400 且存储不低于 4096GB 的机器。", ()),
    ("update_or_cancel", "laptop-r2-017", "预算不用管；内存至少 32GB；固态先定 2TB，后来改成最低 1TB，以后者为准。", ()),
    ("update_or_cancel", "laptop-r2-017", "取消预算限制。至少 32G 内存；存储原想要 2T，最终改为不低于 1T。", ()),
    ("unknown_or_refusal", "laptop-r2-015", "H7606WI 的分辨率和刷新率分别是多少？治理资料缺字段就明确说未知。", ("H7606WI",)),
    ("unknown_or_refusal", "laptop-r2-016", "仅核验 usexcpcto9350lnl04 的电池容量和 Thunderbolt；没有证据不要猜。", ("usexcpcto9350lnl04",)),
    ("clarification", "laptop-r2-006", "ProArt P16 H7606 有 WI、WW、WX 多套配置，我没选具体一个，请先澄清。", ("ProArt P16 H7606",)),
    ("clarification", "laptop-r2-018", "我只说想轻一些、内存大一点，没有给阈值；请先追问，暂时别筛选。", ()),
    ("evidence_identity_isolation", "laptop-r2-019", "核验美版 usexchcto9350lnl06 的分辨率；加拿大同值页面也不能替代美版证据。", ("usexchcto9350lnl06",)),
    ("evidence_identity_isolation", "laptop-r2-020", "查 H7606WI 的显存；H7606WX 即使是 24GB 也不能作为 WI 的事实。", ("H7606WI",)),
)


def generate(output: Path, policy_output: Path, manifest_output: Path) -> dict[str, Any]:
    if any(path.exists() for path in (output, policy_output, manifest_output)):
        raise RuntimeError("validation freeze output already exists")
    source = {item["case_id"]: item for item in _jsonl(SOURCE_CASES)}
    exposed_questions = {
        item["question"].strip() for item in [*_jsonl(SOURCE_CASES), *_jsonl(ORIGINAL_CASES)]
    }
    seed_material = f"{CODE_FREEZE_COMMIT}:v2-6c-r3:round-{ROUND}"
    seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest(), 16)
    blueprints = list(BLUEPRINTS)
    random.Random(seed).shuffle(blueprints)
    cases: list[dict[str, Any]] = []
    for number, (category, source_id, question, mentions) in enumerate(blueprints, 1):
        if question in exposed_questions:
            raise RuntimeError("generated question duplicates an exposed input")
        gold = copy.deepcopy(source[source_id]["gold"])
        gold["scope"]["mentioned_quotes"] = list(mentions)
        cases.append(
            {
                "case_id": f"laptop-r3-v{ROUND}-{number:03d}",
                "split": "post_code_freeze_validation",
                "category": category,
                "question": question,
                "evaluation_state": "frozen_unrun",
                "run_count": 0,
                "gold": gold,
            }
        )
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    for case in cases:
        validator.validate(case)
    if len(cases) != 24 or len({item["case_id"] for item in cases}) != 24:
        raise RuntimeError("validation set must contain 24 unique cases")
    distribution = Counter(item["category"] for item in cases)
    if set(distribution.values()) != {2} or len(distribution) != 12:
        raise RuntimeError("validation set must contain two cases in each category")

    with tempfile.TemporaryDirectory(prefix="proofpick-v2-6c-r3-gold-") as temporary:
        pack = DomainPackLoader().load(DOMAIN_PACK)
        manager = DomainProductPackManager(
            Path(temporary) / "data", domain_pack_path=DOMAIN_PACK
        )
        snapshot = manager.publish(manager.stage(PRODUCT_PACK).data_version)
        connection = sqlite3.connect(
            f"file:{snapshot.database_path.as_posix()}?mode=ro&immutable=1", uri=True
        )
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("gold SQLite integrity check failed")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("gold SQLite has foreign-key violations")
        finally:
            connection.close()
        repository = DomainReadonlyRepository(snapshot, pack)
        products = repository.load()
        checker = DomainConstraintCheckerTool(repository)
        for case in cases:
            _validate_scope(case, products)
            _validate_constraints(case, pack)
            _validate_evidence(case, products)
            constraints = _active_hard_constraints(case)
            checker_ids = case["gold"]["checker_candidate_ids"]
            if constraints and not case["gold"]["clarification_required"]:
                result = checker.run(constraints, candidate_ids=checker_ids)
                if result.status != "success":
                    raise RuntimeError(f"{case['case_id']}: Checker failed")
                eligible = sorted(
                    item["product_id"] for item in result.data["results"] if item["eligible"]
                )
                if eligible != sorted(case["gold"]["final_candidate_ids"]):
                    raise RuntimeError(f"{case['case_id']}: Checker gold mismatch")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in cases),
        encoding="utf-8",
        newline="\n",
    )
    case_sha = _sha(output)
    policy = {
        "schema_version": "proofpick-v2-6c-r3-validation-policy-v1",
        "round": ROUND,
        "classification": "代码冻结后生成并单次运行的验证集",
        "code_freeze_commit": CODE_FREEZE_COMMIT,
        "seed_material_sha256": hashlib.sha256(seed_material.encode("utf-8")).hexdigest(),
        "case_sha256": case_sha,
        "case_count": 24,
        "allowed_complete_runs": 1,
        "scoring": "exact scope, canonical hard constraints, tool subsequence, Checker pool, result, evidence and safety gates",
        "thresholds": {
            "task_accuracy_min": 0.8,
            "clear_hard_constraint_f1_min": 0.9,
            "recommendation_evidence_coverage_min": 0.95,
            "wrong_configuration_recommendations_max": 0,
            "wrong_region_recommendations_max": 0,
            "candidate_scope_leakage_max": 0,
            "checker_scope_leakage_max": 0,
            "unknown_overclaimed_max": 0,
            "clarification_bypass_max": 0,
            "non_domain_field_activations_max": 0,
            "sufficient_evidence_empty_recommendation_rate_max": 0.1,
        },
    }
    policy_output.write_text(
        json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest = {
        "schema_version": "proofpick-v2-6c-r3-validation-freeze-v1",
        "round": ROUND,
        "code_freeze_commit": CODE_FREEZE_COMMIT,
        "case_sha256": case_sha,
        "schema_sha256": _sha(SCHEMA),
        "policy_sha256": _sha(policy_output),
        "case_count": len(cases),
        "category_distribution": dict(sorted(distribution.items())),
        "schema_valid": True,
        "gold_sqlite_integrity": "ok",
        "gold_foreign_key_violations": 0,
        "gold_checker_valid": True,
        "questions_distinct_from_exposed_50": True,
        "evaluation_state": "frozen_unrun",
        "run_count": 0,
        "paid_api_calls": 0,
    }
    manifest_output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--policy-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()
    result = generate(args.output, args.policy_output, args.manifest_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
