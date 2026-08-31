# ProofPick V2-1C 编排兼容适配报告

最后更新：2026-08-31

状态：**实现与离线验收完成；LangGraph 仍非默认编排器**

分支：`feature/proofpick-v2`

基线：V1 `d51b6668a6a45c1b01ef4e64da3c4b9ac84ed10c`

## 1. 范围与结论

V2-1C 在不替换 `PurchaseDecisionAgent`、不改商品规则和不调用收费 API 的前提下，建立统一 Orchestrator 契约、显式特性开关、安全 Checkpointer 和 V1/V2 事件适配。现有 ReAct 仍是默认且唯一稳定路径；LangGraph 只是显式开启的兼容外壳，内部继续调用同一套 ReAct、工具、Evidence Check、Memory、Reporting 和 Constraint Checker。

结论：**已经具备受控、可回滚的 opt-in 技术条件，但尚不具备切换默认编排器的条件。** 当前图将完整 V1 工作流作为单个权威节点，尚未把 Text2SQL/KB 等迁成正式图节点，也没有真实流量/在线模型验证；切换默认值必须等待后续独立授权和验收。

## 2. 实现边界

### 2.1 统一契约

`smartbuy/orchestration/contracts.py` 提供：

- `OrchestratorRequest`：统一 query、user/session/thread、Memory 与恢复输入；版本固定为 `proofpick-orchestration-v1`。
- `OrchestratorResult`：统一 completed/interrupted、编排器类型、thread、报告和 Interrupt 输出。
- `Orchestrator` / `CompatibleAgent`：限制适配层只能依赖 V1 已公开的 `run` 与 `preference_memory` 表面。
- 版本不匹配、恢复缺少 thread、completed 无报告等情况由 Pydantic 在入口拒绝。

`ReactOrchestrator` 只转发 V1 输入、事件与 `DecisionReport`，不改写工具路径、候选池、Memory 或报告。`LangGraphOrchestrator` 的当前正式图是：

```text
START -> prepare -> [clarify/interrupt] -> execute_react
      -> checker_terminal -> report -> END
```

`execute_react` 调用原 `PurchaseDecisionAgent.run`，因此没有第二套 Text2SQL、KB Search、Evidence、Memory、Ranking、Reporting 或 Checker 规则。`report` 的唯一前驱是 `checker_terminal`。

### 2.2 特性开关与回滚

| 配置 | 默认 | 行为 |
|---|---|---|
| `PROOFPICK_ORCHESTRATOR` | `react` | 只接受 `react` / `langgraph`；非法值启动失败 |
| `PROOFPICK_LANGGRAPH_FALLBACK_TO_REACT` | `false` | 只有显式为真时，LangGraph **初始化失败**才回退 ReAct |
| `PROOFPICK_CHECKPOINT_PATH` | `C:/ai/proofpick-v2/checkpoints.sqlite3` | LangGraph 本地 Checkpoint；必须位于仓库外 |

- 默认请求不实例化 LangGraph，也不创建 Checkpoint 数据库。
- 选择、初始化失败、显式回退和运行失败均写入脱敏 SSE/Monitor 事件。
- LangGraph 运行中失败不会自动重放到 ReAct，避免重复工具/API 调用；只允许初始化阶段的显式回退。
- 关闭开关后仍读取同一 V1 数据、索引和 Memory，无需迁移或重建数据。

### 2.3 强制 Checker 终态

V1 `PurchaseDecisionAgent` 仍负责完整候选池与实际 `CandidateConstraintVerifier` 调用。图在其后增加不含品类规则的结构安全门：

1. `DecisionReport.constraint_verification` 必须存在。
2. 推荐集合必须是 Checker `eligible_model_ids` 的子集。
3. Checker degraded 时推荐集合必须为空。
4. 报告候选的 `eligible` 不得超出 Checker 合规集合。
5. 任何不一致都清空推荐、标记 abstained/degraded 并 fail closed；不编造事实或证据。
6. `report` 节点再次要求 `checker_terminal_completed`，不存在绕过边。

LLM 和工具节点不能产生可返回的最终报告；只有安全门后的 `report` 节点可以形成 `OrchestratorResult`。

## 3. Checkpointer 与反序列化安全

由于环境原有 `langgraph==1.0.5` 但没有 SQLite Saver，本阶段新增并锁定 `langgraph-checkpoint-sqlite==3.0.3`，同步引入其锁定依赖 `sqlite-vec==0.1.9`。`uv sync --frozen` 已验证通过。

| 场景 | 实现 | 边界 |
|---|---|---|
| 单元测试 | `InMemorySaver` | 不跨进程，不用于本地持久运行 |
| Windows 本地 MVP | `AsyncSqliteSaver` | 仓库外单机文件；不是生产 HA/多实例方案 |
| PostgreSQL | 仅 `PostgresCheckpointBackend` 接口边界 | 本轮不安装依赖、不部署、不宣称可用 |

安全设置：

- `JsonPlusSerializer(pickle_fallback=False)`，禁止 Pickle fallback。
- `allowed_json_modules=[("builtins", "dict")]`，只允许精确符号，不开放通配或 `True`。
- 原始 user/session/thread 和完整 `OrchestratorRequest` 通过每次调用的异步上下文传入，不作为图状态字段持久化；SQLite thread key 只保存摘要。
- 图状态只持久化 JSON-safe 字典、字符串、数值、布尔和 `DecisionReport.model_dump(mode="json")`；Provider、连接、锁、Key、Prompt 和思维链不进入状态。
- 按 `user_id + session_id + thread_id + checkpoint_version` 计算 SHA-256 存储键，三层身份互相隔离且 SQLite 中不暴露原始 ID。
- 恢复前校验 `proofpick-checkpoint-v1`；缺失或不兼容状态明确拒绝。
- 后端提供按 thread 清理与连接关闭；数据库路径落入 Git 仓库会在初始化前拒绝。

## 4. SSE 与 Monitor 兼容

V1 的 `tool_call`、`tool_output`、`constraint_check_started/completed` 和 `done` 保持原格式。V2 增量事件包括：

- `orchestrator_selected/failed/fallback`
- `graph_started/completed`、`graph_node_started/completed`
- `checkpoint_saved/resumed`
- `interrupt_required/resumed`
- `checker_terminal_started/completed`

Monitor 只保存类型、requested/selected、状态和错误类别；不保存 query、user/session/thread、Checkpoint key、Prompt、路径或底层异常正文。

## 5. 验证结果

所有 V2-1C 用例均使用 Stub/Fake Provider 和本地临时文件；云端模型调用、Token 和费用均为 **0**。

| 验证项 | 结果 |
|---|---:|
| V2-1C 新增测试 | 25/25 |
| 全仓库离线测试 | 120/120（V1 95 + V2-1C 25） |
| V1 既有测试独立复跑 | 95/95 |
| ReAct/LangGraph 同输入、同报告契约代表用例 | 10/10 |
| 默认 ReAct / 非显式不创建 LangGraph | 1/1 |
| 非法开关拒绝 | 1/1 |
| 初始化失败不静默回退 | 1/1 |
| 显式初始化回退及事件 | 1/1 |
| 运行中失败不自动重放 | 1/1 |
| Checker 集合外推荐与缺失结果 fail closed | 2/2 |
| Checker 异常降级批次在图终态保持 fail closed | 1/1 |
| Checker 唯一报告前驱拓扑 | 1/1 |
| Interrupt 暂停/恢复 | 1/1 |
| 不兼容 Checkpoint 版本拒绝 | 1/1 |
| user/session/thread 隔离 | 3/3 维度 |
| AsyncSqliteSaver 跨 Python 进程恢复 | 1/1 |
| V1 + V2 SSE 事件同时可见 | 1/1 |
| 冻结阶段 4 当前回归记录 | 16/16，文件未改 |

提交前 Ruff、Compileall、12/12 JavaScript、5/5 PowerShell AST、227 个 Markdown 相对链接和 `git diff --check` 均通过。V1 历史在线结果没有重跑或覆盖。

### 5.1 首次失败与修复

- 新套件首次运行为 20/22：其一把 `checkpoint_ns` 错当作普通版本命名空间，LangGraph 将其解释为不存在的子图；改为只使用摘要 thread key，并在状态内独立校验版本。其二是跨进程 helper 的模块搜索路径未显式传递；测试入口补充固定项目根路径。
- 下一次跨进程运行暴露 Windows 子进程输出编码未固定；仅在测试子进程设置 `PYTHONIOENCODING=utf-8` 后恢复，不影响 Checkpoint 数据格式。
- 最终扩充 Checker degraded 终态用例后为 25/25。失败输出未通过删除断言或 skip 掩盖。

## 6. 与 V2-1B PoC 的关系

- V2-1B 的并行 Fake 负载延迟只证明 PoC 状态图能并发执行，不是线上性能、P95 或 SLA；V2-1C 不引用它作为运行性能结论。
- `experiments/langgraph_poc/` 仍是隔离实验；正式入口不导入 PoC 模块。
- V2-1C 复用 PoC 已证明的图/Interrupt 思路，但使用受支持的 SQLite Saver 和严格序列化，不复用 PoC 文件 Checkpointer。
- 当前正式图没有把 KB/SQL 拆成正式并行节点，因此不能宣称生产链路已经获得并行加速。

## 7. 已知限制与下一步前置门

1. LangGraph 仍包裹完整 V1 ReAct 节点；正式节点迁移、并行工具与状态粒度尚未开始。
2. SQLite Saver 只适用于单机 Windows MVP，不提供生产级并发、HA、备份或租户治理。
3. 尚未用真实模型、四个本地 Demo 或长期运行服务验证 opt-in LangGraph；本阶段按要求不调用收费 API。
4. API 已能返回 interrupted 契约和 V2 SSE，但主动澄清策略尚未接入 V1 需求解析；测试通过显式契约触发。
5. PostgreSQL 只有接口与迁移方向，没有实现或部署。

进入下一阶段前必须另获授权，并先决定是做受控 shadow/canary，还是逐节点迁移。无论选择何者，都必须保持 Checker 唯一终态、V1 默认回滚路径、冻结数据/评测不变，并重新跑 V1 全量与四个 Demo。当前不应将默认值改为 `langgraph`。

## 8. 可复现命令

```powershell
uv sync --project vendor/youtu-rag --frozen
uv run --project vendor/youtu-rag --frozen python -m pytest `
  smartbuy/tests/unit/test_v2_orchestration_contract.py `
  smartbuy/tests/integration/test_v2_sqlite_checkpoint.py `
  smartbuy/tests/integration/test_v2_api_orchestration.py -q
```

运行开关与本地路径见 [V2-1C 运行说明](v2_1c_runtime.md)，决策见 [ADR-0008](../adr/0008-langgraph-compatibility-and-checkpointing.md)。
