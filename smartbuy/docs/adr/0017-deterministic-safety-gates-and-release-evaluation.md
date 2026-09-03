# ADR-0017：确定性安全门与发布评测分离

- 状态：Accepted
- 日期：2026-09-03
- 决策范围：V2-6C-R4 Laptop E2E 工程收尾

## 背景

V2-6C-R3 的三套代码冻结验证都已完成一次不可覆盖的首测：轮 1 为 `17/24`，轮 2 为 `16/24`，轮 3 为 `21/24`。第三轮已达到任务正确率、硬约束 F1 `97.56%` 和推荐事实证据覆盖 `93/93` 的目标，但 Candidate Scope 越界为 1，充分证据下错误空推荐为 `1/8`，因此没有通过全部联合门槛。三轮输入、金标、SHA-256、run_id、RC 配置和首次结果继续保持原样。

`1/8 = 12.5%` 也说明小分母百分比会被单个错误显著影响。该事实不能成为追溯修改门槛、把失败改称通过的理由。

## 决策

1. V2-6C-R3 三轮首测永久按原结论保留，第三轮仍为失败。
2. V2-6C-R4 不创建新的 Holdout；原始 30 条、R2 20 条和 R3 三轮各 24 条合计 122 条，全部只作为 `exposed regression` 或 `diagnostic regression`。
3. 推荐链建立由确定性代码维护的集合不变量：

   ```text
   final_report_candidates
   ⊆ checker_eligible_candidates
   ⊆ candidate_scope.allowed_candidates
   ⊆ domain_catalog
   ```

4. Checker 前和 Reporting 前都执行断言；工具合并、Checkpoint 恢复和报告渲染不得扩大 Scope。违反时删除越界推荐、fail closed，并只发出脱敏的 `scope_violation` 事件。
5. 结果状态由确定性状态机计算，至少区分 `recommendation_available`、`no_matching_candidate`、`insufficient_evidence`、`needs_clarification`、`unsupported_request`、`tool_failure` 和 `safety_blocked`；LLM 只能解释，不能授权候选或改写状态。
6. 工程收尾证据由三层组成：确定性安全不变量、122 条已暴露回归、至少 1000 组变形/属性断言。
7. 新鲜的 Release Candidate 泛化评测推迟到 V2-9；应尽量由未参与本轮实现的独立评测 Agent 出题和复核，并在看到结果前冻结任务、金标、评分器和 RC 配置。

## 后果

- 收益：安全性质不再依赖小样本命中率；Scope、Checker 和报告的责任边界可由代码和测试复核；历史结果不会被工程调试污染。
- 代价：122 条回归只能证明已知问题没有复发，不能证明新问题上的泛化性能；V2-6C-R4 只能称为工程收尾。
- 发布限制：在 V2-9 完成独立 RC 评测前，不得把 R4 暴露回归写成 Holdout、盲测、生产准确率或 SLA。

## 回滚

如新安全门导致无法解释的 V1 行为差异，关闭 V2 Domain/LangGraph/Open Research 特性开关并回到 V1 默认 ReAct 路径。不得通过移动 V1 Tag、修改冻结数据或删除历史失败文件回滚。

相关证据见 [V2-6C-R3 报告](../v2/v2_6c_r3_generic_decision_core_report.md)和 [V2-6C-R4 工程收尾报告](../v2/v2_6c_r4_laptop_engineering_closeout.md)。
