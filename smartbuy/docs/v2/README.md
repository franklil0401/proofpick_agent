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
- [V2-1D 通用契约与 Monitor Domain Pack 报告](v2_1d_domain_pack_report.md)
- [V2-1D Domain Pack 运行说明](v2_1d_runtime.md)
- [ADR-0009：通用契约与 Monitor Pack](../adr/0009-domain-contracts-and-monitor-pack.md)

## 当前状态

- V1 已冻结在 `v1.0.0-portfolio`；`feature/proofpick-v2` 已从同一 V1 Commit 创建并推送。
- V2-1D 已通过适配层落地通用契约、严格 Domain Pack Loader 与 Monitor Pack；该路径默认关闭，V1 行为与冻结数据不变。
- V1 自研 ReAct 仍是默认编排器；LangGraph 只可显式开启，尚不具备切换默认值的条件。
- Product Pack 导入、Evidence Ledger、第二品类和真实 Web Search 均未开始。
- 每个阶段完成后必须测试、提交、推送并停止，等待用户确认。
