# ADR-0008：LangGraph 兼容适配、显式开关与本地 Checkpoint

- 状态：Accepted for opt-in validation
- 日期：2026-08-31
- 阶段：V2-1C
- 默认编排器：`react`
- 关联：[ADR-0007](0007-langgraph-orchestration-decision.md)、[V2-1C 报告](../v2/v2_1c_compatibility_report.md)

## 背景

ADR-0007 基于隔离 Fake PoC 有条件建议采用 LangGraph，但不授权替换 V1。进入后续迁移前，需要证明新编排器能共享 V1 输入/输出/事件，持久恢复不引入不安全反序列化，Checker 无法被图路径绕过，且关闭开关即可恢复 V1。

## 决策

1. 定义版本化 `OrchestratorRequest/Result`，由 `ReactOrchestrator` 与 `LangGraphOrchestrator` 共同实现。
2. `PROOFPICK_ORCHESTRATOR` 默认 `react`；`langgraph` 必须显式开启，非法值失败。
3. 只允许配置显式授权的 LangGraph **初始化失败**回退；运行失败不得自动重放到 ReAct。
4. LangGraph 暂时把完整 `PurchaseDecisionAgent` 作为权威执行节点，复用同一工具、Evidence、Memory、Reporting、Ranking 与 Checker，不复制业务规则。
5. `checker_terminal` 是 `report` 的唯一前驱；缺失、degraded 或集合不一致均清空推荐并 fail closed。
6. 测试使用 `InMemorySaver`；Windows 本地 MVP 使用仓库外 `AsyncSqliteSaver`。SQLite 不作为生产级方案。
7. 序列化使用 `JsonPlusSerializer`，`pickle_fallback=False`，constructor 只允许精确 `builtins.dict`。
8. user/session/thread 组成版本化哈希键；恢复必须通过状态版本校验；后端必须支持 thread 清理与关闭。
9. PostgreSQL 只定义迁移边界，本阶段不安装、不部署。
10. V1 SSE 事件保持不变，V2 图/Checkpoint/Interrupt/Checker 事件增量输出并写入脱敏 Monitor。

## 结果

- 新增 V2-1C 离线测试 25/25；10 条代表输入的 ReAct/LangGraph 报告一致 10/10。
- AsyncSqliteSaver 跨两个 Python 进程恢复 1/1；Interrupt 恢复与不兼容版本拒绝均通过。
- Checker 集合外推荐、缺失验证、拓扑绕过均被阻断；异常路径不输出购买推荐。
- V1 冻结阶段 4 当前回归记录仍为 16/16，冻结文件未修改。
- 外部 API 调用 0，费用 ¥0。

PoC 的 Fake 延迟只属于框架可行性对比，不是线上性能指标；本 ADR 不作性能或 SLA 结论。

## 后果与限制

- 优点：默认行为可证明不变；新图可以显式试用；选择、失败和回退可审计；本地恢复有受支持 Saver；Checker 多一层结构防线。
- 代价：新增 `langgraph-checkpoint-sqlite==3.0.3` 与 `sqlite-vec==0.1.9` 锁定依赖；图外壳、连接生命周期和版本策略增加维护面。
- 限制：正式图仍把 V1 ReAct 当单节点，没有实现生产 SQL/KB 并行；主动澄清策略尚未接入 V1 需求解析；SQLite 不适合多实例。

## 默认值迁移门

本 ADR **不批准**把默认值改成 `langgraph`。后续至少需要另行授权、真实服务受控验证、四个 Demo、V1 全量回归、事件/UI 检查、Checkpoint 保留策略和逐节点迁移方案。任一安全或兼容门失败时保持/恢复 `react`。
