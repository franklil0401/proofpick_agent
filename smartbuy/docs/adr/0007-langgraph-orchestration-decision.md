# ADR-0007：V2 编排层采用 LangGraph 的阶段性决策

- 状态：Accepted for staged migration
- 日期：2026-08-31
- 阶段：V2-1B
- 结论：**建议采用 LangGraph**
- 关联：[PoC 计划](../v2/v2_1_langgraph_poc_plan.md)、[PoC 报告](../v2/v2_1_langgraph_poc_report.md)、[ADR-0004](0004-bounded-react-evidence-and-memory.md)

## 背景

V1 自研有界 ReAct 已验证工具编排、安全停止和确定性 Checker，但没有持久 Checkpoint、可恢复 Interrupt 或原生并行状态图。V2 未来的澄清、并行本地/联网工具与恢复需求会放大单循环的维护成本。V2-1B 因而只用 Fake Provider 和 V1 冻结夹具验证 LangGraph，不接生产 API、WebUI、SSE 或正式 Demo。

## 决策

建议在用户另行授权的 V2 迁移阶段采用 LangGraph 作为编排状态机，同时保留以下不可变边界：

1. 现有工具、Evidence 四态、Memory 规则和 `CandidateConstraintVerifier` 保持独立；LangGraph 只拥有状态转移，不拥有事实或资格判定。
2. Text2SQL 的完整结构化候选池是混合任务的候选集合真源；KB 只补证据，不能静默缩小候选池。
3. 所有正常和异常终止路径必须经过 `constraint_gate`；Checker 异常、状态缺失或候选池不可确定时 fail closed。
4. 生产迁移必须走兼容适配器和特性开关；V1 自研 ReAct 保留为回滚路径，直到完整 V1 回归与四个 Demo 均通过。
5. PoC 的测试用文件 Checkpointer 不进入生产；正式持久化需选择受支持的 durable saver，并单独完成安全、迁移和保留策略评审。

本 ADR 不授权把 PoC 接入生产。当前 V1 API、WebUI、SSE 和 Demo 的编排器仍是自研 ReAct。

## 可验证证据

| 决策门 | PoC 结果 |
|---|---:|
| 计划中的测试场景 | 20/20 |
| PoC 自动化测试 | 28/28 |
| V1 代表性 Checker 金标 | 10/10 |
| V1 16 条回放无新增违规推荐 | 16/16 |
| SQL/KB 并行重叠 | 9/9 |
| 并行完整图中位延迟 | 51.945 ms |
| 相同数据的串行参考中位延迟 | 83.117 ms |
| 中位延迟降低 | 37.504% |
| 跨进程 Checkpoint 恢复 | 1/1 |
| 恢复后已完成 SQL/KB 重复执行 | 0/2 |
| Interrupt 暂停/恢复 | 1/1 |
| Checker 异常 fail closed | 1/1 |
| 拓扑与运行时绕过阻断 | 2/2 |
| 外部 API / 实际费用 | 0 / ¥0 |

“至少改善两项”的证据：

- **并行**：同一 40ms + 40ms Fake SQL/KB 工作负载的 9 次运行全部发生时间重叠；包含 StateGraph、Checkpoint、第二跳、Evidence 和 Checker 的完整图中位延迟仍比串行参考低 37.504%。
- **恢复**：跨两个 Python 进程从同一临时 Checkpoint 恢复 1/1 成功，恢复进程没有重复已完成的 SQL/KB 调用；V1 `react.py` 中公开 Checkpoint/Interrupt API 计数均为 0。
- **主动澄清**：Interrupt 在工具调用前暂停并恢复 1/1，暂停阶段工具调用为 0；V1 没有等价可恢复入口。

## 代价与风险

- 图状态、条件边、Reducer 和 Checkpointer 增加新的学习与调试面；LangGraph 版本升级必须受锁文件和回归门控制。
- PoC 只使用显示器冻结夹具和 Fake Provider，没有验证真实 LLM 路由波动、生产持久化、并发多用户或 SSE 接入。
- PoC 首次文件 Checkpoint 测试暴露 Windows 并发落盘竞争；修复为加锁原子替换并保留失败记录。这证明生产 saver 选择不能沿用测试实现。
- 并行基准仅 9 次本地 Fake 运行，不是生产性能或 SLA。

## V2 生产迁移前置门

1. 用户明确授权后再创建生产适配层，不直接移动 PoC 文件。
2. 先固定通用 `AgentState`/`ToolResult` 契约和兼容响应，再迁移节点。
3. 在特性开关下同时运行自研 ReAct 与新图，比较完整候选池、Checker 输入/输出、事件和报告。
4. 95 项 V1 门禁、四个 Demo、冻结文件哈希和敏感扫描全部通过。
5. 任一安全门或兼容性失败时关闭开关并回到 V1 自研 ReAct。

## 明确不做

本 ADR 不实现 Domain Pack、Product Pack、Web Search、第二品类，不安装或升级依赖，不修改 V1 主链，也不授权 V2-1C。
