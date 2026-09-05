# 项目结构说明

## 文档元信息

| 项目 | 内容 |
|---|---|
| 最后更新时间 | 2026-09-05 |
| 当前阶段 | V1 已冻结；V2-9H 已冻结 `proofpick-v2-rc3` 供独立评测，Trusted Core 为默认 Stable，Online Research 为 Experimental/Beta；未创建 Tag/Release/PR |
| 结构生成范围 | 根目录、自研 `smartbuy/`、隔离 `experiments/`、供应商目录的维护入口与关键子目录 |
| 排除目录 | `.git`、`.venv`、`__pycache__`、`node_modules`、模型缓存、构建产物、运行数据库、向量索引、MinIO 数据和临时文件 |
| 更新规则 | 新增、删除、移动、重命名文件，或文件职责/入口/配置明显变化时，必须在同一 Commit 中更新本文 |

本文是项目结构的事实来源，不承担技术架构设计职责。技术路线、阶段计划和验收要求见 [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)。

## 当前真实结构

```text
proofpick_agent/
├─ .github/
│  └─ workflows/
│     ├─ ci.yml
│     └─ pages.yml
├─ .gitattributes
├─ .gitignore
├─ LICENSE
├─ README.md
├─ THIRD_PARTY_NOTICES.md
├─ experiments/
│  └─ langgraph_poc/
│     ├─ tests/
│     │  ├─ conftest.py
│     │  ├─ test_acceptance_matrix.py
│     │  └─ test_v1_replay_and_comparison.py
│     ├─ results/
│     │  └─ poc_summary.json
│     ├─ README.md
│     ├─ benchmark.py
│     ├─ checkpoint.py
│     ├─ checkpoint_worker.py
│     ├─ contracts.py
│     ├─ fake_provider.py
│     ├─ fake_tools.py
│     ├─ fixtures.py
│     └─ graph.py
├─ smartbuy/
│  ├─ __init__.py
│  ├─ agent/
│  │  ├─ domain_agent.py
│  │  ├─ domain_gateway.py
│  │  ├─ ranking.py
│  │  ├─ react.py
│  │  └─ reporting.py
│  ├─ cache/
│  │  ├─ __init__.py
│  │  ├─ adapters.py
│  │  └─ safe_cache.py
│  ├─ constraints/
│  │  ├─ __init__.py
│  │  ├─ models.py
│  │  ├─ normalize.py
│  │  ├─ scoring.py
│  │  └─ verifier.py
│  ├─ constraint_proposals/
│  │  ├─ __init__.py
│  │  ├─ coordinator.py
│  │  ├─ engine.py
│  │  ├─ models.py
│  │  ├─ provider.py
│  │  ├─ spans.py
│  │  └─ settings.py
│  ├─ contracts/
│  │  ├─ __init__.py
│  │  ├─ models.py
│  │  └─ product_pack.py
│  ├─ api/
│  │  ├─ portfolio_runtime.py  # 默认关闭的 Laptop/Headphone V2 UI 运行时
│  │  └─ router.py
│  ├─ config/
│  │  ├─ __init__.py
│  │  └─ bailian.py
│  ├─ data/
│  │  ├─ headphone/
│  │  │  └─ headphone_configurations_v1.json
│  │  ├─ laptop/
│  │  │  └─ laptop_configurations_v1.json
│  │  ├─ catalog/
│  │  │  └─ monitors_v1.json
│  │  ├─ demo/
│  │  │  ├─ fact_cards/        # 12 份自制型号事实卡
│  │  │  └─ manifest.json
│  │  ├─ processed/
│  │  │  ├─ products.jsonl
│  │  │  ├─ price_observations.jsonl
│  │  │  ├─ source_records.jsonl
│  │  │  ├─ evidence_records.jsonl
│  │  │  ├─ index_manifest.json
│  │  │  ├─ stage3_retrieval_results.json
│  │  │  ├─ stage4_dry_run_results.json
│  │  │  ├─ stage4_e2e_results.json
│  │  │  ├─ stage4_postfix_s4_014_results.json
│  │  │  ├─ stage5_fixed_ablation_results.json
│  │  │  ├─ stage5_agent_dry_run_results.json
│  │  │  ├─ stage5_agent_e2e_results.json
│  │  │  ├─ stage5_agent_regression_results.json
│  │  │  ├─ stage5_agent_s4_012_regression_results.json
│  │  │  ├─ stage5_agent_s4_012_order_regression_results.json
│  │  │  ├─ stage6_*            # 冻结评测、首次失败、账本、缓存、故障与汇总结果
│  │  │  ├─ stage7_*            # 发布候选、定向修复与 Demo 脱敏结果
│  │  │  ├─ v2_stage5_*         # 旧基线、首次实现失败和修复后冻结表达结果
│  │  │  ├─ v2_stage5b_*        # 四条失败审计与不可覆盖的 Live qwen-plus 首测结果
│  │  │  └─ v2_stage5c_*        # 已暴露回归与新 Live Holdout V2 的机器可读首测摘要
│  │  ├─ raw/
│  │  │  └─ README.md
│  │  ├─ __init__.py
│  │  ├─ derive.py
│  │  ├─ loader.py
│  │  └─ quality.py
│  ├─ db/
│  │  ├─ __init__.py
│  │  ├─ build_database.py
│  │  └─ schema_v1.sql
│  ├─ docs/
│  │  ├─ assets/                 # WebUI 实图、脱敏回放与 README 架构图
│  │  ├─ adr/
│  │  │  ├─ 0001-vendor-youtu-rag.md
│  │  │  ├─ 0002-bailian-provider-and-index-contract.md
│  │  │  ├─ 0003-governed-monitor-data-and-index.md
│  │  │  ├─ 0004-bounded-react-evidence-and-memory.md
│  │  │  ├─ 0005-deterministic-constraint-gate.md
│  │  │  ├─ 0006-reproducible-evaluation-cache-and-resilience.md
│  │  │  ├─ 0007-langgraph-orchestration-decision.md
│  │  │  ├─ 0008-langgraph-compatibility-and-checkpointing.md
│  │  │  ├─ 0009-domain-contracts-and-monitor-pack.md
│  │  │  ├─ 0010-versioned-product-pack-and-evidence-ledger.md
│  │  │  ├─ 0011-auditable-zhipu-source-search.md
│  │  │  ├─ 0012-governed-web-extraction-and-open-evidence.md
│  │  │  ├─ 0013-regional-evidence-comparability.md
│  │  │  ├─ 0014-validated-constraint-proposals-and-clarification.md
│  │  │  ├─ 0015-server-verified-quote-to-span.md
│  │  │  ├─ 0016-deterministic-product-identity-and-candidate-scope.md
│  │  │  ├─ 0017-deterministic-safety-gates-and-release-evaluation.md
│  │  │  ├─ 0018-deterministic-ranking-and-layered-memory.md
│  │  │  ├─ 0019-headphone-source-authority-and-pack-reuse.md
│  │  │  ├─ 0020-separate-query-intent-scope-and-purchase-constraints.md
│  │  │  ├─ 0021-generalized-intent-online-evidence-and-semantic-manifest.md
│  │  │  └─ 0022-bounded-official-source-discovery-and-extraction.md
│  │  ├─ archive/
│  │  │  └─ FINAL_多源消费决策研究Agent开发交接总文档.md
│  │  ├─ development/
│  │  │  ├─ DEVELOPMENT_GUIDE.md
│  │  │  └─ PROJECT_STRUCTURE.md
│  │  ├─ release/
│  │  │  └─ v1.0.0-portfolio-release-notes.md
│  │  ├─ setup/
│  │  │  └─ 阿里云百炼API-Key调用与Youtu-RAG接入说明.md
│  │  ├─ v2/
│  │  │  ├─ README.md
│  │  │  ├─ ProofPick_V2_目标与实现路径.md
│  │  │  ├─ V2_DEVELOPMENT_PROCESS.md
│  │  │  ├─ v2_1_implementation_design.md
│  │  │  ├─ v2_1_langgraph_poc_plan.md
│  │  │  ├─ v2_1_langgraph_poc_report.md
│  │  │  ├─ v2_1c_compatibility_report.md
│  │  │  ├─ v2_1c_runtime.md
│  │  │  ├─ v2_1d_domain_pack_report.md
│  │  │  ├─ v2_1d_runtime.md
│  │  │  ├─ v2_2_product_pack_report.md
│  │  │  ├─ v2_2_runtime.md
│  │  │  ├─ v2_3_source_search_report.md
│  │  │  ├─ v2_3_runtime.md
│  │  │  ├─ v2_4_open_research_report.md
│  │  │  ├─ v2_4_runtime.md
│  │  │  ├─ v2_4c_regional_evidence_report.md
│  │  │  ├─ v2_5_constraint_clarification_report.md
│  │  │  ├─ v2_5_expression_eval.md
│  │  │  ├─ v2_5_runtime.md
│  │  │  ├─ v2_5b_live_provider_validation_report.md
│  │  │  ├─ v2_5c_quote_span_report.md
│  │  │  ├─ v2_5c_quote_span_runtime.md
│  │  │  ├─ v2_5c_live_holdout_v2_data_card.md
│  │  │  ├─ v2_6a_laptop_domain_and_data_report.md
│  │  │  ├─ v2_6a_laptop_data_card.md
│  │  │  ├─ v2_6a_laptop_runtime.md
│  │  │  ├─ v2_6b_laptop_toolchain_report.md
│  │  │  ├─ v2_6b_laptop_index_runtime.md
│  │  │  ├─ v2_6c_r_failed_holdout_audit.md
│  │  │  ├─ v2_6c_identity_scope_failure_audit.md
│  │  │  ├─ v2_6c_identity_scope_repair_report.md
│  │  │  ├─ v2_6c_second_holdout_data_card.md
│  │  │  ├─ v2_6c_r2b_second_holdout_report.md
│  │  │  ├─ v2_6c_r3_generic_decision_core_report.md
│  │  │  ├─ v2_6c_r4_laptop_engineering_closeout.md
│  │  │  ├─ v2_6c_r4_runtime.md
│  │  │  ├─ v2_7_explainable_ranking_report.md
│  │  │  ├─ v2_7_memory_runtime.md
│  │  │  ├─ v2_8_headphone_domain_report.md
│  │  │  ├─ v2_8_headphone_data_card.md
│  │  │  ├─ v2_8_three_domain_evaluation.md
│  │  │  ├─ v2_8_headphone_runtime.md
│  │  │  ├─ v2_9f_online_research_repair_report.md
│  │  │  ├─ v2_9f_online_research_runtime.md
│  │  │  ├─ v2_9g_online_scope_and_feasibility_report.md
│  │  │  ├─ v2_release_candidate_rc3_manifest.md
│  │  │  ├─ v2_9h_rc3_release_candidate_report.md
│  │  │  ├─ v2_9h_windows_reproduction.md
│  │  │  └─ v2_9h_rc3_handoff.md
│  │  ├─ data_card.md
│  │  ├─ runtime_manifest.md
│  │  ├─ stage1_smoke_test.md
│  │  ├─ stage2_bailian_verification.md
│  │  ├─ stage3_data_and_retrieval_report.md
│  │  ├─ stage4_agent_workflow_report.md
│  │  ├─ stage5_constraint_verification_report.md
│  │  ├─ stage6_evaluation_and_resilience_report.md
│  │  ├─ demo_guide.md
│  │  ├─ portfolio_metrics.md
│  │  ├─ release_checklist.md
│  │  └─ release_report.md
│  ├─ domain/
│  │  └─ models.py
│  ├─ decision_core/
│  │  ├─ canonical.py
│  │  ├─ delta.py
│  │  ├─ intent.py
│  │  ├─ result.py
│  │  ├─ safety.py
│  │  └─ scope.py
│  ├─ identity/
│  │  ├─ __init__.py
│  │  ├─ guards.py
│  │  ├─ models.py
│  │  └─ resolver.py
│  ├─ domain_packs/
│  │  ├─ headphone/
│  │  │  ├─ manifest.json
│  │  │  ├─ fields.json
│  │  │  └─ policies.json
│  │  ├─ laptop/
│  │  │  ├─ manifest.json
│  │  │  ├─ fields.json
│  │  │  └─ policies.json
│  │  ├─ monitor/
│  │  │  ├─ manifest.json
│  │  │  ├─ fields.json
│  │  │  └─ policies.json
│  │  ├─ __init__.py
│  │  ├─ evaluator.py
│  │  ├─ loader.py
│  │  ├─ orchestrator.py
│  │  ├─ registry.py
│  │  ├─ scope.py
│  │  ├─ settings.py
│  │  └─ v1_adapter.py
│  ├─ eval/
│  │  ├─ __init__.py
│  │  ├─ cases.jsonl
│  │  ├─ run_retrieval_eval.py
│  │  ├─ stage4_cases.jsonl
│  │  ├─ run_stage4_eval.py
│  │  ├─ stage5_natural_cases.jsonl
│  │  ├─ stage5_fault_cases.jsonl
│  │  ├─ run_stage5_eval.py
│  │  ├─ stage6_config.json
│  │  ├─ stage6_natural_cases.jsonl
│  │  ├─ stage6_failure_cases.jsonl
│  │  ├─ stage6_memory_cases.jsonl
│  │  ├─ stage6_scoring.py
│  │  ├─ run_stage6_eval.py
│  │  ├─ run_stage6_resilience.py
│  │  ├─ run_stage6_cache_benchmark.py
│  │  ├─ run_stage6_checker_determinism.py
│  │  ├─ merge_stage6_checkpoints.py
│  │  ├─ build_stage6_artifacts.py
│  │  ├─ v2_stage5_expression_cases.jsonl
│  │  ├─ v2_stage5_expression_manifest.json
│  │  ├─ run_v2_constraint_eval.py
│  │  ├─ v2_stage5b_live_holdout.jsonl
│  │  ├─ v2_stage5b_live_holdout_manifest.json
│  │  ├─ run_v2_live_constraint_holdout.py
│  │  ├─ v2_stage5c_live_holdout_v2.jsonl
│  │  ├─ v2_stage5c_live_holdout_v2_manifest.json
│  │  ├─ run_v2_quote_span_live_eval.py
│  │  ├─ run_v2_9f_online_regression.py
│  │  ├─ v2_6a_laptop_cases.jsonl
│  │  ├─ v2_6b_laptop_retrieval_cases.jsonl
│  │  ├─ v2_6b_laptop_retrieval_runner.py
│  │  ├─ v2_8_headphone_retrieval_cases.jsonl
│  │  ├─ v2_8_headphone_retrieval_runner.py
│  │  ├─ v2_8_headphone_engineering_cases.jsonl
│  │  ├─ v2_8_headphone_engineering_runner.py
│  │  ├─ v2_6c_laptop_agent_runner.py
│  │  ├─ v2_6c_laptop_scoring_policy.json
│  │  ├─ v2_6c_r1_identity_scope_replay.py
│  │  ├─ v2_6c_r2_laptop_holdout.jsonl
│  │  ├─ v2_6c_r2_laptop_holdout.schema.json
│  │  ├─ v2_6c_r2_laptop_scoring_policy.json
│  │  ├─ v2_6c_r2_laptop_scorer.py
│  │  ├─ v2_6c_r2_laptop_runner.py
│  │  ├─ v2_6c_r3_exposed_runner.py
│  │  ├─ v2_6c_r3_validation.schema.json
│  │  ├─ v2_6c_r3_validation_generator.py
│  │  ├─ v2_6c_r3_validation_round2_generator.py
│  │  ├─ v2_6c_r3_validation_round3_generator.py
│  │  ├─ v2_6c_r3_validation_runner.py
│  │  ├─ v2_6c_r3_validation_scorer.py
│  │  ├─ v2_6c_r3_validation_round*.jsonl
│  │  ├─ v2_6c_r3_validation_round*_manifest.json
│  │  ├─ v2_6c_r3_validation_round*_policy.json
│  │  ├─ results/v2_6c_r4_exposed_regression_iteration*.json
│  │  └─ results/
│  │     ├─ v2_6b_laptop_retrieval_first.json
│  │     ├─ v2_6c_*            # 历史失败、暴露回归及 R2/R3 冻结 RC、Journal、首次结果；不可覆盖
│  │     ├─ v2_8_headphone_*   # Headphone 检索、工程首次/暴露回归与 Open Research 脱敏结果
│  │     ├─ v2_9e_*            # 第二次独立评测后的 Trusted/Online 暴露回归与语义 Manifest
│  │     ├─ v2_9f_*            # Online 修复前漏斗、评测器事故和唯一有效 exposed regression
│  │     ├─ v2_9g_*            # 单调漏斗审计、Playwright/Bocha 有限 PoC 原始记录与语义复核
│  │     └─ v2_9h_*            # RC3 稳定语义 Manifest 与 Windows 干净复现摘要
│  ├─ memory/
│  │  ├─ domain_store.py       # V2 全局/品类分层偏好、版本/过期及摘要身份隔离
│  │  └─ store.py              # V1 会话与长期偏好兼容实现
│  ├─ ranking/
│  │  ├─ __init__.py
│  │  ├─ models.py             # 领域无关排名请求、候选、维度和解释契约
│  │  ├─ profile.py            # Domain Pack Ranking Profile 校验与场景选择
│  │  └─ ranker.py             # Checker 合规集合上的确定性 Evidence-backed 排序
│  ├─ observability/
│  │  ├─ __init__.py
│  │  ├─ agent_events.py
│  │  ├─ eval_ledger.py
│  │  └─ usage.py
│  ├─ open_research/
│  │  ├─ __init__.py
│  │  ├─ evidence_check.py
│  │  ├─ extractor.py
│  │  ├─ html_parser.py
│  │  ├─ models.py
│  │  ├─ normalizer.py
│  │  ├─ pdf_parser.py
│  │  ├─ service.py
│  │  ├─ settings.py
│  │  ├─ store.py
│  │  └─ url_safety.py
│  ├─ orchestration/
│  │  ├─ __init__.py
│  │  ├─ checkpoints.py
│  │  ├─ contracts.py
│  │  ├─ langgraph_adapter.py
│  │  ├─ react_adapter.py
│  │  ├─ safety.py
│  │  └─ selector.py
│  ├─ providers/
│  │  ├─ __init__.py
│  │  ├─ bailian.py
│  │  └─ zhipu_search.py
│  ├─ product_packs/
│  │  ├─ examples/
│  │  │  ├─ headphone-v1/
│  │  │  │  └─ pack.json
│  │  │  ├─ laptop-v1/
│  │  │  │  └─ pack.json
│  │  │  └─ monitor-u2725qe-us/
│  │  │     └─ pack.json
│  │  ├─ schema/
│  │  │  └─ product-pack-v1.schema.json
│  │  ├─ __init__.py
│  │  ├─ builder.py
│  │  ├─ cli.py
│  │  ├─ domain_builder.py
│  │  ├─ domain_cli.py
│  │  ├─ ledger.py
│  │  ├─ live_index.py
│  │  ├─ loader.py
│  │  ├─ models.py
│  │  └─ runtime.py
│  ├─ reproducibility/
│  │  ├─ __init__.py
│  │  ├─ semantic_manifest.py   # 排除时间/路径/费用等运行噪声的稳定语义合同
│  │  ├─ v2_9e_manifest.py      # 从不可变生产 Commit 枚举成员并生成 V2-9E Manifest
│  │  └─ v2_9h_rc3_manifest.py  # 冻结 RC3 的完整成员组、能力边界与三品类运行合同
│  ├─ portfolio/
│  │  ├─ demos.py              # 严格加载五个脱敏回放
│  │  ├─ dynamic_facts.py      # URL/币种/时间/TTL/hash 动态观察安全判断
│  │  └─ models.py             # UI 候选、Evidence、轨迹和回放 Schema
│  ├─ retrieval/
│  │  ├─ __init__.py
│  │  ├─ domain_index.py
│  │  └─ knowledge_base.py
│  ├─ source_search/
│  │  ├─ __init__.py
│  │  ├─ cache.py
│  │  ├─ models.py
│  │  ├─ provider.py
│  │  ├─ settings.py
│  │  └─ validator.py
│  ├─ tools/
│  │  ├─ base.py
│  │  ├─ domain.py
│  │  ├─ evidence_check.py
│  │  ├─ kb_search.py
│  │  ├─ source_search.py
│  │  ├─ text2sql.py
│  │  ├─ web_extractor.py
│  │  └─ web_search.py
│  ├─ scripts/
│  │  ├─ __init__.py
│  │  ├─ bootstrap.ps1
│  │  ├─ build_headphone_product_pack.py
│  │  ├─ build_laptop_product_pack.py
│  │  ├─ build_stage3_data.py
│  │  ├─ build_stage3_index.py
│  │  ├─ check_markdown_links.py
│  │  ├─ preflight.ps1
│  │  ├─ replay.ps1
│  │  ├─ start.ps1
│  │  ├─ start_youtu_rag.ps1
│  │  ├─ stop.ps1
│  │  ├─ validate_stage3_data.py
│  │  ├─ verify_bailian_stage2.py
│  │  ├─ verify_v2_source_search.py
│  │  ├─ verify_v2_product_pack_live.py
│  │  ├─ verify_v2_open_research.py
│  │  ├─ verify_v2_6c_laptop_open_research.py
│  │  ├─ verify_v2_8_headphone_open_research.py
│  │  ├─ verify_v2_9a_demos.py
│  │  ├─ build_v2_release_runtime.py
│  │  ├─ verify_stage7_demos.py
│  │  └─ verify_stage3_index.py
│  └─ tests/
│     ├─ fixtures/
│     │  ├─ stage1_baseline.md
│     │  └─ v2_checkpoint_worker.py
│     ├─ integration/
│     │  ├─ test_stage4_api.py
│     │  ├─ test_v2_headphone_domain_pack.py
│     │  ├─ test_v2_headphone_toolchain.py
│     │  ├─ test_v2_three_domain_isolation.py
│     │  ├─ test_v2_laptop_domain_pack.py
│     │  ├─ test_v2_laptop_agent_e2e.py
│     │  ├─ test_v2_open_research_agent.py
│     │  ├─ test_v2_source_search_agent.py
│     │  ├─ test_v2_live_product_index.py
│     │  ├─ test_v2_product_pack_pipeline.py
│     │  ├─ test_v2_domain_pack_compat.py
│     │  ├─ test_v2_api_orchestration.py
│     │  ├─ test_v2_sqlite_checkpoint.py
│     │  └─ test_youtu_bailian_adapters.py
│     └─ unit/
│        ├─ test_bailian_config.py
│        ├─ test_bailian_provider.py
│        ├─ test_stage3_data.py
│        ├─ test_stage3_database.py
│        ├─ test_stage3_retrieval_contract.py
│        ├─ test_stage4_agent.py
│        ├─ test_stage4_evidence.py
│        ├─ test_stage4_kb_search.py
│        ├─ test_stage4_memory.py
│        ├─ test_stage4_text2sql.py
│        ├─ test_stage5_agent_gate.py
│        ├─ test_stage5_constraints.py
│        ├─ test_stage5_verifier.py
│        ├─ test_stage6_cache.py
│        ├─ test_stage6_eval_contract.py
│        ├─ test_stage7_reporting.py
│        ├─ test_v2_orchestration_contract.py
│        ├─ test_v2_domain_pack.py
│        ├─ test_v2_product_pack.py
│        ├─ test_v2_open_research.py
│        ├─ test_v2_headphone_open_research.py
│        ├─ test_v2_product_identity_scope.py
│        ├─ test_v2_portfolio.py
│        └─ test_v2_source_search.py
└─ vendor/
   └─ youtu-rag/
      ├─ configs/
      ├─ frontend/rag_webui/
      │  ├─ app.html            # ProofPick V2 产品首页
      │  ├─ classic.html        # 保留的 Youtu-RAG 经典入口
      │  └─ assets/             # V2 CSS、JS 与五 Demo 脱敏 JSON
      ├─ tests/
      ├─ utu/
      ├─ LICENSE
      ├─ README.md
      ├─ pyproject.toml
      └─ uv.lock
```

`vendor/youtu-rag/` 包含完整固定上游源码，树中只展开维护入口，未逐项列出所有上游文件。上游固定 Commit、版本和差异见 [Runtime Manifest](../runtime_manifest.md) 与 [THIRD_PARTY_NOTICES.md](../../../THIRD_PARTY_NOTICES.md)。

## 文件与目录职责

| 路径 | 职责 |
|---|---|
| `.gitignore` | 排除凭据文件、虚拟环境、缓存、日志、运行数据库、向量索引和模型文件 |
| `.gitattributes` | 固定版本化数据、事实卡与冻结评测夹具为 LF，并将 `vendor/**` 标记为 GitHub Linguist vendored |
| `.github/workflows/ci.yml` | 在 Windows/Python 3.12 上执行无百炼 Secret、无外部服务和无模型费用的离线质量门 |
| `.github/workflows/pages.yml` | 只将脱敏回放 HTML 与白名单 PNG 发布到 GitHub Pages，不包含运行数据或配置 |
| `README.md` | 面向招聘者的项目定位、Demo、核心代码、量化结果与四行启动入口 |
| `smartbuy/docs/development/DEVELOPMENT_GUIDE.md` | 项目范围、架构、数据、模型、指标、阶段计划、DoD 和 Git 工作流的主要依据 |
| `smartbuy/docs/development/PROJECT_STRUCTURE.md` | 当前真实结构和职责的事实来源 |
| `smartbuy/docs/archive/FINAL_多源消费决策研究Agent开发交接总文档.md` | 原始规格、调研和总体完成定义；仅移动归档，保持原名与原内容 |
| `smartbuy/docs/setup/阿里云百炼API-Key调用与Youtu-RAG接入说明.md` | 百炼 API 安全、端点、模型和 Youtu-RAG 适配说明；仅移动到 setup，内容未改 |
| `smartbuy/docs/v2/README.md` | V2 文档入口与当前真实阶段状态 |
| `smartbuy/docs/v2/ProofPick_V2_目标与实现路径.md` | V2 产品目标、Trusted/Open 模式、目标架构、阶段路线和完成边界 |
| `smartbuy/docs/v2/V2_DEVELOPMENT_PROCESS.md` | V2 分支、阶段门、测试、成本、提交和停止规则 |
| `smartbuy/docs/v2/v2_1_implementation_design.md` | V2-1A 硬编码清单、通用契约、Monitor Domain Pack、V1 兼容与回滚设计 |
| `smartbuy/docs/v2/v2_1_langgraph_poc_plan.md` | V2-1B Fake Provider PoC 的冻结状态图、并行、恢复、澄清、安全门和决策标准 |
| `smartbuy/docs/v2/v2_1_langgraph_poc_report.md` | 20 类 PoC 矩阵、量化对比、首次失败、V1 回归、隔离边界和采用建议 |
| `smartbuy/docs/v2/v2_1c_compatibility_report.md` | V2-1C 统一契约、显式开关、Checker 终态、Checkpoint 安全、兼容测试和采用边界 |
| `smartbuy/docs/v2/v2_1c_runtime.md` | 默认 ReAct、显式 LangGraph、仓库外 Checkpoint 和安全回滚的 Windows 运行说明 |
| `smartbuy/docs/v2/v2_1d_domain_pack_report.md` | 通用契约、Monitor Pack、V1 往返兼容、冻结证据、测试和 V2-2 前置条件 |
| `smartbuy/docs/v2/v2_1d_runtime.md` | 默认关闭的 Domain Pack 开关、显式验证、fail-closed 与无迁移回滚说明 |
| `smartbuy/docs/v2/v2_2_product_pack_report.md` | 测试计数审计、Product Pack/Ledger、第 13 个显示器、幂等构建、工具链和失败回滚证据 |
| `smartbuy/docs/v2/v2_2_runtime.md` | 仓库外导入、校验、发布、版本查看、回滚、特性开关与索引状态说明 |
| `smartbuy/docs/v2/v2_3_source_search_report.md` / `v2_3_runtime.md` | Provider 选型历史、6/8 精确地区覆盖、安全降级、错误/缓存/成本证据和默认关闭运行方式 |
| `smartbuy/docs/v2/v2_4_open_research_report.md` / `v2_4_runtime.md` | 数据库外真实抽取、SSRF/失败矩阵、Open/Trusted 隔离、临时证据生命周期、成本和运行开关 |
| `smartbuy/docs/v2/v2_4c_regional_evidence_report.md` | V2-4 假通过审计、目标地区/跨地区分层语义、专项回归与 PD3226G 离线回放证据 |
| `smartbuy/docs/v2/v2_5_constraint_clarification_report.md` / `v2_5_runtime.md` | V2-5 Proposal/澄清实现、冻结指标、首次失败、双编排器暂停恢复、显式开关与回滚说明 |
| `smartbuy/docs/v2/v2_5b_live_provider_validation_report.md` | 四条 Regression 失败口径、原 Holdout 独立性和 12 条真实 qwen-plus Live Holdout 首测证据 |
| `smartbuy/docs/v2/v2_5c_quote_span_report.md` / `v2_5c_quote_span_runtime.md` | 服务端精确 Quote-to-Span、旧暴露回归、新 20 条首测、安全门、运行与回滚说明 |
| `smartbuy/docs/v2/v2_5c_live_holdout_v2_data_card.md` | 新 20 条一次性 Live Holdout V2 的冻结 SHA、覆盖、评分、不变性和限制 |
| `smartbuy/docs/v2/v2_6a_laptop_domain_and_data_report.md` / `v2_6a_laptop_runtime.md` | 第二品类前置审计、Pack/数据/构建证据、离线复现命令和 V2-6B 边界 |
| `smartbuy/docs/v2/v2_6a_laptop_data_card.md` | 12 个精确笔记本配置的范围、来源权限、缺失率、证据覆盖和许可边界 |
| `smartbuy/docs/v2/v2_6b_laptop_toolchain_report.md` / `v2_6b_laptop_index_runtime.md` | Laptop 字段/缺失/分母审计、SQLite/真实索引、检索指标、五工具闭环、成本与复现边界 |
| `smartbuy/docs/v2/v2_6c_identity_scope_failure_audit.md` | 30 条任务资格、七条失败链路、正确拒答案例和首错节点的不可覆盖审计 |
| `smartbuy/docs/v2/v2_6c_identity_scope_repair_report.md` | R1 通用身份/Scope 契约、工具链边界、证据闭包、20 条暴露回归和新 Holdout 前置条件 |
| `smartbuy/docs/v2/v2_6c_second_holdout_data_card.md` | R2A 第二套 20 条 Laptop 验证集的分布、确定性金标复核、冻结哈希、评分门槛和独立性边界 |
| `smartbuy/docs/v2/v2_6c_r2b_second_holdout_report.md` | R2B 唯一首次运行的 RC、2/20 结果、18条失败、费用、安全门和 JavaScript 口径审计 |
| `smartbuy/docs/v2/v2_6c_r3_generic_decision_core_report.md` | 通用决策契约、暴露回归、三轮冻结验证、API 成本、第三轮失败与硬停止结论 |
| `smartbuy/docs/v2/v2_6c_r4_laptop_engineering_closeout.md` / `v2_6c_r4_runtime.md` | 122 条暴露工程回归、确定性安全门、Laptop Open Research、Memory、故障矩阵、双编排器一致性及复核命令 |
| `smartbuy/docs/adr/0017-deterministic-safety-gates-and-release-evaluation.md` | 保留三轮失败历史，以安全不变量和暴露回归完成工程收尾，并把新鲜 RC 评测推迟到 V2-9 |
| `smartbuy/ranking/` | Domain Pack Profile 驱动、只排序 Checker 合规候选的确定性 Ranker 与公开解释契约 |
| `smartbuy/memory/domain_store.py` | V2 Global/Category 分层偏好、确认/过期/版本失效及摘要身份存储 |
| `smartbuy/docs/v2/v2_7_explainable_ranking_report.md` / `v2_7_memory_runtime.md` | V2-7 评分公式、10 个场景、12 条 What-if、不变量、Memory 生命周期与运行边界 |
| `smartbuy/docs/adr/0018-deterministic-ranking-and-layered-memory.md` | Checker 唯一资格所有权、Pack-owned Profile、Evidence gate 和分层 Memory 决策 |
| `smartbuy/docs/v2/v2_8_headphone_domain_report.md` / `v2_8_headphone_runtime.md` | V2-8 Headphone 数据、真实索引、检索/工程评测、Open Research、成本及复现边界 |
| `smartbuy/docs/v2/v2_8_headphone_data_card.md` | 12 个精确耳机配置、三层来源权限、缺失率、Evidence 覆盖和可重建哈希 |
| `smartbuy/docs/v2/v2_8_three_domain_evaluation.md` | Monitor、Laptop、Headphone 的字段、数据、索引、Evidence、Memory 与编排资格隔离证据 |
| `smartbuy/docs/v2/v2_9a_release_candidate_report.md` | V2-9A 产品 UI、五 Demo、动态事实边界、成本、RC 与 V2-9B 交接结论 |
| `smartbuy/docs/v2/v2_9a_windows_reproduction.md` | 新短 ASCII 克隆、冻结依赖、三 SQLite/索引、HTTP、回放与端口释放实测 |
| `smartbuy/docs/v2/v2_demo_guide.md` | 五个固定输入的在线/本地真实路径、脱敏回放、预期结果与失败备用步骤 |
| `smartbuy/docs/v2/v2_release_candidate_manifest.md` | V2-9B 使用的 Commit、锁、Pack/Data/Index、模型、Schema、数据和评测哈希快照 |
| `smartbuy/docs/v2/v2_9a_handoff.md` | 未发布的 PR 草案、V1/V2 边界、回滚与独立评测纪律 |
| `smartbuy/docs/v2/v2_9c_independent_evaluation_repair_report.md` | V2-9B 首次 26 条失败的七类归因、通用修复、90 条 exposed regression、Online 边界与发布判断 |
| `smartbuy/docs/v2/v2_release_candidate_rc2_manifest.md` | RC2 的生产 Commit/Tree、完整冻结成员列表、聚合哈希、三品类运行版本与质量基线 |
| `smartbuy/docs/v2/v2_9c_rc2_handoff.md` | RC2 历史结果边界、Windows 复现证据及下一轮独立评测纪律 |
| `smartbuy/eval/results/v2_9c_exposed_regression_summary.json` | 同一独立题集的脱敏已暴露回归评分；不是新 Holdout 或发布结论 |
| `smartbuy/docs/v2/v2_9e_generalization_repair_report.md` | V2-9D 失败归因、通用修复、90+15 条暴露回归、Online 漏斗、费用与继续阻断发布的结论 |
| `smartbuy/eval/results/v2_9e_exposed_*` | V2-9D 已暴露题集的 Trusted 首次修复回归和三轮 Online 漏斗结果；不覆盖独立首次证据 |
| `smartbuy/eval/results/v2_9e_semantic_runtime_manifest.json` | 生产 Commit/Tree、三品类 Data/Index 合同和七组完整成员列表的可移植语义 Manifest |
| `smartbuy/docs/release/v2_portfolio_release_notes_draft.md` | 仅供后续审核的 V2 Portfolio Release Notes 草案，本轮不发布 |
| `smartbuy/docs/adr/0019-headphone-source-authority-and-pack-reuse.md` | Headphone 三层来源权限、主观证据边界及通用 Checker/Ranker 复用决策 |
| `smartbuy/docs/adr/0020-separate-query-intent-scope-and-purchase-constraints.md` | 事实/比较字段、商品 Scope、购买约束、澄清和证据闭包的通用边界决策 |
| `smartbuy/docs/adr/0021-generalized-intent-online-evidence-and-semantic-manifest.md` | V2-9E 通用语义修复、官方来源漏斗、Open/Trusted 隔离和稳定 Manifest 决策 |
| `smartbuy/docs/v2/v2_9f_online_research_repair_report.md` / `v2_9f_online_research_runtime.md` | V2-9F 修复前后漏斗、逐条 exposed 结果、静态 HTML/PDF 边界、费用、运行方式与 RC3 阻断结论 |
| `smartbuy/eval/results/v2_9f_*` | 修改前失败漏斗、不可覆盖的评测器事故、唯一有效 15 条 exposed Online 结果及其独立运行 Manifest |
| `smartbuy/docs/adr/0022-bounded-official-source-discovery-and-extraction.md` | 多查询官方来源发现、型号绑定相关页、静态多格式提取与 Open/Trusted 安全边界 |
| `smartbuy/docs/v2/v2_9g_online_scope_and_feasibility_report.md` | 严格任务 lineage 漏斗、默认关闭 Playwright/Bocha PoC、门槛判断与 Online 发布范围收敛 |
| `smartbuy/docs/adr/0023-trusted-core-and-experimental-online-research.md` | RC3 以 Trusted Multi-domain Decision Core 为候选范围、Online 保持 Experimental/Beta 的决策 |
| `smartbuy/eval/audit_v2_9g_online_funnel.py` / `results/v2_9g_monotonic_funnel_audit.json` | 将候选级并行分支与任务级单调漏斗分开计算的只读审计器和结果 |
| `smartbuy/eval/v2_9g_feasibility.py` / `run_v2_9g_feasibility_poc.py` | 不接生产主链、默认关闭的受控 Playwright 与 Bocha 失败类型 PoC |
| `smartbuy/tests/fixtures/v2_9g/` / `unit/test_v2_9g_online_feasibility.py` | 虚构商品渲染页、默认关闭/地区门与单调漏斗测试，不含评测商品答案 |
| `smartbuy/docs/v2/v2_release_candidate_rc3_manifest.md` / `eval/results/v2_9h_rc3_semantic_runtime_manifest.json` | RC3 生产 Commit/Tree、19 组完整成员、三品类版本、发布门槛及稳定 Payload Hash |
| `smartbuy/docs/v2/v2_9h_rc3_release_candidate_report.md` / `v2_9h_rc3_handoff.md` | Trusted Stable 与 Online Experimental 范围、历史结果边界和独立评测纪律 |
| `smartbuy/docs/v2/v2_9h_windows_reproduction.md` / `eval/results/v2_9h_rc3_windows_verification.json` | 新短 ASCII clone、冻结依赖、三 SQLite/索引、HTTP、五 Demo 与端口释放证据 |
| `smartbuy/reproducibility/v2_9h_rc3_manifest.py` | 从不可变 RC3 生产 Commit 枚举完整成员并生成可重复 Semantic Manifest |
| `smartbuy/docs/v2/v2_5_expression_eval.md` | 50 条新表达的冻结哈希、评分口径与不可覆盖结果索引 |
| `experiments/langgraph_poc/` | 不被生产入口导入、可整体删除的 StateGraph/Fake Tool/Checkpoint/Interrupt/Checker 可行性实验 |
| `experiments/langgraph_poc/graph.py` | PoC StateGraph、条件边、并行 fan-out/fan-in、预算、Interrupt 与强制 Checker 拓扑 |
| `experiments/langgraph_poc/contracts.py` | JSON-safe AgentState、ToolResult、Reducer、事件和确定性合并契约 |
| `experiments/langgraph_poc/fake_provider.py` / `fake_tools.py` | 零网络、零模型费用的脚本化路由、错误、重试和降级夹具 |
| `experiments/langgraph_poc/checkpoint.py` / `checkpoint_worker.py` | 仅写 pytest 临时目录的跨进程 Checkpoint 恢复实验；不是生产 saver |
| `experiments/langgraph_poc/tests/` | 20 类验收矩阵、10 条 V1 金标、16 条 regression 与量化对比测试 |
| `experiments/langgraph_poc/results/poc_summary.json` | Fixture 哈希、精确分母、并行基准、首次失败和零 API 成本的机器可读摘要 |
| `LICENSE` | 本项目自行开发代码的 MIT License |
| `THIRD_PARTY_NOTICES.md` | 第三方来源、固定版本、许可和供应商目录差异 |
| `vendor/youtu-rag/` | 以 Git subtree 固定纳入的完整 Youtu-RAG 上游源码 |
| `vendor/youtu-rag/configs/` | 上游 Agent/RAG 配置；阶段 1 关闭非必要能力并设置 API Embedding 配置骨架 |
| `vendor/youtu-rag/frontend/` | 上游 WebUI 静态资源；含阶段 4 SmartBuy 模式开关及阶段 5 Checker SSE 卡片 |
| `vendor/youtu-rag/utu/` | 上游 Python 包、Agent/RAG 服务与 FastAPI；含阶段 1 配置脱敏、阶段 2 Provider/Windows 兼容补丁、阶段 4 路由和阶段 5 Monitor 展示 |
| `vendor/youtu-rag/tests/` | 上游测试及本项目新增的配置脱敏回归测试 |
| `vendor/youtu-rag/pyproject.toml` / `uv.lock` | 上游 Python 依赖定义与固定锁文件 |
| `smartbuy/__init__.py` | 自研 SmartBuy Python 包入口 |
| `smartbuy/agent/react.py` | qwen-plus 有界 Tool Calling、结构化状态、依赖门禁、预算与停止循环 |
| `smartbuy/agent/ranking.py` | 仅对 Checker 合规候选执行软偏好排序，并由代码阻止增删资格 |
| `smartbuy/agent/reporting.py` | 从工具观察确定性组装并渲染 Schema 校验报告 |
| `smartbuy/cache/` | 仅缓存公开稳定中间结果的校验和、TTL、容量、版本失效和损坏绕过实现 |
| `smartbuy/constraints/models.py` | 带来源约束、字段四态、候选复核和批次结果的 Pydantic 契约 |
| `smartbuy/constraints/normalize.py` | 首批字段的别名、单位、否定、比较符、来源优先级和取消规则 |
| `smartbuy/constraints/verifier.py` | 完整候选池的只读 SQLite/evidence 确定性复核与 fail-closed |
| `smartbuy/constraints/scoring.py` | 自然/故障注入固定套件的精确分母、延迟和重复性 Scorer |
| `smartbuy/constraint_proposals/` | V2-5 Proposal Schema、确定性优先解析、qwen-plus Function Calling 候选门、仓库外澄清状态与双编排器适配；`spans.py` 负责服务端精确 Quote-to-Span |
| `smartbuy/contracts/` | V2 不可变通用 Product/Field/Constraint/Evidence/Candidate/Tool/Data/Pack 契约与 Product Pack 只读接口 |
| `smartbuy/api/router.py` | `/api/smartbuy` HTTP/SSE、Monitor JSON 和长期偏好管理接口 |
| `smartbuy/domain/models.py` | 需求、四态证据、轨迹、Checker 结果、候选和最终报告 Pydantic 契约 |
| `smartbuy/identity/` | Product Pack 驱动的精确商品身份、不可变 Candidate Scope、版本/工具边界和证据闭包安全门 |
| `smartbuy/agent/domain_agent.py` | 通用 Trusted Domain Agent；解析 Scope 并把同一范围传递给查询、KB、Evidence、Checker 和报告 |
| `smartbuy/decision_core/` | 品类无关的查询意图、引用、Candidate Scope、Canonical Value、Constraint Delta、结果分类与候选链安全断言 |
| `smartbuy/domain_packs/loader.py` / `settings.py` | 固定 JSON 文件集、版本/字段/策略校验及默认关闭的 Domain Pack 配置 |
| `smartbuy/domain_packs/registry.py` / `evaluator.py` | 多 Pack fail-closed 注册与完全由 Pack 字段/操作符驱动的确定性比较；不含品类字段常量 |
| `smartbuy/domain_packs/scope.py` | 把 domain 纳入 Memory/Checkpoint key，并拒绝跨品类 envelope 恢复 |
| `smartbuy/domain_packs/laptop/` | 49 个 Laptop 字段、单位/别名/值域、来源权限、Checker、Ranking、Memory、报告和冻结评测配置 |
| `smartbuy/domain_packs/headphone/` | 38 个 Headphone 字段、三层来源权限、30 个 Checker 字段、四个 Ranking Profile、Memory 与 Open Research 声明规则 |
| `smartbuy/domain_packs/monitor/` | 映射 V1 显示器字段、单位、别名、来源、Checker、Ranking、Memory、报告和冻结哈希的首套 Pack |
| `smartbuy/domain_packs/v1_adapter.py` / `orchestrator.py` | V1 请求/商品/Checker/报告的通用映射、资格一致性门和 opt-in 包装层 |
| `smartbuy/memory/store.py` | 进程内会话状态及仓库外、显式确认的长期偏好生命周期 |
| `smartbuy/orchestration/contracts.py` / `react_adapter.py` | ReAct/LangGraph 共用的版本化输入输出事件契约及不改行为的 V1 适配器 |
| `smartbuy/orchestration/langgraph_adapter.py` / `safety.py` | 显式启用的状态图外壳、Interrupt/恢复和不可绕过的 Checker 终态结构门 |
| `smartbuy/orchestration/checkpoints.py` / `selector.py` | 严格反序列化、内存/仓库外 SQLite Saver、身份隔离、特性选择及显式回退 |
| `smartbuy/tools/` | KB、只读 Text2SQL、Evidence Check、Web unavailable、显式 Source Search 和统一结果契约 |
| `smartbuy/tools/domain.py` | 通用 EAV 只读 Product Query、领域索引 KB Search、四态 Evidence Check 与完整池 Checker |
| `smartbuy/eval/v2_6c_r1_identity_scope_replay.py` | 只复用已暴露 Constraint Resolution 的零 API 20 条离线回归，不运行剩余 10 条 |
| `smartbuy/eval/results/v2_6c_r1_exposed_regression.json` | R1 独立机器结果；不覆盖 V2-6C 首次失败和历次修复记录 |
| `smartbuy/eval/v2_6c_r2_laptop_holdout.jsonl` / `.schema.json` | 代码冻结后创建的 20 条 `frozen_unrun` 第二验证集及严格单条任务 Schema |
| `smartbuy/eval/v2_6c_r2_laptop_scoring_policy.json` / `v2_6c_r2_laptop_scorer.py` | 首次 E2E 前固定的指标、门槛与评分器；本轮只执行确定性金标校验入口 |
| `smartbuy/eval/v2_6c_r2_laptop_runner.py` | 隔离评测 Runner：冻结 RC、固定顺序执行、逐条 fsync Journal、预算限制和不可覆盖结果汇总 |
| `smartbuy/eval/results/v2_6c_r2_*` | 第二验证集的 RC、20条追加 Journal 与唯一首次结果；不包含密钥、Prompt 或隐藏推理 |
| `smartbuy/eval/v2_6c_r3_exposed_runner.py` | 汇总历史和已暴露验证失败的离线回归，不把暴露样本当作新 Holdout |
| `smartbuy/eval/results/v2_6c_r4_exposed_regression_iteration*.json` | R4 每次独立保存的 122 条已暴露工程回归；不覆盖 R3 三轮冻结首测 |
| `smartbuy/eval/results/v2_6c_r4_failure_diagnostic.json` / `v2_6c_r4_engineering_validation.json` | 第三轮三条首错节点的前后状态，以及 R4 暴露回归、Open Research、Memory、故障和双编排器脱敏摘要 |
| `smartbuy/eval/v2_6c_r3_validation_*` | 三轮独立验证集生成、Schema、冻结策略、单次 Runner、Scorer、RC、Journal 与不可覆盖首次结果 |
| `smartbuy/config/bailian.py` | 从继承进程安全加载百炼配置、派生三类端点和 Youtu 子进程映射 |
| `smartbuy/providers/bailian.py` | 普通/流式/工具 Chat、1024 维 Embedding、Rerank、有限重试与降级实现 |
| `smartbuy/providers/zhipu_search.py` | `search_pro` 与搜狗有界回退、重试/费用/延迟门、TTL 缓存和脱敏调用账本 |
| `smartbuy/source_search/` | 可插拔 Provider 契约、候选状态、默认关闭配置、缓存和 URL/域名/型号/地区确定性验证 |
| `smartbuy/tools/source_search.py` | Agent 显式来源发现工具、本地证据充分性门，以及 Source Candidate 与 Evidence/Checker 隔离 |
| `smartbuy/open_research/` | URL/SSRF 安全、静态 HTML/PDF/内嵌状态抽取、Domain Pack 字段规范化、Open 四态核验、请求级仓库外临时存储和研究报告服务 |
| `smartbuy/tools/web_extractor.py` | 仅在显式 Open Mode 中接受本轮 Source Candidate 的 Agent 工具门，拒绝任意 URL 和 Trusted 晋升 |
| `smartbuy/product_packs/models.py` / `schema/` | Product Pack、来源、字段证据、观察和临时证据的严格版本化 JSON/Pydantic 契约 |
| `smartbuy/product_packs/loader.py` / `ledger.py` | 型号/品牌/别名/地区/配置版/单位/许可归一化门和统一字段级 Evidence Ledger |
| `smartbuy/product_packs/builder.py` / `cli.py` / `runtime.py` | 仓库外 staging/validate/publish/rollback、幂等数据快照、默认关闭的运行选择与数据/索引 CLI |
| `smartbuy/product_packs/domain_builder.py` / `domain_cli.py` | 配置驱动的 standalone Pack EAV SQLite、Evidence/事实卡/待索引文档派生、原子版本和通用 CLI |
| `smartbuy/product_packs/live_index.py` | 独立 1024 维 Chroma 构建、完整 Manifest 校验、原子 Index 指针、失败保持与回滚 |
| `smartbuy/product_packs/examples/laptop-v1/pack.json` | 12 个精确配置、12 个官方 Source 和 406 条字段 Evidence 的版本化 Laptop Product Pack |
| `smartbuy/product_packs/examples/monitor-u2725qe-us/pack.json` | 仅含官方元数据、自制短摘要和结构化证据的第 13 个显示器示例 Pack |
| `smartbuy/observability/usage.py` | 不记录正文或凭据的内存 Token、延迟和成本账本 |
| `smartbuy/observability/agent_events.py` | 有界、脱敏的 Agent 运行摘要和 Monitor 聚合 |
| `smartbuy/observability/eval_ledger.py` | 阶段 6 统一运行/步骤账本 Schema、脱敏校验与 JSONL 输出 |
| `smartbuy/reproducibility/semantic_manifest.py` / `v2_9e_manifest.py` / `v2_9h_rc3_manifest.py` | 明确成员集、稳定聚合哈希、三品类版本合同、RC3 发布边界和独立运行审计 envelope |
| `smartbuy/data/catalog/monitors_v1.json` | 12 个型号、来源、追加式价格和冲突证据的唯一 canonical 源数据 |
| `smartbuy/data/laptop/laptop_configurations_v1.json` | Laptop Product Pack 的紧凑治理源：型号、地区、精确配置、官方来源与可核验字段；未知保留 null |
| `smartbuy/data/headphone/headphone_configurations_v1.json` | Headphone Product Pack 的紧凑治理源：12 个精确配置、官方/专业实测/主观来源及字段级证据引用 |
| `smartbuy/data/loader.py` / `derive.py` / `quality.py` | 加载、派生证据/事实卡和执行确定性数据质量门 |
| `smartbuy/data/demo/` | Clone 后可用的 12 份自制事实卡及文件哈希清单 |
| `smartbuy/data/processed/` | 可由 canonical 数据或真实评测重建的 JSONL、索引清单和脱敏指标结果 |
| `smartbuy/data/raw/README.md` | 本地受限原文目录规则；除说明外的内容均被 Git 忽略 |
| `smartbuy/db/schema_v1.sql` / `build_database.py` | 四实体 SQLite Schema、工作区外原子重建、完整性摘要和可选 CSV 导出 |
| `smartbuy/retrieval/knowledge_base.py` | H2 事实卡切分、必需 chunk 元数据和 Youtu/Chroma 正式建库契约 |
| `smartbuy/retrieval/domain_index.py` | 通用 Product Pack 的仓库外 1024 维 Chroma 构建、Manifest 校验与原子领域索引指针 |
| `smartbuy/eval/cases.jsonl` | 40 条固定检索、冲突、拒答和降级金标任务 |
| `smartbuy/eval/run_retrieval_eval.py` | Vector-only/Reranker 检索、Recall/nDCG/拒答/延迟/成本评测 |
| `smartbuy/eval/stage4_cases.jsonl` / `run_stage4_eval.py` | 16 条 Agent 金标、4 条 dry run、真实 E2E 指标与成本 Runner |
| `smartbuy/eval/stage5_*.jsonl` / `run_stage5_eval.py` | 10 条自然硬约束、12 条独立故障注入、固定池 A/B 和有界在线回归 Runner |
| `smartbuy/eval/stage6_*.jsonl` / `stage6_config.json` | 40 条自然任务、13 条故障、5 条 Memory 任务及首次运行前冻结的公平配置 |
| `smartbuy/eval/run_stage6_eval.py` / `stage6_scoring.py` | 四组公平 Runner、断点恢复、重复运行及精确分子/分母确定性评分 |
| `smartbuy/eval/run_stage6_resilience.py` | 受控 Provider、存储、预算和 Checker 故障注入与 Memory 专项评测 |
| `smartbuy/eval/run_stage6_cache_benchmark.py` | 公开稳定查询的冷/热缓存正确性、延迟和命中率基准 |
| `smartbuy/eval/run_stage6_checker_determinism.py` | 同输入三次执行的 Checker 字节级一致性验证 |
| `smartbuy/eval/merge_stage6_checkpoints.py` / `build_stage6_artifacts.py` | 分片审计合并、首见结果保留、指标 CSV 和统一账本生成 |
| `smartbuy/eval/v2_stage5_expression_*` / `run_v2_constraint_eval.py` | 先冻结的 30 Regression + 20 Holdout 新表达、哈希和零网络精确评分器 |
| `smartbuy/eval/v2_6a_laptop_cases.jsonl` | 首次正式 Laptop E2E 前冻结的 30 条结构化、相似配置、地区/配置、负例和自然约束金标 |
| `smartbuy/eval/v2_6b_laptop_retrieval_cases.jsonl` / `v2_6b_laptop_retrieval_runner.py` | 在线调参前冻结的 30 条 Laptop 工具检索集，以及 Vector/Reranker 首次评测 Runner |
| `smartbuy/eval/results/v2_6b_laptop_retrieval_first.json` | 不可覆盖的首次真实 1024 维检索、Reranker、延迟和费用脱敏结果 |
| `smartbuy/eval/v2_8_headphone_retrieval_cases.jsonl` / `v2_8_headphone_retrieval_runner.py` | 30 条冻结 Headphone 检索集及真实 Vector/Reranker 指标 Runner |
| `smartbuy/eval/v2_8_headphone_engineering_cases.jsonl` / `v2_8_headphone_engineering_runner.py` | 30 条 Headphone 工程任务、固定评分与不可覆盖首次/暴露回归执行入口 |
| `smartbuy/eval/results/v2_8_headphone_*` | Headphone 检索、工程首次失败、修复后暴露回归及 Open Research 脱敏结果 |
| `smartbuy/scripts/build_laptop_product_pack.py` | 将紧凑治理源确定性展开为完整 Laptop Product Pack，不抓取网页或调用模型 |
| `smartbuy/tests/integration/test_v2_laptop_domain_pack.py` | Pack 隔离、字段/单位、来源权限、Evidence、幂等构建、SQLite、回滚、自然表达和冻结哈希验收 |
| `smartbuy/tests/integration/test_v2_laptop_toolchain.py` | Product Query、真实索引合同、KB/Reranker 降级、Evidence/Checker、10 条组合与跨品类隔离测试 |
| `smartbuy/eval/v2_stage5b_live_holdout*` / `run_v2_live_constraint_holdout.py` | 一次性 12 条 qwen-plus 回退集、冻结哈希、严格 Tool/span/Pack 评分和仓库外首测产物 |
| `smartbuy/eval/v2_stage5c_live_holdout_v2*` / `run_v2_quote_span_live_eval.py` | 新 20 条 Quote 合同 Live Holdout、冻结哈希、真实 Function/Schema/span/安全评分与仓库外不可覆盖输出 |
| `smartbuy/docs/adr/0001-vendor-youtu-rag.md` | 上游纳入方式、固定 Commit、修改边界和更新流程决策 |
| `smartbuy/docs/adr/0002-bailian-provider-and-index-contract.md` | 百炼 Provider、1024 维索引、重试和降级契约 |
| `smartbuy/docs/adr/0003-governed-monitor-data-and-index.md` | 数据许可边界、四实体 Schema、事实卡和索引版本决策 |
| `smartbuy/docs/adr/0004-bounded-react-evidence-and-memory.md` | ReAct、SQL/Evidence、公开轨迹、停止和 Memory 决策 |
| `smartbuy/docs/adr/0005-deterministic-constraint-gate.md` | 来源优先级、完整候选池、只读 Checker 和 LLM 权限决策 |
| `smartbuy/docs/adr/0006-reproducible-evaluation-cache-and-resilience.md` | 四组公平性、冻结集、缓存边界、统一账本及故障注入决策 |
| `smartbuy/docs/adr/0007-langgraph-orchestration-decision.md` | V2 编排建议采用 LangGraph、证据、风险、兼容门和回滚条件 |
| `smartbuy/docs/adr/0008-langgraph-compatibility-and-checkpointing.md` | V2-1C 默认 ReAct、显式 LangGraph、本地 Checkpoint 与默认值迁移门决策 |
| `smartbuy/docs/adr/0009-domain-contracts-and-monitor-pack.md` | V2-1D 适配优先、数据所有权、严格 Loader、默认关闭和无迁移回滚决策 |
| `smartbuy/docs/adr/0010-versioned-product-pack-and-evidence-ledger.md` | V2-2 严格 Schema、字段 Ledger、事务发布、索引版本和临时证据边界决策 |
| `smartbuy/docs/adr/0011-auditable-zhipu-source-search.md` | V2-3 智谱单 Provider、精确地区状态、搜狗回退、候选隔离和不采用三家聚合的决策 |
| `smartbuy/docs/adr/0012-governed-web-extraction-and-open-evidence.md` | V2-4 URL 安全、静态抽取、临时 Open Evidence、模式隔离和不自动晋升的决策 |
| `smartbuy/docs/adr/0013-regional-evidence-comparability.md` | V2-4C 单边地区缺失、跨地区异值/同值与目标地区事实不覆盖的决策 |
| `smartbuy/docs/adr/0014-validated-constraint-proposals-and-clarification.md` | V2-5 LLM 只提案、严格 span/Pack 校验、双编排器暂停恢复和默认关闭决策 |
| `smartbuy/docs/adr/0015-server-verified-quote-to-span.md` | V2-5C 由服务端精确定位 quote、重复 occurrence 和禁止模糊补救的 grounding 决策 |
| `smartbuy/docs/data_card.md` | 数据范围、来源、缺失、哈希语义、人工抽查和合规说明 |
| `smartbuy/docs/runtime_manifest.md` | 目标主机、依赖、模型状态、索引契约、运行路径和服务结果 |
| `smartbuy/docs/stage1_smoke_test.md` | 阶段 1 命令、耗时、通过/延后项、安全事件与退出结论 |
| `smartbuy/docs/stage2_bailian_verification.md` | 三模型、建库、KB Search、错误矩阵、安全处置和成本证据 |
| `smartbuy/docs/stage3_data_and_retrieval_report.md` | 数据质量、SQLite、正式索引、40 条检索指标、成本和失败案例 |
| `smartbuy/docs/stage4_agent_workflow_report.md` | Agent 工具链、E2E、Memory、成本、失败修复和真实服务冒烟 |
| `smartbuy/docs/stage5_constraint_verification_report.md` | 固定池消融、故障注入、在线 E2E、Checker 延迟、成本和边界 |
| `smartbuy/docs/stage6_evaluation_and_resilience_report.md` | 四组主实验、重复稳定性、缓存、故障降级、成本和首次失败的完整证据 |
| `smartbuy/docs/demo_guide.md` | 四个五分钟固定 Demo 的输入、轨迹、结果、备用步骤和截图入口 |
| `smartbuy/docs/release_report.md` | 发布候选、定向修复、Windows 复现、成本与最终发布边界 |
| `smartbuy/docs/portfolio_metrics.md` | 简历数字的分子/分母、数据、Commit 和允许/禁止表述 |
| `smartbuy/docs/release_checklist.md` | 评测、运行、数据许可、安全、工程质量和推送清单 |
| `smartbuy/docs/release/v1.0.0-portfolio-release-notes.md` | 已发布的 `v1.0.0-portfolio` GitHub Release 基础文案与 V1 能力边界 |
| `smartbuy/docs/assets/` | 实际 WebUI、明确标注非实时的脱敏回放与 README 专用架构图 |
| `smartbuy/api/portfolio_runtime.py` | 仅在显式开关开启且仓库外 Data/Index 指针通过校验时装配 Laptop/Headphone 通用 Agent |
| `smartbuy/portfolio/` | 五 Demo 公开 Schema、固定脱敏回放加载与动态观察的 fail-closed 合同 |
| `smartbuy/scripts/start_youtu_rag.ps1` | 从继承进程安全映射百炼变量并在回环地址启动 Youtu-RAG |
| `smartbuy/scripts/verify_bailian_stage2.py` | 有界真实 API 验证；只输出脱敏统计，不输出模型正文或 Key |
| `smartbuy/scripts/verify_v2_source_search.py` | 8 条固定官方来源任务的有界真实搜索，只输出 URL 元数据、状态、计数、延迟和费用 |
| `smartbuy/scripts/verify_v2_open_research.py` | 仓库外运行的数据库外商品/降级/canonical-hreflang 有界真实验收，只保存脱敏状态与哈希 |
| `smartbuy/scripts/verify_v2_6c_laptop_open_research.py` | 动态发现数据库外 Laptop 官方页并在仓库外验证 Open Evidence；不硬编码目标 URL，不进入 Trusted Checker |
| `smartbuy/scripts/verify_v2_product_pack_live.py` | 第 13 个型号真实 KB、四工具闭环、Reranker 降级、未完成索引与回滚的有界在线验收 |
| `smartbuy/scripts/build_stage3_data.py` / `validate_stage3_data.py` | 生成并核验 processed 数据、事实卡和哈希清单 |
| `smartbuy/scripts/build_stage3_index.py` / `verify_stage3_index.py` | 有界真实建库和不调用模型的 Chroma 契约复核 |
| `smartbuy/scripts/check_markdown_links.py` | 在本地与 CI 中检查根文档和 `smartbuy/docs/` 的相对链接目标 |
| `smartbuy/scripts/preflight.ps1` / `bootstrap.ps1` | Windows 依赖与脱敏配置预检、冻结依赖、数据/SQLite/Chroma 幂等构建 |
| `smartbuy/scripts/start.ps1` / `stop.ps1` | 仓库外运行目录中的 MinIO/FastAPI 启停、HTTP 检查和精确进程树清理 |
| `smartbuy/scripts/build_v2_release_runtime.py` | 仓库外幂等发布 Laptop/Headphone Product Pack，并在显式请求时构建独立 1024 维索引 |
| `smartbuy/scripts/replay.ps1` / `verify_v2_9a_demos.py` | 无 Key/MinIO 脱敏回放启停，以及零 API 的五 Demo 数据/代码合同复核 |
| `smartbuy/scripts/verify_stage7_demos.py` | 调用本地 API 验证四个固定 Demo 并保存脱敏摘要 |
| `smartbuy/tests/fixtures/stage1_baseline.md` | 自制、无隐私的 Markdown 上传与知识库配置冒烟夹具 |
| `smartbuy/tests/unit/` | 百炼统一配置、请求契约、重试、维度与降级单元测试 |
| `smartbuy/tests/integration/` | Youtu Embedding/Reranker 和 Toolkit 日志安全适配回归 |
| `smartbuy/tests/unit/test_v2_product_pack.py` / `integration/test_v2_product_pack_pipeline.py` | Product Pack Schema、非法输入、临时 Ledger、幂等构建、工具链、发布失败和回滚测试 |
| `smartbuy/tests/integration/test_v2_live_product_index.py` | 真实本地 Chroma 的数量/维度/Manifest 门、原子指针、回滚和 fail-closed 测试；Provider 为 Fake，不调用云端 |
| `smartbuy/tests/unit/test_stage3_*` | 数据质量、评测集、SQLite 幂等和 chunk 元数据契约测试 |
| `smartbuy/tests/unit/test_stage4_*` | SQL 安全/金标、Evidence 四态、Memory、Agent 上限和降级测试 |
| `smartbuy/tests/unit/test_stage5_*` | 约束来源、别名/边界、完整池、fail-closed、s4-014、安全门和顺序回归 |
| `smartbuy/tests/unit/test_stage6_*` | 冻结集、评分分母、账本脱敏、缓存正确性/损坏恢复和故障契约回归 |
| `smartbuy/tests/unit/test_stage7_reporting.py` | 报告冲突 fail-closed、unknown、证据/字段收敛回归 |
| `smartbuy/tests/integration/test_stage4_api.py` | SmartBuy HTTP/SSE、偏好生命周期和 WebUI 接线回归 |
| `smartbuy/tests/unit/test_v2_source_search.py` / `integration/test_v2_source_search_agent.py` | 候选分类、白名单/地区/型号安全、重试/缓存/费用、Agent 事件和 Evidence/Checker 隔离 |
| `smartbuy/tests/unit/test_v2_open_research.py` / `integration/test_v2_open_research_agent.py` | SSRF/HTML/重定向/临时证据/四类双边冲突、地区不匹配/canonical 恢复和 Open Agent/Checker/Monitor 隔离回归 |
| `smartbuy/tests/unit/test_v2_constraint_proposals.py` / `integration/test_v2_clarification_orchestration.py` | 50 条表达精确指标、span/Pack 安全、Memory 优先级及 ReAct/LangGraph 五类暂停恢复回归 |
| `smartbuy/tests/unit/test_v2_live_constraint_provider_contract.py` | Live Holdout 冻结、规则隔离、缺失/错误 Function、非领域字段和未确认歧义的 fail-closed 回归 |
| `smartbuy/tests/unit/test_v2_quote_span_contract.py` | 唯一/重复/缺失 quote、Unicode/Emoji、unsupported、Prompt Injection、服务端优先级和双编排器一致性测试 |

## 计划结构

V2 已创建 Monitor、Laptop、Headphone 三套 Domain Pack，以及兼容适配层、Product Pack/Ledger、Source Search、Open Research、服务端 Quote-to-Span、确定性 Ranker、分层 Memory 和统一产品 UI。默认仍使用 ReAct；LangGraph 只是显式启用的兼容外壳。V2-9H 已冻结 `proofpick-v2-rc3`：Trusted Multi-domain Decision Core 为默认 Stable 能力，Online Research 为 Experimental/Beta。V2-9D 第二次独立评测仍为 `Needs revision`；V2-9F 已暴露 Online 回归为 6/15，V2-9G 未接入生产的有限 PoC 只投影 7/15。RC3 下一次发布判断必须由独立评测方执行；正式浏览器、Composite Provider、自动 Evidence Promotion、GraphRAG、Neo4j 和第四品类均不在当前已实现范围。

## 维护检查清单

- [x] 树状结构来自当前工作区，不从计划或旧文档复制。
- [x] 计划项单独列出且明确标记“计划/不存在”。
- [x] 缓存、模型文件、运行数据和大批样本没有逐项罗列。
- [x] 供应商目录修改已同步第三方声明与 ADR。
- [x] 文件职责与 [README.md](../../../README.md) 和 [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) 一致。
- [x] 两份原始资料已按 archive/setup 归档，保留原文件名且内容未被改写。

## 文档导航

- [项目首页](../../../README.md)
- [开发指南](DEVELOPMENT_GUIDE.md)
- [Runtime Manifest](../runtime_manifest.md)
- [阶段 1 冒烟记录](../stage1_smoke_test.md)
- [阶段 2 验证记录](../stage2_bailian_verification.md)
- [阶段 3 数据卡](../data_card.md)
- [阶段 3 数据与检索报告](../stage3_data_and_retrieval_report.md)
- [阶段 4 技术报告](../stage4_agent_workflow_report.md)
- [ADR-0004](../adr/0004-bounded-react-evidence-and-memory.md)
- [阶段 5 技术报告](../stage5_constraint_verification_report.md)
- [ADR-0005](../adr/0005-deterministic-constraint-gate.md)
- [阶段 6 技术报告](../stage6_evaluation_and_resilience_report.md)
- [ADR-0006](../adr/0006-reproducible-evaluation-cache-and-resilience.md)
- [阶段 7 发布报告](../release_report.md)
- [Demo 指南](../demo_guide.md)
- [作品集指标](../portfolio_metrics.md)
- [V2 文档入口](../v2/README.md)
- [V2-1A 实现级设计](../v2/v2_1_implementation_design.md)
- [LangGraph PoC 计划](../v2/v2_1_langgraph_poc_plan.md)
- [LangGraph PoC 报告](../v2/v2_1_langgraph_poc_report.md)
- [ADR-0007](../adr/0007-langgraph-orchestration-decision.md)
- [V2-1C 兼容适配报告](../v2/v2_1c_compatibility_report.md)
- [V2-1C 运行说明](../v2/v2_1c_runtime.md)
- [ADR-0008](../adr/0008-langgraph-compatibility-and-checkpointing.md)
- [V2-1D Domain Pack 报告](../v2/v2_1d_domain_pack_report.md)
- [V2-1D 运行说明](../v2/v2_1d_runtime.md)
- [ADR-0009](../adr/0009-domain-contracts-and-monitor-pack.md)
- [V2-2 Product Pack 报告](../v2/v2_2_product_pack_report.md)
- [V2-2 运行说明](../v2/v2_2_runtime.md)
- [ADR-0010](../adr/0010-versioned-product-pack-and-evidence-ledger.md)
- [V2-3 Source Search 报告](../v2/v2_3_source_search_report.md)
- [V2-3 运行说明](../v2/v2_3_runtime.md)
- [ADR-0011](../adr/0011-auditable-zhipu-source-search.md)
- [V2-4 Open Research 报告](../v2/v2_4_open_research_report.md)
- [V2-4 运行说明](../v2/v2_4_runtime.md)
- [ADR-0012](../adr/0012-governed-web-extraction-and-open-evidence.md)
- [FINAL 开发交接文档](../archive/FINAL_多源消费决策研究Agent开发交接总文档.md)
- [阿里云百炼 API 调用说明](../setup/阿里云百炼API-Key调用与Youtu-RAG接入说明.md)
