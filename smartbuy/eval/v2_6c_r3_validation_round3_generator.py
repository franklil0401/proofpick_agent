"""Freeze the final permitted V2-6C-R3 validation round."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import v2_6c_r3_validation_generator as core


ROOT = Path(__file__).resolve().parents[2]
CODE_FREEZE_COMMIT = "08c7381fdde9a4bf3f7836f74c982572dd5412d7"
ROUND = 3
PRIOR_VALIDATION_CASES = (
    ROOT / "smartbuy/eval/v2_6c_r3_validation_round1.jsonl",
    ROOT / "smartbuy/eval/v2_6c_r3_validation_round2.jsonl",
)


BLUEPRINTS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "exact_configuration", "laptop-r2-001",
        "请核验配置 H7606WI 的显卡型号、固态容量；H7606WW 和 H7606WX 不参与。",
        ("H7606WI",),
    ),
    (
        "exact_configuration", "laptop-r2-002",
        "只查 21YW0042US：它的地区与内存容量分别是什么？",
        ("21YW0042US",),
    ),
    (
        "family_multi_configuration", "laptop-r2-005",
        "H7606 系列中需要显卡 RTX 5080 Laptop GPU、显存 16GB，请给出唯一配置号。",
        ("H7606", "RTX 5080 Laptop GPU", "16GB"),
    ),
    (
        "family_multi_configuration", "laptop-r2-007",
        "在 XPS 13 9350 家族筛选内存 16GB、分辨率 1920x1200 的配置，并返回 Order Code。",
        ("XPS 13 9350", "16GB", "1920x1200"),
    ),
    (
        "family_cross_region", "laptop-r2-008",
        "XPS 13 9350 要内存 32GB；美国区或加拿大区尚未决定，请先确认地区。",
        ("XPS 13 9350", "32GB"),
    ),
    (
        "family_cross_region", "laptop-r2-008",
        "想选 XPS 13 9350 的 32GB 内存版本，但地区没有选，请先澄清 US 还是 CA。",
        ("XPS 13 9350", "32GB"),
    ),
    (
        "explicit_comparison", "laptop-r2-011",
        "对比 H7606WI 和 H7606WX 的显卡、显存、存储，H7606WW 不参与。",
        ("H7606WI", "H7606WX"),
    ),
    (
        "explicit_comparison", "laptop-r2-012",
        "请比较 caexchcto9350lnl02 与 usexchcto9350lnl06 的地区、操作系统；排除 usexcpcto9350lnl04。",
        ("caexchcto9350lnl02", "usexchcto9350lnl06"),
    ),
    (
        "catalog_filter", "laptop-r2-013",
        "从全部配置中筛选重量不超过 1.2kg、内存至少 32GB 的笔记本。",
        (),
    ),
    (
        "catalog_filter", "laptop-r2-014",
        "全目录选择屏幕 16 英寸、分辨率不低于 3840x2400、存储最低 4TB 的配置。",
        (),
    ),
    (
        "include_exclude", "laptop-r2-011",
        "候选只包含 H7606WI、H7606WX，明确排除 H7606WW；比较显卡、显存与存储。",
        ("H7606WI", "H7606WX"),
    ),
    (
        "include_exclude", "laptop-r2-012",
        "仅比较 caexchcto9350lnl02 和 usexchcto9350lnl06 的地区及系统，不要 usexcpcto9350lnl04。",
        ("caexchcto9350lnl02", "usexchcto9350lnl06"),
    ),
    (
        "fact_verification", "laptop-r2-003",
        "核实 xps13-9350-oled-ca 对应的配置号、分辨率、操作系统。",
        ("xps13-9350-oled-ca",),
    ),
    (
        "fact_verification", "laptop-r2-004",
        "9G0C0ET 有没有 Thunderbolt？内存和硬盘是否可以升级？",
        ("9G0C0ET",),
    ),
    (
        "numeric_and_unit", "laptop-r2-013",
        "筛选内存不少于 32GB、整机重量最多 1200g 的全部配置。",
        (),
    ),
    (
        "numeric_and_unit", "laptop-r2-014",
        "要求 16 英寸、至少 3840×2400 分辨率、固态下限 4096GB。",
        (),
    ),
    (
        "update_or_cancel", "laptop-r2-017",
        "移除预算要求；内存最低 32G；固态原来至少 2T，改为至少 1T。",
        (),
    ),
    (
        "update_or_cancel", "laptop-r2-017",
        "预算不用限制，内存至少 32GB；存储从最低 2TB 改成最低 1TB。",
        (),
    ),
    (
        "unknown_or_refusal", "laptop-r2-015",
        "H7606WI 的屏幕分辨率、刷新率是什么？证据缺少的字段请标 unknown。",
        ("H7606WI",),
    ),
    (
        "unknown_or_refusal", "laptop-r2-016",
        "核验 usexcpcto9350lnl04 的电池容量和 Thunderbolt，治理资料没有就拒绝推断。",
        ("usexcpcto9350lnl04",),
    ),
    (
        "clarification", "laptop-r2-006",
        "ProArt P16 H7606 有 WI、WW、WX 多个配置，我没有指定，请先确认具体配置。",
        ("ProArt P16 H7606",),
    ),
    (
        "clarification", "laptop-r2-018",
        "只要求轻一点、内存大些，没有任何数值；请先澄清，不能直接推荐。",
        (),
    ),
    (
        "evidence_identity_isolation", "laptop-r2-020",
        "请查 H7606WI 的显存；H7606WX 的 24GB 参数不能作为 WI 的证据。",
        ("H7606WI",),
    ),
    (
        "evidence_identity_isolation", "laptop-r2-020",
        "H7606WI 配置的 GPU 显存是多少？不要把 H7606WX 的 24GB 资料算进来。",
        ("H7606WI",),
    ),
)


def _questions(paths: tuple[Path, ...]) -> set[str]:
    return {
        json.loads(line)["question"].strip()
        for path in paths
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def generate(output: Path, policy_output: Path, manifest_output: Path) -> dict[str, object]:
    previous = _questions(PRIOR_VALIDATION_CASES)
    generated = [item[2].strip() for item in BLUEPRINTS]
    if len(set(generated)) != 24 or previous.intersection(generated):
        raise RuntimeError("round 3 expressions must be unique and absent from earlier rounds")
    core.CODE_FREEZE_COMMIT = CODE_FREEZE_COMMIT
    core.ROUND = ROUND
    core.BLUEPRINTS = BLUEPRINTS
    manifest = core.generate(output, policy_output, manifest_output)
    manifest["questions_distinct_from_exposed_98"] = True
    manifest_output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
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
