# V2-6C-R1 商品身份与 Candidate Scope 失败审计

## 1. 审计边界

- 基线：`b6ae43de9e03cb828b117ff087897800b899d952`
- 冻结任务：[v2_6a_laptop_cases.jsonl](../../eval/v2_6a_laptop_cases.jsonl)，SHA-256 `3dfcc0f442bda2b6b4d2e96814a8973b415b3d8c8b9b33235924982fa1758d34`
- 评分规则：[v2_6c_laptop_scoring_policy.json](../../eval/v2_6c_laptop_scoring_policy.json)，SHA-256 `7617f607d98b5e06e1c43bf09c2fce71a44cea89d9f1da822cc70da5f2f4363c`
- 原 Holdout 首次结果：[v2_6c_laptop_holdout_first.json](../../eval/results/v2_6c_laptop_holdout_first.json)，SHA-256 `5d7009f7c262547a41d63727e5e2e70037cbca01f7d836c2bc10c2a28826aebc`
- 原结果永久保留：Regression `4/10 → 5/10 → 10/10`，原 Holdout `3/10`，原推荐证据覆盖 `3/9`。

本次先只读审计，随后只离线重放已经暴露的 20 条。没有创建新 Holdout，没有运行剩余 10 条，没有调用模型、Embedding、Reranker 或搜索 API。

## 2. 30 条任务口径

“运行次数”是审计开始时仓库内可核验的完整结果快照次数。Regression 每条存在首次及四次独立修复结果；原 Holdout 每条只存在一次首次结果。所有金标在本轮均已审阅，因此剩余 10 条即使尚未运行，也不再具有未见测试资格。

| case_id | category | split | 审计时是否运行 / 次数 | 金标 / 结果是否查看 | 后续资格 |
|---|---|---|---|---|---|
| laptop-001 | structured_filter | regression | 是 / 5 | 是 / 是 | exposed regression |
| laptop-002 | structured_filter | regression | 是 / 5 | 是 / 是 | exposed regression |
| laptop-003 | structured_filter | regression | 是 / 5 | 是 / 是 | exposed regression |
| laptop-004 | structured_filter | regression | 是 / 5 | 是 / 是 | exposed regression |
| laptop-005 | structured_filter | regression | 是 / 5 | 是 / 是 | exposed regression |
| laptop-006 | structured_filter | regression | 是 / 5 | 是 / 是 | exposed regression |
| laptop-007 | structured_filter | regression | 是 / 5 | 是 / 是 | exposed regression |
| laptop-008 | structured_filter | regression | 是 / 5 | 是 / 是 | exposed regression |
| laptop-009 | structured_filter | regression | 是 / 5 | 是 / 是 | exposed regression |
| laptop-010 | structured_filter | regression | 是 / 5 | 是 / 是 | exposed regression |
| laptop-011 | similar_configuration | holdout | 是 / 1 | 是 / 是 | `exposed_holdout_regression_v1` |
| laptop-012 | similar_configuration | holdout | 是 / 1 | 是 / 是 | `exposed_holdout_regression_v1` |
| laptop-013 | similar_configuration | holdout | 是 / 1 | 是 / 是 | `exposed_holdout_regression_v1` |
| laptop-014 | similar_configuration | holdout | 是 / 1 | 是 / 是 | `exposed_holdout_regression_v1` |
| laptop-015 | similar_configuration | holdout | 是 / 1 | 是 / 是 | `exposed_holdout_regression_v1` |
| laptop-016 | region_configuration | holdout | 是 / 1 | 是 / 是 | `exposed_holdout_regression_v1` |
| laptop-017 | region_configuration | holdout | 是 / 1 | 是 / 是 | `exposed_holdout_regression_v1` |
| laptop-018 | region_configuration | holdout | 是 / 1 | 是 / 是 | `exposed_holdout_regression_v1` |
| laptop-019 | region_configuration | holdout | 是 / 1 | 是 / 是 | `exposed_holdout_regression_v1` |
| laptop-020 | region_configuration | holdout | 是 / 1 | 是 / 是 | 安全拒答 exposed regression |
| laptop-021 | unknown_evidence | hard_negative | 否 / 0 | 是 / 无结果 | `unrun_exposed_specialist`，仅可作诊断回归 |
| laptop-022 | unknown_evidence | hard_negative | 否 / 0 | 是 / 无结果 | `unrun_exposed_specialist`，仅可作诊断回归 |
| laptop-023 | unsupported | hard_negative | 否 / 0 | 是 / 无结果 | `unrun_exposed_specialist`，仅可作诊断回归 |
| laptop-024 | unknown_evidence | hard_negative | 否 / 0 | 是 / 无结果 | `unrun_exposed_specialist`，仅可作诊断回归 |
| laptop-025 | unknown_evidence | hard_negative | 否 / 0 | 是 / 无结果 | `unrun_exposed_specialist`，仅可作诊断回归 |
| laptop-026 | natural_constraint | clarification | 否 / 0 | 是 / 无结果 | `unrun_exposed_specialist`，仅可作诊断回归 |
| laptop-027 | natural_constraint | clarification | 否 / 0 | 是 / 无结果 | `unrun_exposed_specialist`，仅可作诊断回归 |
| laptop-028 | natural_constraint | clarification | 否 / 0 | 是 / 无结果 | `unrun_exposed_specialist`，仅可作诊断回归 |
| laptop-029 | natural_constraint | clarification | 否 / 0 | 是 / 无结果 | `unrun_exposed_specialist`，仅可作诊断回归 |
| laptop-030 | natural_constraint | clarification | 否 / 0 | 是 / 无结果 | `unrun_exposed_specialist`，仅可作诊断回归 |

## 3. 身份缩写

| 缩写 | family_id | product_id / configuration_id / region |
|---|---|---|
| WI | `asus-proart-p16-h7606` | `asus-proart-p16-h7606wi-cn` / `H7606WI` / CN |
| WW | `asus-proart-p16-h7606` | `asus-proart-p16-h7606ww-cn` / `H7606WW` / CN |
| WX | `asus-proart-p16-h7606` | `asus-proart-p16-h7606wx-cn` / `H7606WX` / CN |
| XPS-CA | `dell-xps13-9350` | `dell-xps13-9350-caexchcto9350lnl02-ca` / `caexchcto9350lnl02` / CA |
| XPS-US-OLED | `dell-xps13-9350` | `dell-xps13-9350-usexchcto9350lnl06-us` / `usexchcto9350lnl06` / US |
| XPS-US-FHD | `dell-xps13-9350` | `dell-xps13-9350-usexcpcto9350lnl04-us` / `usexcpcto9350lnl04` / US |
| Firefly | `hp-zbook-firefly14-g11` | `hp-zbook-firefly14-g11-98n14et-il` / `98N14ET` / IL |
| Power | `hp-zbook-power-g9` | `hp-zbook-power-g9-6b8c1ea-global` / `6B8C1EA` / GLOBAL |
| T14-DE | `lenovo-thinkpad-t14-g5-intel` | `lenovo-thinkpad-t14-g5-21ml000fgr-de` / `21ML000FGR` / DE |
| T14s-US | `lenovo-thinkpad-t14s-g7-amd` | `lenovo-thinkpad-t14s-g7-21yw0042us-us` / `21YW0042US` / US |
| X1-PH | `lenovo-x1-carbon-g13` | `lenovo-x1-carbon-g13-21nx00k4ph-ph` / `21NX00K4PH` / PH |

## 4. 七条失败链路与安全样本

历史结果没有保存 KB hit 的完整 ID 列表，只保存了脱敏工具状态。因此表中“未持久化”不是推测为空，而是明确表示无法从历史账本恢复；本轮不为补齐审计而重新调用在线 KB。

| case | 原始 mention（Python 字符 span） | 任务 / 初始范围 | Product Query / KB | Evidence / Checker / 最终报告 | 首个错误节点 |
|---|---|---|---|---|---|
| 011 | `H7606WX` `[7:14]`；`H7606WW` `[17:24]` | comparison；旧范围 WI+WW+WX | SQL 未调用；KB 成功但 hit ID 未持久化 | 旧 Evidence、Checker pool、报告均为 WI+WW+WX；eligible 空 | 身份解析用共享前缀/短 token，将未点名 WI 纳入 |
| 012 | `XPS 13 9350` `[4:15]`，并有 US/OLED 限定 | selector；旧范围 XPS 三配置 | SQL 产生 XPS 三配置；KB hit ID 未持久化 | 仅 family 证据；Checker 输入全库 12，eligible 为 XPS 三配置；报告全库 12 | 家族身份未与地区、面板限定合并为唯一配置，Checker 又扩大到全库 |
| 013 | `XPS 13 9350` `[7:18]`，明确比较 16GB FHD / 32GB OLED | comparison；XPS 三配置 | SQL 未调用；KB 成功但 hit ID 未持久化 | Evidence Check 未执行；Checker 非筛选不执行；报告三配置但证据为 0 | 证据字段/目标没有从比较语义贯穿到 Evidence Check |
| 015 | `H7606WI` `[4:11]`；`H7606WX` `[18:25]` | comparison；旧范围 WI+WW+WX | SQL 未调用；KB hit ID 未持久化 | Evidence Check 未执行；报告含未点名 WW 且无证据 | 共享前缀扩大显式比较集合 |
| 016 | `caexchcto9350lnl02` `[7:25]` | fact；身份为 XPS-CA | 旧规则错误激活 `region=US`，SQL 交集为空；KB hit ID 未持久化 | Evidence/Checker 均未执行；报告候选为空 | 否定句“不是美国版”被解析成正向 US 约束，覆盖精确配置身份 |
| 017 | `usexchcto9350lnl06` `[8:26]` | fact-like guard；身份为 XPS-US-OLED | 地区 Proposal 冲突后 pending，所有工具未执行 | Checker 空、报告空 | 约束解析器而非注册身份决定地区，造成不必要澄清和证据丢失 |
| 019 | `ThinkPad` `[30:38]`；US 且排除 DE/PH | filter；旧范围 T14-DE+T14s-US+X1-PH | SQL 未调用；KB hit ID 未持久化 | Evidence/Checker 未执行；报告仍含三项且无证据 | 产品线字面量与确定性地区过滤没有形成统一 Scope |
| 020 | `H7606WX` `[4:11]`；询问 CN 字段能否用于 US | fact；WX/CN | SQL、KB、Evidence 均执行；KB hit ID 未持久化 | Checker 无 eligible；报告只含 WX/CN 并拒答 | 无错误；这是必须保留的跨地区禁止推断样本 |

## 5. 根因结论

失败不是单个 Prompt 问题，而是缺少一个系统拥有、不可扩大的商品范围对象：旧 `_mentioned_products` 允许共享前缀和子串授权身份；Product Query、KB、Evidence、Checker、报告各自重建候选；Checker 在筛选路径显式接收全 Catalog；Evidence 引用没有携带完整配置、数据和索引身份。修复必须在工具链之前解析唯一 Scope，并要求每个下游节点验证同一指纹。

修复与结果见 [V2-6C-R1 修复报告](v2_6c_identity_scope_repair_report.md)和 [ADR-0016](../adr/0016-deterministic-product-identity-and-candidate-scope.md)。
