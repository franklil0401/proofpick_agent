# ProofPick V2 文档入口

本目录保存 ProofPick V2 的目标、开发流程和后续阶段文档。

## 当前文档

- [V2 产品目标、能力边界与实现路径](ProofPick_V2_目标与实现路径.md)
- [V2 详细开发流程](V2_DEVELOPMENT_PROCESS.md)
- [V2-1A 实现级设计](v2_1_implementation_design.md)
- [V2-1B LangGraph PoC 计划](v2_1_langgraph_poc_plan.md)
- [V2-1B LangGraph PoC 报告](v2_1_langgraph_poc_report.md)
- [ADR-0007：LangGraph 编排决策](../adr/0007-langgraph-orchestration-decision.md)
- [V2-1C 编排兼容适配报告](v2_1c_compatibility_report.md)
- [V2-1C 本地运行说明](v2_1c_runtime.md)
- [ADR-0008：兼容适配与 Checkpoint](../adr/0008-langgraph-compatibility-and-checkpointing.md)

## 当前状态

- V1 已冻结在 `v1.0.0-portfolio`；`feature/proofpick-v2` 已从同一 V1 Commit 创建并推送。
- V2-1C 已建立统一编排契约、显式开关、仓库外 SQLite Checkpoint 与 Checker 强制终态。
- V1 自研 ReAct 仍是默认编排器；LangGraph 只可显式开启，尚不具备切换默认值的条件。
- Domain Pack、Product Pack、真实 Web Search 和其他业务开发均未开始。
- 每个阶段完成后必须测试、提交、推送并停止，等待用户确认。
