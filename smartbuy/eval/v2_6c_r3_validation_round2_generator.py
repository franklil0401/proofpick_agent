"""Freeze validation round 2 after the first round became exposed.

The implementation delegates schema and deterministic gold verification to
the round generator while supplying a new code-seeded expression set.  It
does not import the production Agent and cannot call a model provider.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import v2_6c_r3_validation_generator as core


ROOT = Path(__file__).resolve().parents[2]
CODE_FREEZE_COMMIT = "3667ff215c5d09e81af023fb8506dbfc71f7c995"
ROUND = 2
ROUND1_CASES = ROOT / "smartbuy/eval/v2_6c_r3_validation_round1.jsonl"


BLUEPRINTS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "exact_configuration",
        "laptop-r2-001",
        "H7606WI 这套的显卡型号与固态容量各是多少？同家族另外两套不得代答。",
        ("H7606WI",),
    ),
    (
        "exact_configuration",
        "laptop-r2-002",
        "核验料号 21YW0042US 的归属地区和内存容量，范围只限这一项。",
        ("21YW0042US",),
    ),
    (
        "family_multi_configuration",
        "laptop-r2-005",
        "从 H7606 家族挑出 RTX 5080 Laptop GPU 且显存为 16GB 的配置，并给配置号。",
        ("H7606", "RTX 5080 Laptop GPU", "16GB"),
    ),
    (
        "family_multi_configuration",
        "laptop-r2-007",
        "XPS 13 9350 系列内要 16GB 内存和 1920×1200 屏幕，请定位对应 Order Code。",
        ("XPS 13 9350", "16GB", "1920×1200"),
    ),
    (
        "family_cross_region",
        "laptop-r2-008",
        "我在看 XPS 13 9350 的 32GB 配置，但美国还是加拿大尚未决定，先向我确认地区。",
        ("XPS 13 9350", "32GB"),
    ),
    (
        "family_cross_region",
        "laptop-r2-008",
        "需要 XPS 13 9350 家族的 32GB 版本；地区还没决定，不要直接替我选配置。",
        ("XPS 13 9350", "32GB"),
    ),
    (
        "explicit_comparison",
        "laptop-r2-011",
        "请对照 H7606WI 与 H7606WX 的显卡、显存和存储，H7606WW 不属于比较对象。",
        ("H7606WI", "H7606WX"),
    ),
    (
        "explicit_comparison",
        "laptop-r2-012",
        "比较 caexchcto9350lnl02、usexchcto9350lnl06 的地区与系统；不要加入 usexcpcto9350lnl04。",
        ("caexchcto9350lnl02", "usexchcto9350lnl06"),
    ),
    (
        "catalog_filter",
        "laptop-r2-013",
        "不点名产品，从目录找内存不少于 32GB 且重量最多 1.2kg 的全部配置。",
        (),
    ),
    (
        "catalog_filter",
        "laptop-r2-014",
        "全库筛选 16 英寸、最低 3840×2400 分辨率、固态至少 4TB 的笔记本。",
        (),
    ),
    (
        "include_exclude",
        "laptop-r2-011",
        "比较范围仅为 H7606WI 和 H7606WX，剔除 H7606WW；展示显卡、显存、存储。",
        ("H7606WI", "H7606WX"),
    ),
    (
        "include_exclude",
        "laptop-r2-012",
        "把 caexchcto9350lnl02 与 usexchcto9350lnl06 放在一起比较地区和系统，排除 usexcpcto9350lnl04。",
        ("caexchcto9350lnl02", "usexchcto9350lnl06"),
    ),
    (
        "fact_verification",
        "laptop-r2-003",
        "别名 xps13-9350-oled-ca 对应什么配置？同时核对分辨率和操作系统。",
        ("xps13-9350-oled-ca",),
    ),
    (
        "fact_verification",
        "laptop-r2-004",
        "SKU 9G0C0ET 是否配有 Thunderbolt，内存与硬盘升级能力如何？",
        ("9G0C0ET",),
    ),
    (
        "numeric_and_unit",
        "laptop-r2-013",
        "目录筛选条件：内存下限 32.0 GB，机身重量上限 1200 g。",
        (),
    ),
    (
        "numeric_and_unit",
        "laptop-r2-014",
        "找 16.0 寸、分辨率不低于 3840x2400、存储至少 4096 GB 的配置。",
        (),
    ),
    (
        "update_or_cancel",
        "laptop-r2-017",
        "取消预算条件；内存至少 32GB。存储原定 2TB，现改为最低 1TB。",
        (),
    ),
    (
        "update_or_cancel",
        "laptop-r2-017",
        "预算限制移除，保留内存不低于 32G；固态从至少 2T 覆盖成至少 1T。",
        (),
    ),
    (
        "unknown_or_refusal",
        "laptop-r2-015",
        "核实 H7606WI 的分辨率和刷新率；治理证据没有记录时必须回答未知。",
        ("H7606WI",),
    ),
    (
        "unknown_or_refusal",
        "laptop-r2-016",
        "usexcpcto9350lnl04 的电池容量及 Thunderbolt 能否由现有证据确认？缺失就拒绝猜测。",
        ("usexcpcto9350lnl04",),
    ),
    (
        "clarification",
        "laptop-r2-006",
        "ProArt P16 H7606 有多种配置，我没有选 WI、WW 或 WX，请先澄清再继续。",
        ("ProArt P16 H7606",),
    ),
    (
        "clarification",
        "laptop-r2-018",
        "我只说想轻一些、内存更大，却没有阈值；请先追问，不要执行筛选。",
        (),
    ),
    (
        "evidence_identity_isolation",
        "laptop-r2-020",
        "H7606WI 的显存是多少？即便 H7606WX 写着 24GB，也不能把该值套给 WI。",
        ("H7606WI",),
    ),
    (
        "evidence_identity_isolation",
        "laptop-r2-020",
        "仅核验 H7606WI 的 GPU 显存；来自 H7606WX 的 24GB 证据必须隔离。",
        ("H7606WI",),
    ),
)


def _questions(path: Path) -> set[str]:
    return {
        json.loads(line)["question"].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def generate(output: Path, policy_output: Path, manifest_output: Path) -> dict[str, object]:
    previous = _questions(ROUND1_CASES)
    generated = [item[2].strip() for item in BLUEPRINTS]
    if len(set(generated)) != 24 or previous.intersection(generated):
        raise RuntimeError("round 2 expressions must be unique and absent from round 1")
    core.CODE_FREEZE_COMMIT = CODE_FREEZE_COMMIT
    core.ROUND = ROUND
    core.BLUEPRINTS = BLUEPRINTS
    manifest = core.generate(output, policy_output, manifest_output)
    manifest["questions_distinct_from_exposed_74"] = True
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
