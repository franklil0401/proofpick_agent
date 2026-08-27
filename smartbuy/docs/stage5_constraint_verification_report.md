# 阶段 5 确定性硬约束复核技术报告

最后更新：2026-08-27

状态：实现与阻断验收完成，等待用户验收

范围：ConstraintSet、来源门禁、完整候选池只读复核、LLM 后置排序权限、SSE/Monitor、自然用例与独立故障注入消融

## 技术结论

阶段 5 已在 ReAct 与最终报告之间建立不可由 LLM 跳过的确定性安全门。Agent 继续负责需求理解、工具规划和证据收集；Checker 从工具累计的完整候选池、只读 SQLite 和 `evidence_records` 独立复核；最终推荐只能来自 `eligible_model_ids`。模型臆加的预算、品牌、尺寸或软转硬条件会被 provenance gate 拒绝，模型对合规集合的增删也会被代码纠正。

全部阻断门槛通过：自然硬约束套件字段 55/55、任务 10/10；故障注入字段 21/21、任务 12/12、违规拦截 12/12；unknown/conflict 6/6、unsupported 2/2、重复执行 12/12；合规候选误杀为 0。`s4-014` 通过本地 Agent 集成回归，用户未提出的尺寸没有进入约束，正确候选由完整池恢复。

在线结果没有被包装成一次完美运行：首次完整 16 条 E2E 为 13/16，安全门完整性 16/16；3 个失败逐项修复后，`s4-004`、`s4-007` 在首轮定向回归通过，`s4-012` 的最终定向回归通过并形成成功的 SQL→KB→Evidence 依赖链。原始完整结果和两轮中间失败均保留在仓库中。

## 指标定义与方法

- 字段级硬约束正确率：实际字段四态与预先写入 JSONL 的金标状态一致数 / 全部金标字段检查数。
- 任务级硬约束正确率：实际 `eligible_model_ids` 与金标集合完全相等的任务数 / 全部任务数。
- 违规候选拦截率：金标不合规候选中未进入 `eligible_model_ids` 的数量 / 全部金标不合规候选。
- 合规候选误杀率：金标合规候选中未被保留的数量 / 全部金标合规候选。
- unknown/conflict 处理率：应为 unknown 或 conflict 的字段被正确标记，且候选未成为完全满足的数量 / 全部此类字段。
- unsupported 识别率：未支持/歧义约束被显式列入候选结果的数量 / 全部此类约束。
- 确定性重复率：同一 `ConstraintSet`、候选池、数据库和固定 `as_of` 连续执行，两份序列化结果字节相同的任务数 / 全部任务。
- 安全门完整性：任何最终推荐均为 Checker 合规候选；购买推荐任务还必须保留全部合规候选，LLM 只能改变顺序。
- A/B 固定池消融：A 使用阶段 4 已保存输出，B 对同一数据版本、同一问题和同一已保存工具候选池运行 Checker，不重跑或削弱 A。
- 图表选择：样本是 10、12、16 条离散审计用例，精确分子/分母表比趋势图更便于逐案复核，因此不绘图。

## 实现与安全边界

### 约束与来源

`ConstraintNormalizer` 支持价格、尺寸、分辨率、刷新率、OLED、USB-C、视频、供电、宽度、品牌和支架。当前输入、会话确认、长期偏好、系统默认具有固定优先级；取消表达可关闭记忆条件。每条约束保留原文、轮次、来源、置信度和支持状态。模型建议只有与已解析用户约束的字段、操作符、值和硬/软属性全部一致时才可关联，否则只进入 `rejected_model_constraints` 审计字段。

### 完整候选池与 Checker

SQL 行、KB 命中和 Evidence Check 型号会累计到 `candidate_pool_rows`，不会用最后一次工具结果覆盖。Checker 在 ReAct 结束后由运行时直接调用，不暴露成 Tool Schema。SQLite 使用 `mode=ro`、`query_only`、authorizer 和参数化字段读取；错误/重复/未知型号 fail closed。字段必须有同型号、同地区证据，结构化值与证据不一致或存在冲突组时返回 `conflict`。

### LLM 权限与报告

LLM 排序只接收 Checker 的合规集合和受支持软偏好。运行时删除模型添加的集合外型号，并自动补回模型遗漏的合规型号。`DecisionReport v2` 保存 ConstraintSet、完整 VerificationBatch、字段实际/要求值、证据/来源 ID、版本、语义指纹、延迟和降级；推荐集合由代码生成。

### SSE 与 Monitor

API 透传 `constraint_check_started` 与 `constraint_check_completed`。WebUI 卡片显示每个候选的 passed/failed/unknown/conflict、违规/未知/冲突字段、实际值、用户要求和证据 ID。Monitor 只保存有界候选摘要、Checker 版本、降级状态和平均延迟；不保存 API Key、Authorization、完整 Prompt 或隐藏思维链。

## 固定候选池评测

### 新增自然硬约束用例

| 指标 | 分子/分母 | 结果 |
|---|---:|---:|
| 字段级硬约束正确率 | 55/55 | 100% |
| 任务级硬约束正确率 | 10/10 | 100% |
| 违规候选拦截 | 12/12 | 100% |
| 合规候选保留 | 9/9 | 100% |
| 合规候选误杀 | 0/9 | 0% |
| unknown/conflict | 3/3 | 100% |
| 重复执行一致 | 10/10 | 100% |
| Checker 平均/P95 | 10 条 | 1.332 / 1.994 ms |

用例覆盖预算、尺寸、分辨率、刷新率、OLED、USB-C 视频、供电、宽度、品牌、支架、边界值、缺失价格和证据冲突。所有边界比较均包含等号。

### 独立故障注入

| 指标 | 分子/分母 | 结果 |
|---|---:|---:|
| 字段级硬约束正确率 | 21/21 | 100% |
| 任务级硬约束正确率 | 12/12 | 100% |
| 故意违规候选拦截 | 12/12 | 100% |
| unknown/conflict | 6/6 | 100% |
| unsupported | 2/2 | 100% |
| 重复执行一致 | 12/12 | 100% |
| Checker 平均/P95 | 12 条 | 0.966 / 1.402 ms |

这 12 条只用于安全门攻击与边界验证，包含超预算、尺寸不符、OLED、分辨率、USB-C、视频、供电、宽度、null、来源冲突、多字段违规和未支持约束。它们没有混入自然 E2E 指标，也不用于声称自然任务提升。

### 阶段 4 固定池 A/B

| 指标 | A：阶段 4 Agentic RAG | B：+ Checker |
|---|---:|---:|
| 适用硬约束任务 | 12 | 12 |
| 任务级硬约束正确 | 10/12（83.33%） | 12/12（100%） |
| 推荐候选字段检查 | 30/30（100%） | 47/47（100%） |
| 合规候选误杀 | 3/10（30%） | 0/10（0%） |
| 恢复合规候选 | — | 3 |
| 移除错误推荐 | — | 0 |
| 候选池一致 | — | 12/12 |

字段检查分母不同，因为 A 已提前误杀部分合规候选；不能把 A 的 30/30 解读为完整候选池安全。B 恢复 3 个候选，正是完整池复核带来的差异。

## 在线 E2E 与失败保留

### 4 条 dry run

4/4 端到端通过；工具选择、型号召回、拒答、多跳、Schema 和安全门完整性均为 100%。平均/P95 总延迟 31.897/43.585 秒，Checker 平均/P95 1.877/2.751 ms。45 次账本调用，估算 ¥0.1627041。

### 首次完整 16 条

| 指标 | 结果 |
|---|---:|
| 工具选择 | 15/16（93.75%） |
| 型号召回 | 100% |
| 拒答标签 | 14/16（87.5%） |
| 多跳 | 100% |
| Schema | 16/16（100%） |
| 安全门完整性 | 16/16（100%） |
| 端到端 | 13/16（81.25%） |
| 平均/P95 总延迟 | 28.626 / 49.200 秒 |
| Checker 平均/P95 | 2.014 / 4.975 ms |

原始失败：

- `s4-004`：模型在有界循环内漏掉 Evidence Check。修复为只有在已取得候选和 KB 命中后执行一次白名单、本地、公开可审计的 Evidence 回退；不会调用 LLM 或伪造结论。
- `s4-007`：无关浇水器问题被错误地用 KB 命中判断“证据充分”。修复为 `unrelated` 无条件拒答。
- `s4-012`：60W/65W 字段冲突被误判为商品比较，后续还出现成功工具顺序 Evidence→KB→SQL。修复为事实冲突，并用依赖守卫强制成功链 SQL→KB→Evidence；提前调用失败会保留公开轨迹。

首轮三条定向回归中 `s4-004` 和 `s4-007` 通过，`s4-012` 已正确拒答但暴露工具顺序问题；最终单条回归中 `s4-012` 工具、召回、拒答、多跳、Schema、安全门和 E2E 均为 1/1。未再次全量运行，因此不把当前代码虚报为“同一次 16/16”。

最终 `s4-012` 的公开审计轨迹为：

| 步骤 | 工具 | 状态 | 父步骤 | 公开解释 |
|---:|---|---|---:|---|
| 1 | set_requirements | success | — | 建立事实冲突任务和必要字段 |
| 2 | evidence_check | failed | 1 | 依赖守卫拒绝没有 SQL/KB 前置的越序调用 |
| 3 | text2sql | success | — | 只读定位 PD2705U 稳定型号与结构化字段 |
| 4 | kb_search | success | 3 | 按 SQL 候选检索官方来源 |
| 5 | evidence_check | success | 4 | 识别 60W/65W 冲突并拒绝完全满足 |
| 6 | finish_decision | success | — | 输出冲突、证据与拒答 |

轨迹只含工具、脱敏参数摘要、公开结果和依赖，不含模型自由文本或隐藏思维链。

## 成本与延迟

- Checker 本身：0 次 API 调用，0 元模型成本。
- 阶段 5 保存的在线 dry run、完整 E2E 和定向回归合计 271 次账本调用，1,097,782 input + 26,510 output tokens，估算 ¥0.8967852。
- 没有 401/403 重试、无限循环或超预算批处理；总额低于 10 元阶段上限。
- Checker 固定套件与在线 E2E 延迟均为毫秒级；总任务延迟主要来自 ReAct、Embedding 和 Reranker，阶段 6 再做缓存与重复评测。

## 自动化与质量检查

- 完整回归：76 passed、3 条上游依赖弃用警告。
- Ruff、Python `compileall`、WebUI JavaScript `node --check` 全部通过。
- 自动化覆盖：来源优先级、取消记忆、软转硬、模型臆加预算/品牌/尺寸、别名/单位/否定、边界值、null、冲突、错误/重复型号、Prompt 注入、字节一致、s4-014、报告安全门、SSE/Monitor。
- 评测输出只保存脱敏统计和公开工具轨迹；未保存模型隐藏文本、Key 或 Authorization。

## 局限与下一阶段边界

- 支持字段和自然语言词表是有意收窄的白名单；未支持或歧义表达会 fail closed，需要用户确认。
- 价格只有 4 条历史观察，30 天策略只判断可否用于复核，不代表实时价格；真实 Web Search 尚未实现。
- 首次完整在线 E2E 为 13/16，修复后只做了失败用例定向回归；阶段 6 应在固定温度下重复完整集合，并完成 Direct LLM、Fixed RAG、Agentic RAG、+ Checker 四组对照。
- 当前长期偏好仍是本地单用户 JSON；不是公网多租户存储。
- GraphRAG、Neo4j、第二商品类别和公网部署均未实现，也不属于阶段 5。

## 可复核命令

```powershell
$env:PYTHONPATH="$PWD;$PWD\vendor\youtu-rag"

# 纯本地固定池、自然用例与故障注入；Checker 不调用模型
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_stage5_eval --fixed

# 在线评测会产生费用；必须先 dry run
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_stage5_eval --dry-run
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_stage5_eval --full

# 自动化与静态检查
uv run --project vendor/youtu-rag pytest -q smartbuy/tests `
  vendor/youtu-rag/tests/rag/api/test_config_security.py
uv run --project vendor/youtu-rag ruff check smartbuy
uv run --project vendor/youtu-rag python -m compileall -q smartbuy
node --check vendor/youtu-rag/frontend/rag_webui/assets/js/components/chat.js
```

原始指标文件位于 `smartbuy/data/processed/stage5_*_results.json`；决策边界见 [ADR-0005](adr/0005-deterministic-constraint-gate.md)。
