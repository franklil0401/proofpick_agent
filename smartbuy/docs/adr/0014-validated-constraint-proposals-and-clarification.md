# ADR-0014：Schema 约束提案与双编排器主动澄清

- 状态：Accepted
- 日期：2026-09-02
- 范围：ProofPick V2-5

## 背景

V1 确定性约束门可以阻止 LLM 臆加条件，但固定解析器对口语数字、模糊阈值、双重否定、覆盖和取消的表达能力有限。直接让 LLM 生成有效约束会把候选资格交还给概率模型，也可能把虚构字段/span 或未确认条件送入 Checker。

## 决策

1. 采用确定性规则优先；仅在规则没有 Proposal 且存在约束语气时，允许 qwen-plus Function Calling 提案。
2. LLM Proposal 只有通过精确原文 span、Monitor Domain Pack 字段、Operator、类型、单位和范围校验后才可 supported；LLM 永远不能维护 active、Evidence 四态或 Checker 结果。
3. ambiguous/needs_confirmation 在 Agent 工具执行前中断，未确认进入 Checker 为 0；unsupported/invalid 永不激活。
4. ReAct 与 LangGraph 共用 `ClarificationCoordinator` 和 `ConstraintResolution`。LangGraph 使用现有 interrupt/checkpoint；ReAct 使用仓库外严格 JSON 提供等价暂停恢复。
5. pending 不写长期 Memory；当前输入继续覆盖会话和长期偏好。恢复后不重放已完成工具。
6. 功能采用环境开关和请求开关双重显式启用；默认及回滚路径仍是 V1 ReAct。

## 结果

50 条冻结表达修复后字段 Precision/Recall/F1 均为 100%，任务 50/50；首次实现 46/50 原样保留。5 类澄清在双编排器各通过一次，暂停前 Agent 调用 0、恢复后 1。全部结果为离线规则/Fake Provider，不代表任意自然语言或生产 SLA。

代价是 V1 `ConstraintNormalizer` 与 V2 Proposal Engine 暂时并存；V2 通过 Adapter 把确定性结果交给旧 Checker，没有在本阶段进行大规模去重或切换默认编排器。

## 拒绝的方案

- LLM 直接生成 Checker 输入：无法保证 span、字段和优先级，不采用。
- 模糊约束按默认阈值静默执行：会改变用户意图，不采用。
- 只支持 LangGraph 澄清：会破坏默认 ReAct 兼容与回滚，不采用。
- 为通过评测修改 holdout 金标：违反先冻结原则，不采用。
