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
- [V2-4 Web Extractor 与 Open Research 报告](v2_4_open_research_report.md)
- [V2-4 Open Research 运行说明](v2_4_runtime.md)
- [ADR-0012：受控网页抽取与 Open Evidence](../adr/0012-governed-web-extraction-and-open-evidence.md)
- [V2-4C 地区证据可比性收尾报告](v2_4c_regional_evidence_report.md)
- [ADR-0013：目标地区证据与跨地区比较分层](../adr/0013-regional-evidence-comparability.md)
- [V2-5 自然约束与主动澄清报告](v2_5_constraint_clarification_report.md)
- [V2-5 运行说明](v2_5_runtime.md)
- [V2-5 新表达评测集](v2_5_expression_eval.md)
- [V2-5B 评测口径与真实 qwen-plus 首测](v2_5b_live_provider_validation_report.md)
- [ADR-0014：Schema Proposal 与双编排器澄清](../adr/0014-validated-constraint-proposals-and-clarification.md)
- [V2-5C 服务端 Quote-to-Span 报告](v2_5c_quote_span_report.md)
- [V2-5C Quote-to-Span 运行说明](v2_5c_quote_span_runtime.md)
- [V2-5C Live Holdout V2 数据卡](v2_5c_live_holdout_v2_data_card.md)
- [ADR-0015：服务端精确 Quote-to-Span](../adr/0015-server-verified-quote-to-span.md)
- [V2-6A Laptop Domain Pack 与治理数据报告](v2_6a_laptop_domain_and_data_report.md)
- [V2-6A Laptop 治理数据卡](v2_6a_laptop_data_card.md)
- [V2-6A Laptop Pack 本地运行说明](v2_6a_laptop_runtime.md)
- [V2-6B Laptop SQLite、真实索引与工具闭环报告](v2_6b_laptop_toolchain_report.md)
- [V2-6B Laptop 索引与工具运行说明](v2_6b_laptop_index_runtime.md)
- [V2-6C-R 失败现场保存审计](v2_6c_r_failed_holdout_audit.md)
- [V2-6C-R1 商品身份与 Scope 失败链路审计](v2_6c_identity_scope_failure_audit.md)
- [V2-6C-R1 商品身份与 Scope 修复报告](v2_6c_identity_scope_repair_report.md)
- [V2-6C-R2A 第二套 Laptop Holdout 数据卡](v2_6c_second_holdout_data_card.md)
- [ADR-0016：确定性商品身份与不可扩大的 Candidate Scope](../adr/0016-deterministic-product-identity-and-candidate-scope.md)

## 当前状态

- V1 已冻结在 `v1.0.0-portfolio`；`feature/proofpick-v2` 已从同一 V1 Commit 创建并推送。
- V2-2 已落地严格 Product Pack、字段级 Evidence Ledger、仓库外 staging/publish/rollback，并完成第 13 个显示器的真实 65-chunk Chroma 与四工具闭环验证；Product Pack 路径默认关闭，V1 冻结数据与历史结果不变。
- V1 自研 ReAct 仍是默认编排器；LangGraph 只可显式开启，尚不具备切换默认值的条件。
- V2-3 已实现默认关闭的智谱 Source Search：固定 8 条任务中 6 条命中精确地区官方页、2 条安全降级，错误地区误接受为 0；Source Candidate 不进入 Evidence 或 Checker。
- V2-4 已实现默认关闭的静态 Web Extractor、请求级临时 Open Evidence 与开放研究报告；数据库外 PD3226G/US 真实链路成功，Open 商品固定不能进入 Trusted eligible。
- V2-4C 已把“只有错误地区证据”从 conflict 修正为 unknown，并把目标地区核验与跨地区差异分层；PD3226G/US 离线回放仍为 6/6 matched。
- V2-5 已实现默认关闭的确定性优先 Constraint Proposal 与主动澄清；50 条冻结表达的离线规则回归为 55/55 字段、50/50 任务，ReAct/LangGraph 暂停恢复语义一致。
- V2-5B 新增 12 条一次性 Live Holdout：真实 qwen-plus Function 名 12/12 正确且安全误激活为 0，但 Schema 10/12、span 1/20、任务 2/12，LLM 回退仍属实验能力，不能宣称任意口语约束已稳定支持。
- V2-5C 保留上述历史并改用服务端精确 Quote-to-Span；新的 20 条一次性 Live Holdout V2 首测为 Schema 20/20、服务端 span 28/28、清晰硬约束 F1 96.97%、任务 16/20，安全误激活仍为 0。
- V2-6A 已新增配置驱动的 Laptop Domain Pack，以及 12 个精确配置、4 个品牌、12 个官方来源和 406 条字段证据；30 条 Laptop 任务已冻结。离线 Product Pack、EAV SQLite、事实卡和待索引文档可重复生成。
- V2-6B 已构建独立的 12-document/1024 维 Laptop Chroma，并完成 Product Query、KB Search、Reranker、Evidence Check 与 Checker 的工具闭环；冻结的独立 30 条检索集首次 Recall@5 为 30/30，跨品类召回为 0。
- V2-6C 首次 Regression 经四轮定向修复达到 10/10，但首次 Holdout 只有 3/10、推荐证据覆盖 3/9；该 Holdout 已永久改为 `exposed_holdout_regression_v1`，历史结果不可覆盖。
- V2-6C-R1 已增加确定性商品身份与不可扩大的 Candidate Scope。只对已暴露 20 条执行零 API 回归：Regression 10/10、已暴露 Holdout 10/10、推荐事实证据 75/75、Scope/Checker 越界 0；这不是新 Holdout，V2-6C 仍未完成。
- V2-6C-R2A 已创建并冻结 20 条第二套 Laptop Holdout，Schema、ID、确定性金标和数据自洽校验通过，Agent E2E 运行次数为 0；它是代码冻结后创建的第二验证集，不是第三方盲测。只有获得后续授权才可执行首次单次评测。
- 剩余 10 条 specialist 的金标已经审阅但尚未运行，只能作为 `unrun_exposed_specialist` 诊断回归；Ranker、Memory 专项、完整故障矩阵和 V2-7 均未开始。
- 每个阶段完成后必须测试、提交、推送并停止，等待用户确认。
