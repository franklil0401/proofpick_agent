# V2-6C 第二套 Laptop Holdout 数据卡

## 1. 冻结状态

| 项目 | 冻结值 |
|---|---|
| 代码基线 | `5e1d710c416bceaf66c4cc1a5e7d5e20da04dfbc` |
| 任务文件 | [`v2_6c_r2_laptop_holdout.jsonl`](../../eval/v2_6c_r2_laptop_holdout.jsonl) |
| 任务数量 | 20 |
| Split | `second_holdout` |
| 初始状态 | 全部 `frozen_unrun`，`run_count=0` |
| Domain | `laptop` |
| Domain Pack | `1.0.0` |
| Data Version | `laptop-governed-2026-09-02-v1` |
| Index Version | `laptop-governed-2026-09-02-v1-embedding1024-v1` |
| Product Pack | 现有 12 个治理配置；未增删商品或证据 |
| 冻结阶段 Agent E2E | 0 次 |
| 冻结阶段收费 API | 0 次 / ¥0 |

本评测集是**代码冻结后创建、冻结并单次运行的第二验证集**。任务和金标由当前开发 Agent 创建并完成确定性复核，因此不是严格意义上的第三方盲测；首次运行前不得查看任何 Agent 输出、抽样试跑或按 case 选择运行。

## 2. 分类分布

| 分类 | 数量 | 覆盖重点 |
|---|---:|---|
| 精确配置或 SKU | 4 | configuration、Part Number、唯一别名和注册地区 |
| 同 Family 不同配置 | 3 | 唯一选择、共享前缀和多配置澄清 |
| 同 Family 不同地区 | 3 | 地区未说明、明确排除地区和配置隐含地区 |
| 明确多配置比较 | 2 | 只保留点名对象，不补入同 Family 兄弟配置 |
| 无型号 Catalog 筛选 | 2 | 完整候选池和确定性硬约束 |
| unknown / 证据不足 | 2 | null 不猜测、无证据拒答 |
| 自然约束、覆盖或澄清 | 2 | 覆盖、取消和无数值歧义 |
| Evidence 身份或地区隔离 | 2 | 同值跨地区不可替代、共享前缀配置不可错绑 |

结果类型为：`eligible` 7 条、`referenced` 8 条、`clarify` 3 条、`abstain` 2 条；15 条有明确目标配置，5 条必须澄清或拒答。

## 3. 数据与出题方法

- 任务只基于 [`laptop-v1 Product Pack`](../../product_packs/examples/laptop-v1/pack.json)中的 12 个既有配置、Laptop Domain Pack 字段和 406 条治理证据。
- 输入没有直接复制原 30 条 [`v2_6a_laptop_cases.jsonl`](../../eval/v2_6a_laptop_cases.jsonl)；使用了新的自然语言表达、约束组合和负向身份边界。
- 每条金标固定 domain、Scope 类型、family/product/configuration/region 集合、结构化约束、工具顺序、Checker 输入、最终候选或拒答原因、Evidence 要求与澄清状态。
- 精确配置、family 和比较集合来自 Product Pack Registry；不存在 startswith、模糊匹配或 LLM 补全。
- 正例由现有字段值、单位归一化和确定性 Checker 复核；负例由 null 字段、缺失 Evidence 或明确歧义复核。
- `forbidden_evidence_product_ids` 明确记录不能替代目标事实的其他配置或地区证据。

## 4. 冻结前金标核验

只运行了 [`v2_6c_r2_laptop_scorer.py --validate-gold`](../../eval/v2_6c_r2_laptop_scorer.py)，这是 Schema 与金标检查，不调用 Agent、Parser、KB、Embedding、Reranker、Source Search 或 LLM，也不产生任务结果。

| 核验项 | 结果 |
|---|---:|
| JSON Schema | 20/20 |
| case_id 唯一且连续 | 20/20 |
| 与原 30 条输入完全重复 | 0 |
| 分类分布 | 4/3/3/2/2/2/2/2，符合冻结设计 |
| 临时 SQLite `integrity_check` | `ok` |
| 临时 SQLite 外键违规 | 0 |
| Product / Source / Evidence 行数 | 12 / 12 / 406 |
| 由确定性 Checker 复核的硬约束任务 | 7/7 自洽 |
| 字段级 Evidence 身份闭包 | 64/64 |
| 正例存在合规候选 | 15/15 |
| 澄清或拒答负例自洽 | 5/5 |
| Agent E2E 运行 | 0 |

临时 SQLite 在仓库外的系统临时目录中幂等生成，检查结束即清理；没有创建或提交运行数据库、索引、缓存或日志。

## 5. 评分规则与通过门槛

固定策略见 [`v2_6c_r2_laptop_scoring_policy.json`](../../eval/v2_6c_r2_laptop_scoring_policy.json)。任务级正确要求 Scope、有效硬约束、必要工具顺序、Checker 候选集合、结果类型、最终候选及澄清/拒答行为同时匹配；候选和身份集合排序不计分，推荐排序不计分。

| 指标 | 阻断门槛 |
|---|---:|
| 任务级正确率 | ≥ 80% |
| 清晰硬约束字段级 F1 | ≥ 90% |
| 推荐事实证据覆盖率 | ≥ 95% |
| 错误配置推荐 | 0 |
| 错误地区推荐 | 0 |
| Candidate Scope 越界 | 0 |
| Checker 越界 | 0 |
| unknown 误写为满足 | 0 |
| 应澄清却直接推荐 | 0 |
| 充分证据时错误空推荐率 | ≤ 10% |

首次完整运行必须一次覆盖全部 20 条并保存不可覆盖的原始结果。首次结果失败时只能另存定向诊断或后续回归，不能改写本文件、金标或首次结果。

## 6. 冻结哈希

| 文件 | SHA-256 |
|---|---|
| `v2_6c_r2_laptop_holdout.jsonl` | `dd17cf4a4bf794c77cc75b5406f9e603effc7be4e63f9e9b215a9d4d8ea9e24f` |
| `v2_6c_r2_laptop_holdout.schema.json` | `4cc231fe9e7ee2a50c30ffb3e86da7abf1041280a2b2ecb3317fbab003cce7dc` |
| `v2_6c_r2_laptop_scoring_policy.json` | `7cf3395ca1c2bdb5675577a42b885de78b1ebb8bb6962cbe2bd49d210c0a1c7a` |
| `v2_6c_r2_laptop_scorer.py` | `4fb494700ffb90558ffb2a5a0c49c6f0a0f854516ce5f7ced4e643eb7480edc8` |
| 既有 Laptop Product Pack | `0417332b70d772e851f705c83df7932cd60f5d879425ee04f032f08d9c16dc2a` |

评分脚本或策略发生任何变化都必须形成新版本和新哈希，不能继续沿用本次冻结身份。本轮未修改 Product Pack、Data/Index Version、生产代码、Prompt、Parser、Agent、Checker、Evidence 或历史评测结果。
