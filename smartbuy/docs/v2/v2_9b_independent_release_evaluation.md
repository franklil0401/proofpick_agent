# ProofPick V2-9B 独立发布评测报告

## 结论

**发布结论：Needs revision（不通过发布门槛）。**

本轮不建议把 `feature/proofpick-v2` 合并到 `main`，也不建议创建 V2 Tag 或 GitHub Release。原因不是工程不可运行，而是独立新题上的决策质量没有达到冻结门槛：Monitor 为 `18/30`，Headphone 为 `20/30`，硬约束字段 F1 为 `75.49%`，困难负例/证据不足任务正确率为 `11/18`。Laptop 达到 `26/30`，但不能抵消另外两个品类和跨品类联合安全门的失败。

同时，项目的确定性安全边界仍有明确价值：推荐越过 Checker 合规集合为 `0`，公开结果越过 Candidate Scope 为 `0`，`unknown/conflict` 被写成满足为 `0`；联网取证产生的 28 条 Open Evidence 进入 Trusted Checker 为 `0`。因此当前状态更准确地描述为：**安全边界基本成立，但自然语言理解、候选收敛、主动澄清和开放检索覆盖率尚不足以发布。**

机器可读摘要见 [`v2_9b_independent_summary.json`](../../eval/results/v2_9b_independent_summary.json)，首次完整结果见 [`Trusted 首测`](../../eval/results/v2_9b_independent_trusted_first.json)和[`Online RC2 首次完整运行`](../../eval/results/v2_9b_independent_online_first_rc2.json)。

## 评测对象与独立性

| 项目 | 冻结值 |
|---|---|
| Release Candidate | `proofpick-v2-9a-rc1` |
| 生产 Commit | `dac24123b82683c6708f0d487d9ab9753b172aed` |
| 生产 Tree | `14c25152d30e96a01f7f9face88757f367153a08` |
| RC Manifest Commit | `383df1783328ad6859729c6770fb1a8cea3f648b` |
| RC Payload SHA-256 | `7db3b3a63011848b260c06ea98e6cf9b5e874267df298c042ac56760f8d2c5f5` |
| V1 稳定 Commit / Tag 目标 | `d51b6668a6a45c1b01ef4e64da3c4b9ac84ed10c` |
| 独立评测分支 | `eval/v2-9b-independent` |

评测方没有参与 V2 生产代码实现。题集、Schema、评分规则和运行器在首次 E2E 前冻结并提交；所有运行使用冻结生产 Tree。评测分支只新增 `smartbuy/eval/v2_9b_independent/`、对应首次结果和本报告，没有修改 Agent、Prompt、工具、Checker、Domain/Product Pack、治理数据、索引定义或历史评测。

RC Manifest 的 Payload 哈希可按文档算法复现。`uv.lock` 在 Windows 工作区的原始字节因 CRLF 与 Manifest 不同，但 LF 规范化后的 SHA-256 为 `8e2e8897...94d8`，与 Manifest 一致。Manifest 中四组 aggregate hash 只给出数量与聚合算法，没有列出成员文件，独立评测无法仅凭 Manifest 精确重建成员集合；这是可审计性缺口，不代表已观察到资产篡改。

## 评测集与金标质量

首次运行前冻结：

- Trusted：90 条，Monitor/Laptop/Headphone 各 30 条，SHA-256 为 `22768b4c...397a`。
- Online：RC2 为 15 条、每品类 5 条，SHA-256 为 `1032b085...dd2`。
- 与仓库历史评测问题的逐字重复：0。
- 治理商品：36 个。
- 金标证据对：297 个，校验 `297/297`。
- 候选与约束确定性复核：171 个，校验 `171/171`。
- JSON Schema、case_id、品类分布、商品 ID、字段、Evidence ID：未发现错误。

Trusted 题型包括 36 条精确事实、24 条全库筛选、12 条显式比较和 18 条拒答/澄清任务。运行时关闭热缓存，使用默认 ReAct 编排器，独立会话和用户 ID，不复用长期偏好。

## Trusted 首次运行

Run ID：`v2-9b-independent-20260904T073443Z-81d6b7f6`。完成 `90/90`，没有恢复 Checkpoint，没有重放已完成任务，也没有针对结果修改 Prompt、规则或金标。

### 核心指标

| 指标 | 冻结门槛 | 首次结果 | 结论 |
|---|---:|---:|---|
| Monitor 任务正确率 | ≥80% | 18/30（60.00%） | 未通过 |
| Laptop 任务正确率 | ≥80% | 26/30（86.67%） | 通过 |
| Headphone 任务正确率 | ≥80% | 20/30（66.67%） | 未通过 |
| 总任务正确率 | 仅报告 | 64/90（71.11%） | — |
| 硬约束字段 F1 | ≥90% | 75.49% | 未通过 |
| 约束 Operator/Value 精确率 | 仅报告 | 75/88（85.23%） | — |
| 推荐与事实 Evidence 覆盖 | ≥95% | 276/297（92.93%） | 未通过 |
| 困难负例/证据不足正确率 | ≥90% | 11/18（61.11%） | 未通过 |

硬约束字段混淆矩阵为 `TP/FP/FN = 77/39/11`，Precision/Recall 为 `66.38%/87.50%`。平均端到端延迟为 `8.296s`，P95 为 `31.368s`。

### 按题型观察

| 题型 | 正确/总数 | 正确率 |
|---|---:|---:|
| 精确事实 | 32/36 | 88.89% |
| 全库条件筛选 | 15/24 | 62.50% |
| 显式多商品比较 | 6/12 | 50.00% |
| 模糊身份主动澄清 | 0/4 | 0% |
| 模糊条件主动澄清 | 2/5 | 40.00% |
| 明确无匹配 | 4/4 | 100% |
| 已知违规、未知价格、未知字段、未支持字段 | 5/5 | 100% |

26 条失败中，Monitor 12 条、Laptop 4 条、Headphone 10 条。最集中的失败不是向量检索报错，而是以下上游语义问题：

1. 把“查询某字段”错误激活成购买硬约束，导致 39 个字段级 FP，并影响精确事实和比较任务。
2. 漏掉宽度、重量、分辨率、面板、地区等限制，Checker 只能对错误或不完整的 ConstraintSet 做正确计算，最终候选过宽。
3. 多商品比较时只保留一个配置，或证据只覆盖比较对象的一侧。
4. `U272 系列`、`XPS 13`、`Sony XM5`、`Nova Pro Wireless` 等不唯一身份没有稳定暂停澄清。
5. “尺寸别太大”“刷新率高一点”“续航久一点”等缺少阈值的表达有 7 条绕过澄清。

需要特别区分：Checker leakage 为 `0`，说明最终推荐没有越过 Checker 输出；但如果 Parser/Scope 提供了不完整条件，Checker 仍可能放行不符合用户原意的商品。Checker 不能替代正确的意图与约束解析。

### 安全指标口径说明

冻结评分器输出的 `wrong_configuration_or_region=36` 实际实现为“eligible 任务中推荐集合减去金标集合”的数量。它包含同地区但违反其他约束的过宽候选，不应全部解释成字面意义上的地区或配置串线。本报告因此称其为 **36 个超出金标的推荐项**，但仍按冻结规则判定安全门失败，不改分母或分数。

`scope_leakage=0`、`checker_leakage=0`、`unknown_overclaim=0`。V2 Laptop/Headphone 的 Scope Envelope 缺失为 0；V1 兼容 Monitor 路径 30/30 没有 V2 Scope Envelope，这是现有架构边界，不冒充统一 V2 Scope 已覆盖三品类。

### API、成本与稳定性

| 项目 | 结果 |
|---|---:|
| Provider 请求 | 369 |
| qwen-plus | 177 |
| text-embedding-v4 | 96 |
| qwen3-rerank | 96 |
| 输入/输出 Token | 1,627,746 / 24,936 |
| 重试/失败请求 | 0 / 0 |
| 估算成本 | ¥1.2484845 |

## Online / Open Research 首次运行

### RC1 评测器事故

原 Online RC1 运行到 `web-mon-001` 后，独立评测器把 `UsageLedger.summary()` 的公开字段 `call_count` 错写为 `request_count`，抛出 `KeyError`。没有形成聚合结果或临时 Evidence；该错误属于评测器，不属于生产代码。事故被保存在[`harness failure`](../../eval/results/v2_9b_independent_online_harness_failure.json)，没有把该任务重跑成“首次结果”。

随后冻结 Online RC2：只用新题 `web-mon-006` 替换已触达的 `web-mon-001`，其余 14 条保持不变。RC2 的运行器、题集、Manifest 和哈希在运行前再次提交。

### RC2 首次完整结果

Run ID：`v2-9b-online-rc2-20260904T075343Z-a0a6bf48`。

| 指标 | 结果 |
|---|---:|
| 安全终止 | 15/15（100%） |
| 实际完成搜索、正文提取与 Evidence 生成 | 2/15（13.33%） |
| `no_official_source` | 9/15 |
| `no_region_matched_source` | 4/15 |
| 被接受的官方候选 | 2 |
| 被接受来源的域名/型号/地区精度 | 2/2（100%） |
| 产生 Open Evidence 的任务 | 2/15 |
| Open Evidence / 已核验字段 | 28 / 6 |
| Open Evidence 进入 Trusted Checker | 0 |
| Search 调用/成功 | 28/28 |
| 估算成本 | ¥1.10 |

Monitor 实际取证为 `0/5`，Laptop 为 `1/5`，Headphone 为 `1/5`。因此 `15/15` 只能描述为 **安全处理率**，不能写成联网搜索成功率；`accepted_source_precision=100%` 的真实分母是两个被接受来源，而不是 15 个任务。系统宁可返回 `no_official_source` 或 `no_region_matched_source`，也没有放宽官方域名、型号、地区和 Open/Trusted 边界，这是安全性优点，同时也暴露出搜索覆盖率偏低。

## 工程、故障与 Windows 复现

独立 ASCII 路径克隆使用 Python 3.12.3、uv 0.12.3 和冻结的 296 个依赖。仓库外完成三品类 SQLite 与真实 1024 维索引构建：Monitor 60 chunks，Laptop/Headphone 各 12 chunks；构建成本约 ¥0.015586。

| 检查 | 结果 |
|---|---:|
| CI 等价离线测试 | 467/467 |
| V1 原始测试 | 94/94 |
| 故障/降级关键词专项回归 | 67/67 |
| 五个固定 Demo | 5/5，API 调用 0 |
| Ruff / Compileall | 通过 / 通过 |
| JavaScript / PowerShell AST | 13/13 / 6/6 |
| HTTP | 首页、Health、Monitor、Capabilities、MinIO、Offline Replay 均 200 |
| Stop 后端口 | 8000、8088、9000、9001 全部释放 |

故障专项覆盖 Provider 401/403 不重试、429/503/超时有界处理、Reranker 降级、索引发布回滚、损坏 Pack/Memory/临时 Evidence、Checker/编排异常 fail closed。它们是确定性回归测试，不等价于新的一次端到端故障 Holdout；当前 RC 已因核心发布门失败，因此没有继续产生额外收费故障实验。

一次从仓库根直接裸跑 `pytest` 因缺少 CI 的 `PYTHONPATH` 且误收集需 Docker/外部配置的上游测试而在收集阶段失败。按 `.github/workflows/ci.yml` 的正式命令重跑后为 467/467。首次在包含中文的长路径启动也暴露 `utu` 导入失败；切换到短 ASCII 路径并使用 `powershell -NoProfile` 后，Preflight、Bootstrap、HTTP 和 Stop 全部通过。这是 Windows 复现约束，建议在 README 中明确强调。

## 未执行的对照项

V2 流程文档要求 Direct LLM、Fixed RAG、V1 Agentic RAG、V2 增强组使用同一数据版本比较。本轮没有给出新的四组数字，原因有二：

1. V1 只支持 Monitor，当前没有在首次运行前冻结的 Laptop/Headphone V1 适配器；强行把“不支持”编码成 0 分或临时增加适配器都会改变比较含义。
2. 当前 RC 已经未通过发布必要门槛，继续发起大量付费基线调用不会改变“不发布”的决策。

因此历史 V1 `92/120`、V2-8 `27/30` 等结果只作为历史背景，不与本次新题直接横向比较。若后续 RC 要宣称“相对 Direct/Fixed/V1 提升”，必须先单独冻结共享数据、能力缺失处理规则、Prompt、检索 Top-K、费用和评分器，再做一次不可覆盖的对照实验。

## 已知总成本

Trusted ¥1.2484845 + Online RC2 ¥1.10 + 三索引 Bootstrap ¥0.015586，已知合计为 **¥2.3640705**。Online RC1 评测器中止后无法从退出进程恢复 Provider 用量，因此该次可能产生的费用标为 unknown，不并入精确合计。静态检查、回归、Demo Replay 和 HTTP 启停没有产生额外模型调用。

## 修复优先级与下一次 RC 条件

建议开发 Agent 不要修改或重跑本次 90+15 条首次集来宣称通过；它们从现在起只能作为 exposed regression。修复顺序：

1. 分离 `fact_query`、`comparison` 与 `purchase_filter`，禁止把被询问字段自动激活成硬约束。
2. 让 Candidate Scope 与 ConstraintSet 共享同一身份/地区/排除项结果，并加入“只能单调收窄”的运行时断言。
3. 为模糊型号和无阈值形容词建立稳定的 `pending clarification` 门，暂停前工具调用必须为 0。
4. 比较任务强制检查“所有指定对象 × 所有指定字段”的 Evidence 闭包，不能只返回一侧证据。
5. 提高 Source Search 的官方页面召回，但继续保留域名、型号、地区校验与 Open/Trusted 隔离。
6. 给 RC Manifest 的每个 aggregate hash 增加排序后的成员路径清单，并在 Windows 指南中明确短 ASCII 路径和 `-NoProfile`。
7. 修复后先跑本次 exposed regression；再由未参与修复的评测方创建第三套全新、未审阅的发布集。新 RC 必须重新冻结生产 Commit/Tree、Prompt、工具、数据、索引、评分器和成本上限。

在新的独立发布集同时满足每品类 ≥80%、硬约束 F1 ≥90%、Evidence ≥95%、困难负例 ≥90%、所有越界/澄清绕过为 0，并完成可比较的四组实验之前，不应把 V2 描述为最终发布版本。

## 发布动作

- PR：未创建。
- 合并到 `main`：未执行。
- V2 Tag / GitHub Release：未创建。
- V1 `main` 与 `v1.0.0-portfolio`：未修改。
- 建议状态：保持 `feature/proofpick-v2`，从本报告创建修复任务；评测分支只保留不可变证据。
