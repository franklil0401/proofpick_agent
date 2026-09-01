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
- [V2-2 Product Pack 与 Evidence Ledger 报告](v2_2_product_pack_report.md)
- [V2-2 Product Pack 运行说明](v2_2_runtime.md)
- [ADR-0010：版本化 Product Pack 与字段级 Evidence Ledger](../adr/0010-versioned-product-pack-and-evidence-ledger.md)
- [V2-3 受控 Source Search 报告](v2_3_source_search_report.md)
- [V2-3 Source Search 运行说明](v2_3_runtime.md)
- [ADR-0011：可审计智谱 Source Search](../adr/0011-auditable-zhipu-source-search.md)

## 当前状态

- V1 已冻结在 `v1.0.0-portfolio`；`feature/proofpick-v2` 已从同一 V1 Commit 创建并推送。
- V2-2 已落地严格 Product Pack、字段级 Evidence Ledger、仓库外 staging/publish/rollback，并完成第 13 个显示器的真实 65-chunk Chroma 与四工具闭环验证；Product Pack 路径默认关闭，V1 冻结数据与历史结果不变。
- V1 自研 ReAct 仍是默认编排器；LangGraph 只可显式开启，尚不具备切换默认值的条件。
- V2-3 已实现默认关闭的智谱 Source Search：固定 8 条任务中 6 条命中精确地区官方页、2 条安全降级，错误地区误接受为 0；Source Candidate 不进入 Evidence 或 Checker。
- Web Extractor、Evidence Promotion、第二品类和 V2-4 均未开始。V2-3 只发现 URL，不宣称已经核验网页字段或实时价格。
- 每个阶段完成后必须测试、提交、推送并停止，等待用户确认。
