# ProofPick V2-1B LangGraph PoC 计划

最后更新：2026-08-31

状态：**V2-1B 已按本计划完成隔离 PoC；未接生产主链，外部 API 调用为 0**

前置设计：[V2-1A 实现级设计](v2_1_implementation_design.md)

执行结果：[V2-1B PoC 报告](v2_1_langgraph_poc_report.md)；决策：[ADR-0007](../adr/0007-langgraph-orchestration-decision.md)。以下保留执行前冻结的测试计划和退出标准，作为结果审计依据。

## 1. 决策问题与边界

PoC 只回答一个问题：LangGraph 是否能在不削弱 V1 完整候选池、Evidence 四态、预算限制、可审计事件和不可绕过 Checker 的前提下，实质改善“路由、并行、恢复、可测试性”中的至少两项。

不验证真实百炼质量，不替换 V1 主链，不改依赖锁文件，不接 Web Search，不迁移 Domain Pack，不写生产代码。开始 V2-1B 前需再次获得用户授权，并根据届时官方文档选择/固定 LangGraph 版本；本计划不预设当前 API 细节。

## 2. 计划隔离与输入输出

计划目录（本轮不创建）：

```text
experiments/langgraph_poc/
├─ README.md
├─ graph.py
├─ fake_provider.py
├─ fake_tools.py
├─ fixtures/
├─ tests/
└─ results/
```

输入：`query`、可选 V1 session snapshot、固定 `domain_id=monitor`、冻结 Data Version、Fake Provider 脚本、只读 SQLite/KB fixture、AgentLimits。输入不含真实 Key、Workspace ID、网络客户端或运行数据库写权限。

输出：通用 `AgentState` 的公开快照、完整候选池、合并后的 ToolResult、Evidence 四态、VerificationBatch、结构化报告、SSE/Monitor 事件、预算摘要与可重复结果哈希。不得输出隐藏思维链、完整 Prompt 或敏感错误正文。

## 3. 最小状态图

```text
START
  → parse_requirements
  → route_task
      ├─ clarify_required → interrupt → resume → route_task
      ├─ fact → kb_search
      └─ structured/mixed → fan_out(sql, kb_seed)
                              └→ merge_tool_results
  → targeted_kb_if_needed
  → evidence_check
  → constraint_gate (mandatory)
      ├─ checker_error → fail_closed_report
      └─ verified → rank_eligible → report
  → END
```

### 3.1 StateGraph、Node 与 Conditional Edge

每个 Node 接收/返回可序列化状态增量，不持有 Provider、SQLite 连接或锁。Conditional Edge 只读取显式字段：`clarification_required`、`task_type`、`tool_status`、`missing_fields`、`conflicts`、`budget_exhausted`、`checker_completed`。条件函数不得调用模型或产生副作用。

计划节点：

| Node | 输入 | 输出/副作用 |
|---|---|---|
| `parse_requirements` | query、旧约束、Pack snapshot | 带 span 的 Constraint 提案，经 Fake normalizer 后写入 ConstraintSet |
| `route_task` | task/domain/mode/constraints | 路由枚举；不执行工具 |
| `sql_query` | 硬约束、只读 fixture | ToolResult + 候选；幂等 |
| `kb_seed_search` | query、显式型号/字段 | ToolResult + 初始证据；不得替代 SQL 完整池 |
| `merge_tool_results` | 并行分支结果 | 按 call_id/product_id 合并，保留来源、失败和重复记录 |
| `targeted_kb` | SQL 候选、缺失/冲突字段 | 依赖式第二跳 ToolResult |
| `evidence_check` | 完整池、字段、证据 | 四态账本 |
| `constraint_gate` | ConstraintSet、完整池、只读 DB/Evidence | 必执行 VerificationBatch；异常 fail closed |
| `rank_eligible` | eligible IDs、软偏好 | 只排序，不增删资格 |
| `report` | 受保护状态 | 结构化公开报告和事件 |
| `fail_closed_report` | 错误/未完成状态 | 推荐为空、列出原因和未完成项 |

图编译时必须验证：任何到 `report` 的路径都先经过 `constraint_gate`；报告节点运行时再次断言 `checker_completed=true` 和 `verification_batch` 存在。直接构造状态、Prompt 注入或异常边都不能绕过。

## 4. 并行、合并与有界执行

PoC 的 KB/SQL 并行使用“可独立的第一跳”：SQL 根据硬条件形成完整结构化候选池；KB Seed 根据原问题、显式型号和关键字段检索初始证据。Fan-in 后，SQL 候选池是资格检查的集合真源，KB 命中只补证据，不能覆盖或缩小候选池。随后可按 SQL 候选再做 targeted KB，形成真实依赖式多跳。

ToolResult 合并规则：

- 以 `tool_call_id` 幂等；重复完成只接受首个校验通过的结果并记录 duplicate。
- 候选按 `product_id + market + variant` 去重，累加 `origin_tool_calls`。
- success/degraded/failed/unavailable 各自保留，不以“最后写入”覆盖失败。
- Evidence 按 `evidence_id` 去重；同字段不同值进入 conflict，不做 last-write-wins。
- 并行分支取消/超时也必须形成公开 ToolResult。

边界默认沿用 V1：最大 8 steps、12 tool calls、单工具 20 秒、单任务 ¥0.25；PoC Fake Provider 的成本为确定性虚拟值。另加 graph deadline、每工具最大尝试次数和 checkpoint revision。任何上限到达均转入安全停止/Checker（有完整池时）或 fail-closed report，不继续循环。

## 5. Checkpoint、Interrupt 与副作用

### 5.1 Checkpoint 恢复

测试在 `merge_tool_results` 后强制中断并保存序列化状态；新进程从 checkpoint 恢复。`tool_call_id + input_fingerprint` 作为幂等键，已成功的 SQL/KB 不重复执行、不重复计费；恢复后的候选池、Checker 结果和最终哈希必须等同无中断运行。

PoC Checkpoint 只写测试临时目录，内容做 Schema 和敏感字段扫描；不得使用真实 Memory 或运行日志。损坏/版本不兼容时拒绝恢复并返回明确错误，不能部分加载。

### 5.2 Interrupt 主动澄清

输入“27 英寸左右、Type-C 一线通，预算合适”触发影响候选集的歧义。`parse_requirements` 输出 pending clarification，图在任何查询/Checker 前 interrupt。恢复输入补充“27 英寸是软偏好；预算上限 3000；USB-C 必须支持视频和至少 65W”后，旧模糊约束停用，新约束带 `source_turn/provenance` 激活，流程继续。

Interrupt 前不得进行外部副作用；恢复两次不得重复写 Memory。长期偏好写入不纳入 PoC，若模拟只记录“待用户确认”事件。

## 6. 失败、重试和降级

- Fake KB 超时/503：最多按配置重试，仍失败则保留 SQL 候选但 Evidence unknown，不宣称已核验。
- Fake SQL 非法/不可用：执行前阻断；若没有受控模板则完整池不可确定，报告不推荐。
- Reranker 失败：KB ToolResult degraded，保留向量顺序。
- Fake LLM 429：有限退避；401/403 单次即停，测试不得发真实请求。
- 两个并行分支之一失败：另一结果不丢失，合并状态明确 degraded。
- Checker 抛错、节点被跳过、状态缺字段：统一 fail closed，推荐集合为空。
- 达到步骤/工具/延迟/费用上限：停止原因、未完成字段和已有证据可见。

## 7. SSE 与 Monitor 事件映射

| Graph 事件 | 对外事件 | 最小公开字段 |
|---|---|---|
| node start/end | `agent_step_started/completed` | run_id、node、step、duration、status |
| tool dispatch/result | 兼容 `tool_call/tool_output` | tool、脱敏参数摘要、parent、status、summary |
| parallel fan-out/fan-in | `parallel_group_started/completed` | group_id、children、完成/失败计数 |
| interrupt | `clarification_required` | 问题、待澄清字段、resume token 的不可猜测引用 |
| checkpoint | `checkpoint_saved/resumed` | checkpoint_id、revision；不含状态正文 |
| Checker | `constraint_check_started/completed` | version、池大小、四态、eligible、duration |
| stop | `done/error` | report 或脱敏停止原因 |

现有 WebUI 不在 PoC 修改范围。测试只验证事件可映射到 V1 SSE/Monitor，且没有 Key、Authorization、完整 Prompt、隐藏思维链、私人路径或堆栈。

## 8. Fake Provider 与测试矩阵

Fake Provider 按 `case_id + call_index` 返回固定 tool calls/错误，记录虚拟 token、费用和延迟；Fake Tools 读取冻结 fixture，不联网、不调用百炼。随机顺序测试使用可控 scheduler，但相同输入的逻辑输出必须一致。

| # | 场景 | 关键断言 |
|---:|---|---|
| 1 | 单事实 | 只走 KB；仍形成安全报告，不调用 SQL |
| 2 | 组合筛选 | SQL+KB seed 并行，合并后 targeted KB/Evidence/Checker |
| 3 | 相似型号/地区 | product identity 不误合并 |
| 4 | 并行同候选 | 完整池去重但保留两个来源 |
| 5 | 并行冲突证据 | 双值保留为 conflict，不覆盖 |
| 6 | KB 失败 | SQL 可用、证据 unknown、无虚假完全满足 |
| 7 | SQL 失败 | 不让 LLM 心算候选，推荐为空 |
| 8 | Reranker 降级 | 保留向量结果并显示 degraded |
| 9 | 有界重试 | 429/超时有限；401/403 不重试 |
| 10 | 最大 steps/tools | 安全停止，无无限循环 |
| 11 | 延迟/费用预算 | 达上限后不再派发工具，账本分母准确 |
| 12 | Checkpoint 恢复 | 不重复工具/虚拟费用，结果等同无中断 |
| 13 | Checkpoint 损坏 | 拒绝恢复，不返回未校验数据 |
| 14 | Interrupt 澄清 | 暂停前无查询；恢复后新约束覆盖旧约束 |
| 15 | Checker 异常 | fail closed、推荐为空 |
| 16 | 绕过攻击 | 任意边不能从工具直接到 report |
| 17 | SSE 映射 | 父子、并行、Checker 与停止事件齐全且脱敏 |
| 18 | 代表性 V1 回放 | 至少 10 条候选集合与 Checker golden 一致 |
| 19 | V1 16 条 regression | 不出现新违规推荐；历史文件不修改 |
| 20 | 重复执行/调度乱序 | Fake 下最终候选、Checker 和报告关键字段一致 |

## 9. 通过、失败与退出标准

全部满足才算 PoC 通过：

1. 上表 20 类测试全部通过；至少 10 条代表 V1 用例的完整候选池与 Checker 结果一致。
2. 16 条 V1 regression 不新增违规推荐；Checker 固定输入字节一致。
3. SQL/KB 并行无覆盖、无丢失、无重复计费；并行输出乱序不改变语义结果。
4. Checkpoint 恢复一次成功，Interrupt 暂停/恢复一次成功，副作用幂等。
5. Checker 在所有终止路径必执行或 fail closed；不存在绕过路径。
6. SSE/Monitor 事件可映射且敏感扫描为 0。
7. Fake Provider 下 API 调用和真实费用均为 0。
8. 相比自研循环，在路由、并行、恢复、可测试性中至少两项有可量化改善；迁移复杂度没有破坏 V1 兼容门。

任一安全门、完整池、Checkpoint 幂等、Interrupt 或 V1 等价断言失败，即 PoC 不通过。框架需要侵入 V1 主链、状态必须持有不可序列化/敏感对象、或无法证明 Checker 不可绕过，也判失败，不能用 skip 或降低断言掩盖。

退出后只做决策：通过则提交“采用 LangGraph”的 ADR 和 V2-1C 迁移建议；不通过则提交“不采用”的 ADR，删除隔离 PoC，继续以相同契约重构自研 ReAct。两种结果都必须保留首次失败和测试证据，并推送后停止；未经再次授权不进入生产迁移。
