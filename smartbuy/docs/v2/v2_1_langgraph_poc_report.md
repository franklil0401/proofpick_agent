# ProofPick V2-1B 隔离 LangGraph PoC 报告

最后更新：2026-08-31

分支：`feature/proofpick-v2`

状态：**PoC 通过；建议采用 LangGraph，但尚未迁移生产编排器**

关联：[实现级设计](v2_1_implementation_design.md)、[PoC 计划](v2_1_langgraph_poc_plan.md)、[ADR-0007](../adr/0007-langgraph-orchestration-decision.md)

## 1. 范围与隔离

PoC 位于 `experiments/langgraph_poc/`，没有被 `smartbuy` 包、FastAPI、WebUI、SSE 主链或正式 Demo 导入。它复用上游冻结环境中已有的 `langgraph==1.0.5`；`pyproject.toml` 和 `uv.lock` 均未修改。

模型路由由 `FakeProvider` 按 fixture 返回，KB/Text2SQL 由本地 Fake Tool 执行。只有确定性 Checker 复用 V1 `ConstraintNormalizer`、测试临时 SQLite 和只读 `CandidateConstraintVerifier`。未读取模型凭据，外部 API 调用、Token 与实际费用均为 0。

## 2. 实现结果

- `StateGraph` 使用 JSON-safe `AgentState`、Reducer、Node 与 Conditional Edge。
- 混合任务并行执行 Text2SQL 与 KB seed，按工具优先级确定性 fan-in；SQL 结果保持完整候选池集合真源。
- fan-in 后按 SQL 候选执行 targeted KB，再进入 Evidence Check 与强制 Constraint Gate。
- 401/403 单次终止；429/5xx/timeout 最多按配置有限重试；失败 ToolResult 不被成功结果覆盖。
- `max_steps`、`max_tool_calls`、总延迟、单工具超时和费用上限均能转入 fail-closed。
- Checkpoint 在 pytest 临时目录保存；跨 Python 进程恢复后不重复已完成的 SQL/KB。
- `interrupt()` 在查询前暂停澄清；恢复节点没有前置副作用。
- Checker 是 `build_report` 和 `safe_refusal` 的唯一前驱；报告节点还会在运行时断言 Checker 已完成。
- 节点事件可映射到现有 `tool_call/tool_output`、`constraint_check_*`、并行组和 `done/error` 语义，且只包含有限公开摘要。

## 3. 20 类测试矩阵

| # | 场景 | 结果 | 关键证据 |
|---:|---|---:|---|
| 1 | 单事实 KB 路由 | 通过 | KB 1、SQL 0、Checker 必执行 |
| 2 | SQL + KB 并行与第二跳 | 通过 | 两分支重叠，合并后 targeted KB |
| 3 | 相似型号/地区 | 通过 | US 版本未被当作 CN 合规候选 |
| 4 | 重复候选合并 | 通过 | 完整池稳定去重 |
| 5 | 冲突证据 | 通过 | `conflict` 保留，未推荐 |
| 6 | KB 失败/不可用 | 通过 | SQL 池保留，降级显式 |
| 7 | SQL 失败 | 通过 | 不用 KB 代替完整池，安全拒答 |
| 8 | Reranker 降级 | 通过 | 保留向量候选并标记 degraded |
| 9 | 重试策略 | 通过 | 401/403 为 1 次；429/5xx/timeout 为有界 2 次 |
| 10 | steps/tools 上限 | 通过 | 达限后 Checker fail closed |
| 11 | 延迟/费用上限 | 通过 | 两类预算均阻断推荐 |
| 12 | Checkpoint 恢复 | 通过 | 跨进程 1/1；SQL/KB 重复 0/2 |
| 13 | Checkpoint 损坏 | 通过 | 拒绝部分加载 |
| 14 | Interrupt 澄清 | 通过 | 暂停前工具 0；恢复 1/1 |
| 15 | Checker 异常 | 通过 | 推荐为空、degraded=true |
| 16 | 绕过攻击 | 通过 | 拓扑和运行时 2/2 阻断 |
| 17 | SSE/Monitor 映射 | 通过 | 事件字段白名单与脱敏断言通过 |
| 18 | V1 代表性回放 | 通过 | 10/10 Checker 金标一致 |
| 19 | V1 16 条 regression | 通过 | 16/16 无新增违规推荐 |
| 20 | 重复/调度乱序 | 通过 | 3/3 候选池和 Checker 指纹一致 |

pytest 参数化后共执行 28 项 PoC 测试，结果为 **28 passed**。没有使用 skip 或降低断言。

## 4. 与 V1 自研 ReAct 的量化对比

| 维度 | V1 自研 ReAct | LangGraph PoC | 判断 |
|---|---:|---:|---|
| 显式 StateGraph/Conditional Edge | 无 | 拓扑与路由测试通过 | 状态/路由更可检查 |
| SQL/KB 并行重叠 | 串行工具循环 | 9/9 | 改善 |
| 40ms + 40ms 负载中位延迟 | 串行参考 83.117ms | 完整图 51.945ms | 降低 37.504% |
| 持久 Checkpoint 入口 | 0 | 跨进程 1/1 | 改善 |
| 已完成 SQL/KB 恢复重复 | 不适用 | 0/2 | 幂等通过 |
| 可恢复 Interrupt 入口 | 0 | 1/1 | 改善 |
| Checker 拓扑/运行时绕过 | V1 由主循环顺序保证 | 2/2 阻断 | 不退化 |
| 额外依赖/锁变更 | — | 0/0 | 无当前迁移成本 |

并行基准使用同一测试数据库、同一约束/Checker、每工具固定 40ms 延迟。串行参考顺序执行相同 SQL/KB、合并和 Checker；并行侧统计整个图，因此结论没有把图开销排除。9 次样本只证明 PoC 行为，不代表生产 SLA。

## 5. 首次失败与修复

首次跨实例 Checkpoint 测试失败：LangGraph 后台 Checkpointer 写入可能并发，测试 saver 复用同一个临时文件名，在 Windows 原子替换时触发文件占用。没有删除或跳过该场景。修复为 saver 内使用重入锁保护内存结构和原子快照，再升级为两个独立 Python 进程的恢复测试；定向结果 1/1，完整 PoC 随后 28/28。

测试 saver 使用受信任临时文件的 pickle 快照，仅用于 PoC。它不是生产持久化方案，损坏文件会被拒绝；任何正式迁移必须改用受支持的 durable saver。

## 6. V1 保护与前端 JavaScript 数量

- V1 完整离线门禁按 CI 口径执行：`smartbuy/tests` 加上游配置脱敏测试，**95 passed，3 warnings**。
- `v1.0.0-portfolio..HEAD` 的业务测试、业务 JavaScript、冻结评测和历史结果均没有变化。
- V1 Tag 与当前分支都跟踪 12 个 `.js` 文件，其中 `vendor/youtu-rag/frontend/` 为 11 个，另 1 个是 `vendor/youtu-rag/docs/public/assets/js/i18n.js`。
- 因此“11/11 → 12/12”来自检查范围由 WebUI 前端目录扩展为全部 Git 跟踪 JavaScript；V1 文档中的 11/11 还常指 Windows preflight 项数。没有新增或修改业务 JavaScript。

## 7. 采用建议、限制与下一步

ADR 结论为：**建议采用 LangGraph**。可验证改善至少包括并行、跨进程恢复和主动澄清三项；Checker 安全门、V1 回放和依赖边界没有退化。

已知限制：

- 只使用 Fake Provider、显示器 V1 fixture 和单机测试 SQLite；未验证真实 LLM 路由、生产并发或生产持久化。
- PoC 事件只验证可映射契约，没有接入现有 SSE/Monitor。
- 并行基准 9 次、Checkpoint/Interrupt 各 1 个核心恢复场景，不能外推生产性能。
- V1 自研 ReAct 仍是唯一生产编排器；PoC 可以整体删除。

下一阶段前置条件：用户明确授权生产迁移；先确定通用状态契约和特性开关；保留自研 ReAct 回滚；在相同候选池/Checker/事件/报告上做双路兼容回归。未经确认不进入 V2-1C，也不开始 Domain Pack。
