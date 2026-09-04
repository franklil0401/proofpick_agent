# V2-9C 独立发布评测通用修复报告

## 结论

V2-9B 独立评测的 `Needs revision` 结论保持有效。本轮没有合并或修改独立评测分支，没有改题、改金标、改评分器，也没有把 90 条 Trusted 与 15 条 Online 重新称为未见 Holdout。

通用语义修复后，对已暴露 90 条 Trusted 任务执行了一次审计回归：任务正确率由首次 `64/90` 提升到 `86/90`，硬约束字段 F1 由 `75.49%` 提升到 `94.44%`，推荐/事实证据覆盖由 `276/297` 提升到 `297/297`，困难负例由 `11/18` 提升到 `18/18`；错误配置/地区、Scope 越界、Checker 越界、unknown 过度声明和澄清绕过仍全部为 0。

这只能证明已暴露失败得到修复，**不是新的泛化结果或发布授权**。V2 不得据此合并 `main`、创建 Tag 或 Release；下一套真正未见发布集仍由独立评测方创建和单次运行。

## 审计来源与不可变边界

| 项目 | 值 |
|---|---|
| 独立评测分支 | `origin/eval/v2-9b-independent` |
| 独立评测 Commit | `03ad070d242596c7121da4f7bcf21a1f15758551` |
| 独立 Trusted 首次 run_id | `v2-9b-independent-20260904T073443Z-81d6b7f6` |
| 独立 Trusted 题集 SHA-256 | `22768b4cb9e771f2a378474a1b6ffeca6d60df246668139bfbeec3321b639a7a` |
| 本轮 exposed regression 题集 SHA-256 | `f53757ef371e2a15665d8c95f85adcb4877124520578baba998d16037bb8826d` |
| 本轮 run_id | `v2-9c-exposed-20260904T090844Z-485c3875` |
| 分类 | `exposed regression; not an independent holdout or release conclusion` |

题集 SHA 不同是因为本轮运行器保存的是从 JSONL 解析并按固定顺序序列化后的有效负载哈希；独立分支的原始文件、Schema、评分策略与首次结果均未改动。评分器从独立分支只读加载，没有 Cherry-pick 或合并到生产分支。本轮只提交脱敏评分结果，不提交独立评测器实现。

## 首次 26 条失败归因

下表保留独立首次失败，主分类只取首个错误层；多个层次共同作用时在说明中列出。

| case_id | 主分类 | 首次现象 | 通用修复/结论 |
|---|---|---|---|
| `mon-003` | QueryIntent | 事实字段被激活成硬约束并被列为推荐 | 事实字段只进入 requested fields；推荐集合为空 |
| `mon-016` | Constraint Resolution | 未提取 610mm 宽度上限 | 扩展通用数值、单位和“以内”表达 |
| `mon-017` | Constraint Resolution | 未提取重量和 USB-C 视频 | 扩展通用重量与 USB-C 视频表达 |
| `mon-018` | Constraint Resolution | 未归一化 `5120×2880` | 增加显式分辨率别名和归一化 |
| `mon-019` | Constraint Resolution | IPS Black 未进入 Checker | 增加面板字段与声明式 Checker 能力映射 |
| `mon-020` | Result Classification | 首次放行错误候选 | 修复后治理数据保留 60W/65W 冲突并 fail closed；金标与数据冲突仍记失败 |
| `mon-021` | Tool Orchestration | 比较字段被当硬约束，只保留一侧推荐 | 字段不激活；两侧证据闭合；最终收尾将比较报告改为非推荐 |
| `mon-022` | QueryIntent | 比较字段被当硬约束并发布推荐 | 分离比较事实与购买约束；两侧证据闭合 |
| `mon-023` | QueryIntent | 比较字段被当硬约束并发布推荐 | 分离比较事实与购买约束；两侧证据闭合 |
| `mon-028` | Clarification | `U272` 多义但未暂停 | Registry 前缀解析；收费工具前澄清 |
| `mon-029` | Clarification | 模糊尺寸没有数值阈值 | 无阈值定性词返回 pending，调用为 0 |
| `mon-030` | Clarification | 模糊刷新率直接全库推荐 | 无阈值定性词返回 pending，调用为 0 |
| `lap-014` | ProductReference/Scope | H7606 家族被强制唯一配置 | 家族筛选允许保留多个合规配置 |
| `lap-015` | ProductReference/Scope | XPS 13 家族/配置映射失败 | Registry 生成通用渐进家族别名并按限定词收窄 |
| `lap-016` | Constraint Resolution | 以色列地区/OS 字段不完整 | 地区别名归一；Pack `constraint_enabled` 字段进入 Checker |
| `lap-028` | Clarification | XPS 13 多义但没有澄清 | 多配置身份在收费工具前暂停 |
| `hph-007` | QueryIntent | 事实字段被激活并列为推荐 | 事实字段不再成为购买约束 |
| `hph-009` | QueryIntent | 事实字段被激活并列为推荐 | 事实字段不再成为购买约束 |
| `hph-012` | QueryIntent | 事实字段被激活并列为推荐 | 事实字段不再成为购买约束 |
| `hph-014` | Constraint Resolution | “无线”被裸 `无` 识别成否定 | `无(?!线)`，保留真正否定表达 |
| `hph-022` | Evidence Closure | 比较只保留一侧且证据 2/4 | Scope 保留两配置，按商品 × 字段闭合证据 |
| `hph-023` | Evidence Closure | 两配置比较证据 2/4 | 配置号/地区加入比较身份事实并覆盖两侧 |
| `hph-024` | Evidence Closure | 两产品比较证据 2/4 | Catalog literal 与 Pack 限定词通用解析，闭合两侧 |
| `hph-028` | Clarification | XM5 多义且直接推荐多个产品 | Catalog 前缀多义返回 pending，调用为 0 |
| `hph-029` | Clarification | “续航久一点”未澄清 | 缺少数值阈值时 pending，调用为 0 |
| `hph-030` | ProductReference/Scope | Nova Pro Wireless 多配置身份未澄清 | Registry 多配置身份返回 pending，调用为 0 |

七类问题的边界如下：QueryIntent 决定问题要事实、比较还是购买筛选；ProductReference/Scope 决定允许观察的商品；Constraint Resolution 只把明确购买条件放入 Checker；Clarification 在身份或阈值不明确时早停；Tool Orchestration 必须沿固定 Scope 调工具；Evidence Closure 要覆盖请求字段；Result Classification 决定事实、拒答、冲突或推荐，不能反向修改 Checker。

## 通用实现

1. `QueryUnderstandingEngine` 使用 Pack 字段与通用语言信号分离事实、比较、筛选和澄清；事实/比较字段不会激活购买硬约束。
2. `ProductIdentityResolver` 从 Product Pack 的型号、别名、family/configuration 和字段枚举生成候选，不含 case_id 或具体评测型号补丁；Scope 只保持或收窄。
3. 多义前缀、家族/配置冲突和无数值定性要求在任何收费工具前返回 `pending`。
4. 比较任务使用完整 Scope 作为 Evidence Check 目标；配置与地区有差异时把它们作为身份事实加入证据目标。
5. Legacy Monitor 增加通用宽度、重量、分辨率、面板、地区和 USB-C 表达归一；Checker 继续对未知/冲突 fail closed。
6. Domain Checker 的可执行字段由 Pack `constraint_enabled` 声明与兼容策略共同约束，避免重复白名单漂移。
7. 报告层把显式比较保留为证据分析，只有 filter/dynamic 才能发布购买推荐 ID。

## exposed regression 结果

| 指标 | 独立首次 | 本轮 exposed regression | 变化 |
|---|---:|---:|---:|
| 任务正确率 | 64/90（71.11%） | 86/90（95.56%） | +22 个任务 |
| Monitor | 18/30 | 26/30 | +8 |
| Laptop | 26/30 | 30/30 | +4 |
| Headphone | 20/30 | 30/30 | +10 |
| 硬约束 TP / FP / FN | 77 / 39 / 11 | 85 / 7 / 3 | — |
| 硬约束 Precision / Recall / F1 | 66.38% / 87.50% / 75.49% | 92.39% / 96.59% / 94.44% | F1 +18.95pp |
| 操作符和值 | 75/88 | 84/88 | +9 |
| 推荐/事实 Evidence | 276/297 | 297/297 | +21 |
| 困难负例 | 11/18 | 18/18 | +7 |
| 错误配置/地区 | 36 | 0 | -36 |
| Scope / Checker 越界 | 0 / 0 | 0 / 0 | 不变 |
| unknown 过度声明 / 澄清绕过 | 0 / 7 | 0 / 0 | 澄清 -7 |

本轮评分器的所有 mandatory gate 为 true。机器可读脱敏结果见 [`v2_9c_exposed_regression_summary.json`](../../eval/results/v2_9c_exposed_regression_summary.json)。

### 剩余失败与未包装结果

- `mon-020`：金标要求推荐 `benq-pd2705u-us`，但治理 Evidence 对 USB-C PD 保留 60W/65W 冲突。Checker 正确 fail closed，不能为了金标把 conflict 改成 passed。
- `mon-021`～`mon-023`：回归运行时两侧候选和 `4/4` Evidence 均已闭合，但 Legacy 报告仍把比较对象写进 `recommended_model_ids`，因此评分为失败。运行后已做通用报告分类修复并通过离线定向测试；为避免覆盖审计结果，没有再次运行 90 条收费评测，不能宣称它们已经形成新的 E2E 指标。
- 暴露回归仍有 7 个冗余/缺失约束字段（主要是 `form_factor` 同时派生 `wearing_style`，以及少数 4K/macOS/供电语序），但任务安全与最终候选均未越界。它们留作下一 RC 的通用质量债务，不通过改评分器消除。

## Online 结果边界

V2-9B Online RC2 的不可覆盖结果保持：安全终态 `15/15`，真实网页 Evidence 完成 `2/15`，其余为 `no_official_source` 9 条、`no_region_matched_source` 4 条；Open Evidence 进入 Trusted Checker 为 0，28 次搜索估算成本 ¥1.10。

本轮没有修改 Source Search、Extractor 或 Open Research，也没有重新运行这 15 条已暴露 Online 任务。它们的主要问题属于 Evidence Closure/官方地区来源覆盖，不应通过 QueryIntent 或 Checker 修复伪装成提升。

## API、延迟和审计纪律

| 项目 | 结果 |
|---|---:|
| 请求总数 | 327 |
| qwen-plus / Embedding / Reranker | 147 / 90 / 90 |
| 输入 / 输出 Token | 1,259,922 / 19,645 |
| 估算成本 | ¥0.9615002 |
| 平均 / P95 端到端延迟 | 6,590.45 / 27,467.66 ms |
| 重试 / 失败请求 | 0 / 0 |

运行过程中没有记录 Key、Authorization、隐藏思维链、完整 Prompt、私人路径或运行数据库。外部 Journal 完成 90/90 后只把脱敏摘要纳入 Git。

## 兼容与回滚

- V1 默认 ReAct、Checker 四态、Memory、数据、索引、40 条冻结任务和历史结果未修改。
- Domain Pack、Product Pack 和索引版本未变；本轮只修改通用理解、身份、约束、编排/报告边界及测试。
- 关闭 V2 特性开关仍走 V1 路径；Open/Trusted 隔离和 Checker fail-closed 不变。
- 本轮没有合并独立评测分支、没有创建新 Holdout、没有改 `main`、Tag 或 Release。

## 质量门禁

| 检查 | 结果 |
|---|---|
| CI 等价离线 Pytest | 479/479（含上游配置脱敏测试） |
| V1 Tag 所含 18 个原始测试文件 | 当前 98/98；历史 94 个节点全部保留，另有本轮追加的 4 个参数化/报告断言 |
| V2-9C 定向语义/报告 | 13/13 |
| Ruff / Compileall | 通过 / 通过 |
| 全JavaScript / PowerShell AST | 13/13 / 6/6 |
| Markdown 相对链接 | 421 条、89 份文档，失效 0 |
| 变更文件高置信敏感扫描 | 0 |
| 新增禁止运行产物 | 0 |
| `git diff --check` | 通过 |

全仓库高置信形状扫描仅识别一个早于本轮存在、内容未变的阶段 6 Workspace 占位夹具；新增命中为 0。没有业务 JavaScript 变更，也没有修改 Domain/Product Pack、Catalog、冻结任务、独立评测定义或历史结果。

## 发布判断与下一步

当前仍不是 V2 发布结论。`86/90` 是已暴露回归，不能替代独立首次 `64/90` 或新的未见评测；Online 证据完成仍是 `2/15`。下一步应由独立评测方基于新的 RC Commit、冻结新题集并单次运行。在此之前不得合并 `main` 或创建 V2 Tag/Release。
