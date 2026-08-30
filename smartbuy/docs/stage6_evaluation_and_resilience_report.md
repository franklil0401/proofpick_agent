# 阶段 6：评测、可观测性、缓存与韧性报告

最后更新：2026-08-27
结论：阶段 6 完成；首次失败、评分修复、调度重复和定向回归均单独保留。
配置哈希：`c5001c9707c5cb7302c26745407cf989676e832b6984109604dec829754ab096`

## 1. 结论先行

在冻结的 40 条自然任务首次运行中，四组端到端完成率为：Direct LLM 16/40、Fixed RAG 17/40、Agentic RAG 28/40、Agentic RAG + Constraint Checker 31/40。增强组相对 Agentic RAG 增加 3 个完成任务，将违规候选推荐从 10/38 降为 0/43，并把任务级硬约束满足从 22/30 提升到 24/30。

三次共 120 个预测/组时，增强组端到端为 92/120，Agentic RAG 为 81/120，Fixed RAG 为 51/120，Direct LLM 为 46/120。增强组最终候选集合一致率为 40/40，Agentic RAG 为 35/40；相同固定输入下 Constraint Checker 三次字节一致为 40/40、API 调用和成本均为 0。

结果也暴露了真实边界：首次 holdout 中增强组只有 15/24；Fixed RAG 三次出现 28 个结构化参数 JSONDecodeError；C/D 各有 12 个由 Evidence Check 分辨率比较触发的 ValueError。修复后对 4 条相关 holdout 的独立定向回归中，D 为 4/4、候选召回/精度 13/13，C 为 1/4；首次主指标未被覆盖。

## 2. 实验问题与四组定义

| 组 | 能力边界 |
|---|---|
| A Direct LLM | 仅 `qwen-plus` 直接生成结构化答案；无 KB、SQL、Reranker、Memory、Checker |
| B Fixed RAG | 固定向量 Top-30、`qwen3-rerank` Top-5，再由 `qwen-plus` 生成；无 SQL、ReAct、Memory、Checker |
| C Agentic RAG | 阶段 4 的 ReAct、KB Search、Text2SQL、Evidence Check、多跳；关闭最终 Checker |
| D Agentic RAG + Checker | 完整阶段 5 链路；Checker 后 LLM 只能在合规集合内排序和解释 |

四组共享 `qwen-plus`、`temperature=0`、最大输出 800、30 秒请求超时、数据 `monitor-cn-2026-08-26-v1`、索引 `monitor-fact-card-h2-v1`、地区 CN 和 `as_of=2026-08-27T00:00:00Z`。接口未声明 seed，因此不宣称 LLM 完全确定。

## 3. 数据集冻结

- 自然 E2E：40 条，其中 regression 16、holdout 24。
- 自然集 SHA-256：`6082ac83d72441fedf7ac3083a3c53f31d538ca54216f2cf99d3a9de5068e0ef`。
- Memory：5 条，SHA-256 `ac84cf52fab59ba3392e4d11e97f2572b16187eafc0e8d0a184079beb442f4c0`。
- 故障注入：13 条，SHA-256 `73946eaa9441832dec6fd083b88b168c6a5aca1ee0df8546d0eb2de6d240a999`。
- 数据与索引源哈希见 [`stage6_config.json`](../eval/stage6_config.json)。首次完整运行后未改自然任务或金标。

## 4. 首次 40 条主结果

| 指标 | A Direct | B Fixed RAG | C Agentic | D + Checker |
|---|---:|---:|---:|---:|
| 端到端完成 | 16/40 | 17/40 | 28/40 | **31/40** |
| 正确候选召回 | 0/41 | 20/41 | 21/41 | **25/41** |
| 推荐候选精度 | 0/3 | 20/41 | 21/50 | **25/45** |
| 任务级硬约束满足 | 1/30 | 8/30 | 22/30 | **24/30** |
| 合规候选误杀 | 41/41 | 21/41 | 20/41 | **16/41** |
| 违规候选推荐 | 39/39 | 31/57 | 10/38 | **0/43** |
| 拒答准确率 | 18/40 | 27/40 | 30/40 | **33/40** |
| 拒答 Precision / Recall / F1 | .4211 / 1 / .5926 | .5882 / .625 / .6061 | .6364 / .875 / .7368 | **.7368 / .875 / .8000** |
| unknown/conflict 正确处理 | 1/5 | 4/5 | **5/5** | 3/5 |
| unsupported 识别 | 0/3 | 3/3 | 3/3 | 3/3 |
| Recall@5 | N/A | 22/25 | **27/28** | 26/28 |
| nDCG@5 | N/A | .867299 | **.931546** | .900000 |
| 关键证据覆盖 | 0/71 | 38/71 | 56/71 | 56/71 |
| 错型号/地区引用 | 4/4 | 6/88 | **0/808** | **0/638** |
| 工具选择正确 | N/A | N/A | 33/40 | 33/40 |
| 依赖式多跳完成 | N/A | N/A | 19/23 | 19/23 |

解释边界：D 的 Retriever 指标不必然高于 C，因为两组仍由独立 LLM 路由产生查询和候选池；Checker 的职责是阻止不合规推荐，而不是提高向量排序。D 的 unknown/conflict 3/5 低于 C 的 5/5，是后续需要改善的报告层问题。引用正确率按严格 `gold_evidence_ids` 计分，C/D 分别为 56/808、56/638；大量可访问但不在该 case 最小金标集合中的引用被计为非金标，因此不应把该值解释为“93% 引用造假”。无依据外部事实比例 C/D 为 75/879、57/691，仍需阶段 7 演示报告收敛冗余字段。

### Regression 与 Holdout

| Split | A | B | C | D |
|---|---:|---:|---:|---:|
| regression（16） | 9/16 | 6/16 | **16/16** | **16/16** |
| holdout（24） | 7/24 | 11/24 | 12/24 | **15/24** |

阶段 6 开始时另用当前代码重跑阶段 4 原 16 条，得到 16/16；阶段 4 原始 15/16、阶段 5 首次 13/16、阶段 5 定向修复与本次 16/16 是不同时间点，未合并为一次实验。

## 5. 三次重复稳定性

| 指标 | A | B | C | D |
|---|---:|---:|---:|---:|
| 三次聚合 E2E | 46/120 | 51/120 | 81/120 | **92/120** |
| 最终候选集合一致 | 29/40 | 37/40 | 35/40 | **40/40** |
| 拒答一致 | 38/40 | 39/40 | 37/40 | **39/40** |
| 排名 Jaccard | .800000 | .925000 | .936458 | **1.000000** |
| 工具路径一致 | N/A | N/A | 33/40 | 33/40 |
| 工作流 Checker 指纹一致 | N/A | N/A | N/A | 32/40 |

工作流指纹 32/40 包含 LLM 路由和候选池输入变化，不能解释为 Checker 自身只有 80% 确定。固定首次增强组观察候选池、query 和 `as_of` 后，Checker 每条连续执行三次，字节一致为 40/40。

## 6. 延迟、Token 与成本

| 首次 40 条 | 平均延迟 | P50 | P95 | input / output tokens | 估算成本 |
|---|---:|---:|---:|---:|---:|
| A | 1.573s | 1.530s | 1.890s | 19,380 / 2,422 | ¥0.0203480 |
| B | 5.340s | 4.876s | 12.201s | 200,314 / 8,494 | ¥0.1422808 |
| C | 27.498s | 29.989s | 50.947s | 1,625,811 / 43,460 | ¥1.3594063 |
| D | 24.802s | 27.783s | 41.328s | 1,650,617 / 38,425 | ¥1.3712829 |

C/D Provider 延迟中 `qwen-plus` 占 98.79% / 98.62%；工具内部耗时中 KB Search 占 99.21% / 99.29%。Checker 本身不调用模型。四组 480 个唯一预测估算 ¥8.57293。

阶段 6 全部活动可审计成本下限为 ¥11.4491691，包含阶段 4 当前代码回归、两次 smoke、唯一主实验、调度重复、缓存、一次诊断和定向回归。旧错误路径在响应完成后 JSON 解析失败时未保存该次 usage，故不能声称这是精确云账单；结合各分片最终 Provider 进度与定向诊断，保守估算小于 ¥13，低于 ¥20 阶段上限。详见 [`stage6_cost_summary.json`](../data/processed/stage6_cost_summary.json)。

## 7. 缓存

5 条公共 KB 查询在冷路径平均/P95 为 1441.682/5812.424ms，热路径为 10.436/10.721ms，平均加速 138.15×；热缓存命中 5/5，冷路径 0/5，输出逐条完全一致 5/5。全局缓存统计命中 5、未命中 15，是因为冷 KB 的工具结果、Embedding 和 Rerank 分层分别计数。动态价格查询连续两次均未命中，证明默认绕过；缓存 API 成本 ¥0.0087495。

该样本只有 5 条，不能外推生产 SLA。主四组实验为 cold/no-cache，缓存结果未用于主组间比较。

## 8. 故障注入与 Memory

- 故障注入 13/13：识别 13/13、重试策略 13/13、预期降级 13/13、静默伪装 0、敏感泄露 0。
- 覆盖 Reranker 503、LLM 429、401/403、Embedding 有/无缓存、非法 SQL、SQLite/Chroma 不可用、Memory 损坏/关闭、Web unavailable、Checker fail-closed、ReAct 上限和缓存损坏；401 与 403 各自都只尝试 1 次。
- Checker 异常时合规集合为空，不输出购买推荐。
- Memory 首次 4/5；`m6-002` 暴露“预算改成 2500 元”未覆盖旧预算，修复后 5/5。首次文件单独保留。

## 9. 首次失败、修复与审计

1. 首次 smoke 完成 12 个在线预测后，Scorer 因空地区表达式执行 `int(None)` 失败；保存 [`stage6_smoke_initial_failure.json`](../data/processed/stage6_smoke_initial_failure.json)，修复后 smoke 有效。
2. 首次完整评分发现 Fixed RAG 模型级 nDCG 重复计算同型号多个 chunk，出现大于 1；保存初始结果 SHA-256 和错误数值，按首次 model_id 去重后零调用重算。
3. 首次主实验中 Fixed RAG 出现 28/120 JSONDecodeError；C/D 各出现 12/120 ValueError。后者定位为 Evidence Check 对分辨率字符串执行浮点比较。
4. 修复分辨率比较后，4 条相关 holdout 的 C/D 定向回归无 ValueError：D 4/4、13/13 recall、13/13 precision；C 1/4、6/13 recall、6/6 precision。说明 Checker 能从完整候选池恢复 Agent 过早遗漏，但不能替代上游证据与路由质量。
5. 串行转 repetition 分片时遗留子进程造成 59 个重复 checkpoint 行，其中 49 个内容冲突。原始文件保留在仓库外；仓库提交脱敏哈希审计，最终 480 键按首次出现优先，未选择更好结果。

## 10. 统一账本

[`stage6_unified_ledger.jsonl`](../data/processed/stage6_unified_ledger.jsonl) 共 4,464 条，包含四组模型/工具/最终事件、定向修复回归、缓存、故障、Memory 与 Checker 确定性记录。Schema 字段包括 `run_id/case_id/group/repetition/data_version/config_hash/model/tool/step/parent_step/start/end/duration/status/retry/cache/degraded/tokens/cost/error/final_metrics`，且 `extra=forbid`，没有 Prompt、隐藏思维链、Authorization 或 API Key 字段。

## 11. 有效性威胁与已知边界

- 40 条只覆盖当前显示器数据版本；holdout 在首次完整运行前冻结，但不是外部第三方盲测。
- `qwen-plus` 接口未声明 seed；三次结果衡量的是当前服务行为，不是模型永久属性。
- Fixed RAG 受 800 output tokens 与 Tool Calling JSON 格式稳定性影响，28 次解析失败如实计分。
- 严格 evidence 金标是最小证据集合，不包含所有合法引用，引用正确率会低估“合法但非最小金标”的引用。
- 价格仅来自带 `observed_at` 的 4 条离线观察；不保证实时价格和库存。
- Web Search 仍是 `unavailable/degraded` 接口；未实现真实网页搜索。
- GraphRAG、Neo4j、第二品类和生产 SLA 均未实现。
- 未使用 LLM Judge；自然语言表现未被一个主观 Judge 分数替代。

## 12. 可复现命令

提交前完整项目回归为 89 passed，伴随 3 条来自上游依赖的已知弃用警告。

以下命令从项目根目录运行。在线命令会产生费用；不得输出环境变量值。

```powershell
$env:PYTHONPATH = (Get-Location).Path

# 冻结检查与全部本地故障/Memory
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_stage6_eval --validate-freeze
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_stage6_resilience --all-local

# 四组 smoke；完整三次运行成本较高，checkpoint 可恢复
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_stage6_eval --smoke
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_stage6_eval --full --repetitions 3 --checkpoint C:/ai/smartbuy-stage6/reproduction.jsonl

# 缓存、Checker 确定性与汇总
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_stage6_cache_benchmark
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_stage6_checker_determinism
uv run --project vendor/youtu-rag python -m smartbuy.eval.build_stage6_artifacts
```

## 13. 结果文件

- [`stage6_four_group_results.json`](../data/processed/stage6_four_group_results.json)：480 个唯一预测、首次/聚合/split/稳定性。
- [`stage6_metrics_summary.csv`](../data/processed/stage6_metrics_summary.csv)：首次四组核心表。
- [`stage6_unified_ledger.jsonl`](../data/processed/stage6_unified_ledger.jsonl)：统一脱敏账本。
- [`stage6_cache_results.json`](../data/processed/stage6_cache_results.json)、[`stage6_failure_results.json`](../data/processed/stage6_failure_results.json)、[`stage6_memory_results.json`](../data/processed/stage6_memory_results.json)：专项结果。
- [`stage6_targeted_regression_results.json`](../data/processed/stage6_targeted_regression_results.json)：首次失败修复后的独立回归。
- [`stage6_checkpoint_merge_audit.json`](../data/processed/stage6_checkpoint_merge_audit.json)：重复调度冲突哈希审计。
