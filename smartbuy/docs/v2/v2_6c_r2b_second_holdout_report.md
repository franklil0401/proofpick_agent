# V2-6C-R2B 第二套 Laptop Holdout 首次运行报告

## 1. 结论

第二套 Laptop Holdout 已按冻结顺序完成唯一一次运行，结果为 **2/20**，未达到联合门槛。本次运行及全部失败已经永久保存；本轮没有修改生产代码、Prompt、Holdout、金标、评分规则、Product Pack、Domain Pack、数据或索引，也没有重跑。

这不是 V2-6C 完成结果。由于任务正确率、约束 F1、证据覆盖、错误配置、Candidate Scope、澄清和错误空推荐门均未通过，当前不具备继续 Open Research、Memory 专项、完整故障矩阵或 V2-7 的条件。

机器记录：

- [RC 配置](../../eval/results/v2_6c_r2_release_candidate.json)
- [逐条追加 Journal](../../eval/results/v2_6c_r2_laptop_holdout_first.journal.jsonl)
- [不可覆盖首次结果](../../eval/results/v2_6c_r2_laptop_holdout_first.json)

## 2. 运行身份与前置门禁

| 项目 | 冻结值或结果 |
|---|---|
| 生产代码 / Holdout Commit | `1112f8dad3410af821e11edc60e83ab7ac3112ce` |
| Holdout SHA-256 | `dd17cf4a4bf794c77cc75b5406f9e603effc7be4e63f9e9b215a9d4d8ea9e24f` |
| Run ID | `v2-6c-r2b-20260903T055728Z-1ac7528b` |
| 运行次数 | `1` |
| RC 合同 SHA-256 | `555e4d8bcce61bb90aba5078c04aedce5f4ba2deca369ff0ad011a5119289224` |
| RC 文件 SHA-256 | `5c373809578031f48ff2b710797bec6e1b1a3c674bdab38dfd2534ed9abf0356` |
| Journal SHA-256 | `7b19f1257c186b22f93c4b2c2e4b97d4940370b85caeaf2068962473f41f41f3` |
| 首次结果 SHA-256 | `ce682bf08ae24a2e312c2d330f3e94ec3620fe50d4c3fba2654b09b07f37e7de` |
| Domain Pack | `laptop` / `1.0.0` |
| Data Version | `laptop-governed-2026-09-02-v1` |
| Index Version | `laptop-governed-2026-09-02-v1-embedding1024-v1` |
| Collection | `proofpick_laptop_v2_4e6d332c11bf8f7c` |
| 索引契约 | 12 documents / 12 chunks / `text-embedding-v4` 1024 维 |
| 模型 | `qwen-plus` / `text-embedding-v4` / `qwen3-rerank` |
| 编排与缓存 | ReAct；主评测热缓存关闭 |
| 最大步骤 / 工具调用 | 8 / 12 |
| 运行前任务状态 | 20/20 `frozen_unrun`，`run_count=0` |
| 历史 R2 Agent 结果 | 0 |

运行前验证了分支、Commit、工作区、Holdout/Schema/Policy/Scorer/Product Pack 哈希、Pack/Data/Index 身份和环境变量配置状态。密钥只由进程环境读取，未打印或落盘。RC 冻结后没有修改 Runner、Prompt 或生产配置。

## 3. 评分器完整性

冻结金标 Oracle 自检可评分 20/20，没有静默跳过：

- 7 条 `eligible` 筛选正例有明确的硬约束和 Checker 候选池，由 Constraint Checker 复核，因此冻结时的 Checker 分母为 7/7。
- 其余 8 条正例为 `referenced` 事实核验或明确比较，不产生购买筛选资格；它们通过精确 Scope、工具顺序、返回配置集合和字段级 Evidence 判定。
- 3 条 `clarify` 与 2 条 `abstain` 分别检查暂停澄清和证据不足拒答。
- 因而正例总数为 15，但只有其中 7 条应进入 Checker；强迫另外 8 条进入 Checker 会改变任务语义。

## 4. 首次结果

| 指标 | 首次结果 | 门槛 | 结论 |
|---|---:|---:|---|
| 任务级正确率 | 2/20（10.00%） | ≥16/20 | 未通过 |
| 清晰硬约束 TP / FP / FN | 3 / 10 / 12 | — | — |
| 硬约束 Precision | 3/13（23.08%） | — | — |
| 硬约束 Recall | 3/15（20.00%） | — | — |
| 硬约束 F1 | 21.43% | ≥90% | 未通过 |
| 正例候选召回 | 15/27（55.56%） | 单独报告 | — |
| 澄清/拒答正确率 | 1/5（20.00%） | — | 未通过 |
| 推荐事实证据覆盖 | 32/36（88.89%） | ≥95% | 未通过 |
| 错误配置推荐 | 1 | 0 | 未通过 |
| 错误地区推荐 | 0 | 0 | 通过 |
| Candidate Scope 越界 | 1 | 0 | 未通过 |
| Checker 越界 | 0 | 0 | 通过 |
| unknown 误写为满足 | 0 | 0 | 通过 |
| 应澄清却执行决策 | 1 | 0 | 未通过 |
| 非 Domain Pack 字段激活 | 0 | 0 | 通过 |
| Prompt Injection 越权 | 0 | 0 | 通过；本集专门注入用例为 0 条 |
| 充分证据下错误空推荐 | 3/7（42.86%） | ≤10% | 未通过 |

通过的任务只有 `laptop-r2-004` 和 `laptop-r2-015`。八类任务结果如下：

| 分类 | 正确数/总数 |
|---|---:|
| 精确配置或 SKU | 1/4 |
| 同 Family 不同配置 | 0/3 |
| 同 Family 不同地区 | 0/3 |
| 明确多配置比较 | 0/2 |
| 无型号 Catalog 筛选 | 0/2 |
| unknown / 证据不足 | 1/2 |
| 自然约束、覆盖或澄清 | 0/2 |
| Evidence 身份或地区隔离 | 0/2 |

## 5. 失败任务审计

首个错误节点分布：商品身份/Scope 8 条、约束解析 9 条、工具编排 1 条。

| Case | 首错节点 | 实际差异与根因 | 安全影响 |
|---|---|---|---|
| `laptop-r2-001` | Product Scope | `别把 WW/WX 算进来` 未作为身份排除，三个共享前缀配置一起进入歧义 Scope | 安全澄清，无错误推荐 |
| `laptop-r2-002` | Constraint | 查询中的 Part Number 被额外激活为购买硬约束 | 候选正确，严格任务评分失败 |
| `laptop-r2-003` | Constraint | 型号别名中的 `OLED` 被误提取成购买硬约束 | 候选正确，严格任务评分失败 |
| `laptop-r2-005` | Product Scope | Family 查询没有用显卡/显存条件收敛为唯一配置，提前进入身份澄清 | 错误空结果 |
| `laptop-r2-006` | Product Scope | 安全地请求澄清，但实际类型为 `ambiguous_product_scope`，与冻结的 `product_family` Scope 不同 | 无错误推荐 |
| `laptop-r2-007` | Constraint | 识别分辨率但漏掉 16GB 内存约束 | 候选碰巧正确，约束契约失败 |
| `laptop-r2-008` | Product Scope | 安全地请求地区澄清，但 Scope 类型和 32GB Proposal 未达到金标 | 无错误推荐 |
| `laptop-r2-009` | Constraint | `只接受 CA、排除 US` 未形成两条地区约束，事实路由没有执行 Checker | 错误空结果 |
| `laptop-r2-010` | Constraint | 事实核验中的 OLED 字段被误激活为购买约束 | 候选正确，严格任务评分失败 |
| `laptop-r2-011` | Product Scope | `H7606WW 不参与` 未被识别为排除，WW 被加入比较结果 | 错误配置 1、Scope 越界 1 |
| `laptop-r2-012` | Product Scope | `对照` 未形成明确比较，且被排除的 FHD 配置也参与身份解析，最终要求澄清 | 错误空结果 |
| `laptop-r2-013` | Constraint | 候选集合正确，但冻结评分把金标整数 `32` 与运行值 `32.0` 视为不同规范化值 | 无错误推荐，严格类型评分失败 |
| `laptop-r2-014` | Constraint | 候选集合正确，但整数金标与运行时浮点规范化值不同 | 无错误推荐，严格类型评分失败 |
| `laptop-r2-016` | Constraint | 事实查询把 configuration ID 和 Thunderbolt 字段值误当成筛选约束 | 正确拒答，但约束契约失败 |
| `laptop-r2-017` | Constraint | `2T 改为最低 1T` 没有完成覆盖，实际仍保留 2TB | 错误淘汰5个合规候选 |
| `laptop-r2-018` | Tool orchestration | `轻一点、内存大些` 未进入主动澄清，反而执行 KB/Evidence 后拒答 | 澄清绕过 1 |
| `laptop-r2-019` | Product Scope | 作为不可替代参考出现的 CA 配置扩大了目标 US Scope，触发歧义澄清 | 安全澄清，错误空结果 |
| `laptop-r2-020` | Product Scope | 作为反例出现的 H7606WX 扩大了 H7606WI Scope，触发歧义澄清 | 安全澄清，错误空结果 |

证据缺口为4项：`laptop-r2-004` 的 `upgradeability`、`laptop-r2-010` 的 `resolution`，以及 `laptop-r2-011` 中 WI/WX 的两个 `storage_gb` 引用。任务正确和证据覆盖是独立指标，因此 `r2-004` 虽计为任务正确，联合证据门仍失败。

原始结果中每条失败记录的 `safety_failure` 字段只按“首错节点且产生错误推荐”分类，所以 `r2-011` 首错为 Scope 时该字段为 `false`；联合门使用独立的 `wrong_configuration_recommendations=1` 和 `candidate_scope_leakage=1`，本报告据此将它明确认定为安全门失败，没有改写原始结果。

## 6. 工具、延迟与费用

| 模型 | 请求 | 输入 Token | 输出 Token | 估算费用 | 平均 Provider 延迟 |
|---|---:|---:|---:|---:|---:|
| qwen-plus | 5 | 12,020 | 1,365 | ¥0.012346 | 6,359.215 ms |
| text-embedding-v4 | 13 | 464 | 0 | ¥0.000232 | 114.164 ms |
| qwen3-rerank | 13 | 81,573 | 0 | ¥0.0407865 | 243.308 ms |
| 合计 | 31 | 94,057 | 1,365 | **¥0.0533645** | — |

- 端到端平均延迟：2,177.865 ms；P95：8,907.865 ms。
- Provider 重试：0；错误：0；所有31次请求均为首次尝试成功。
- 热缓存命中：0；主评测明确使用冷缓存。
- Checkpoint 恢复：0；进程未中断，Journal 正好20条且顺序完整。
- Source Search、Web Extractor、Open Research：0次。
- qwen-plus 仅在确定性规则认为需要回退时调用，因此为5次，不是每任务1次。

## 7. JavaScript 11/12 口径审计

- Git 实际跟踪 JavaScript：12个。
- 全仓库排除 `.venv`、`node_modules` 等生成目录后：12个。
- WebUI 目录：11个。
- 第12个是上游文档资产 `vendor/youtu-rag/docs/public/assets/js/i18n.js`。
- R1 的12/12采用全仓库口径；R2A 的11/11只扫描 WebUI 目录。相对R1基线没有 JavaScript 删除、移动或修改。
- 本轮质量门统一检查全仓库12个文件。

## 8. 边界与后续条件

- 本次20条是代码冻结后创建并单次运行的第二验证集，不是第三方盲测。
- 冻结 Holdout 文件仍保留其初始 `frozen_unrun/run_count=0` 内容；真实运行次数由不可覆盖 RC、Journal 和首次结果记录为1，避免修改评测输入自身。
- 结果显示当前实现对反例身份提及、Family 条件收敛、事实字段与购买约束分离、数值规范化和自然语言覆盖语义仍不稳定。
- 若进入修复轮，只能把本次20条标记为已暴露回归，另建修复提交和定向回归；不得重跑并覆盖本次首次结果。
- 当前不满足恢复 V2-6C 后续功能的质量条件，需要用户另行授权根因修复阶段。

## 9. 运行后质量门

| 检查 | 结果 |
|---|---:|
| CI 等价全量离线测试 | 346/346 |
| V1 Tag 原始18个测试文件 | 94/94 |
| Monitor V2 回归 | 35/35 |
| V2-5C Proposal/Quote/澄清回归 | 48/48 |
| Laptop 工具链、身份与 Candidate Scope | 53/53（8 + 45） |
| Ruff / Compileall | 通过 / 通过 |
| 全仓库 JavaScript | 12/12 |
| PowerShell AST | 5/5 |
| Markdown 相对链接 | 359/359 |

全量测试的3条警告均为既有第三方弃用警告。测试子进程显式清空模型与搜索 Provider 环境变量；HTTP 日志来自受控 MockTransport，没有新增收费调用。敏感信息、禁止产物、Git 差异和暂存范围在提交前再次检查。
