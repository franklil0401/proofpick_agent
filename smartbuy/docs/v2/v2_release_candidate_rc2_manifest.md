# ProofPick V2-9C RC2 Release Candidate Manifest

## 冻结声明

本文件冻结 `proofpick-v2-9c-rc2`。生产代码固定在 `2d41773981c69b815efa21c0bf21675d095b920d`，Git Tree 固定为 `9273e9f41a3ad62ac6712a02a6ee6a4486a90f24`。本文件自身属于其后的冻结文档提交，不改变生产 Tree。

RC2 不是 Git Tag、GitHub Release、生产 SLA 或新的独立评测结论。本轮没有创建或运行新 Holdout；V2-9B 的 90 条 Trusted 与 15 条 Online 只能作为已暴露测试引用。

聚合哈希算法：按成员相对路径排序，对每个成员追加 `path UTF-8 + NUL + file SHA-256 hex + LF`，再对完整字节序列计算 SHA-256。仓库成员均从指定 `production_commit` 的 Git Blob 读取，不使用可变工作区。外部索引清单使用相同算法，但成员名是下文的逻辑路径，成员摘要是运行清单文件 SHA-256。

Manifest Payload SHA-256 的计算对象是下方 `RC2-PAYLOAD-BEGIN/END` 标记之间的 UTF-8 文本，去除首尾空白后补一个 LF；不包含标记、标题或 SHA 行。

**Manifest Payload SHA-256：** `026e1ccff278c8285231223e3f2510f658e0ce2e68921c6ea94bf0a84eec1e2b`

<!-- RC2-PAYLOAD-BEGIN -->
```yaml
manifest_schema: proofpick-release-candidate-v2
release_candidate: proofpick-v2-9c-rc2
generated_at_utc: 2026-09-04T11:14:42.453Z
branch: feature/proofpick-v2
production_commit: 2d41773981c69b815efa21c0bf21675d095b920d
production_tree: 9273e9f41a3ad62ac6712a02a6ee6a4486a90f24
v1_stable_commit: d51b6668a6a45c1b01ef4e64da3c4b9ac84ed10c
v1_tag: v1.0.0-portfolio

runtime:
  os: Windows 11
  python: 3.12.3
  uv: 0.12.3
  git: 2.54.0.windows.1
  node: 24.15.0
  default_orchestrator: react
  agent_limits:
    max_steps: 8
    max_tool_calls: 12
  models:
    llm: qwen-plus
    embedding: text-embedding-v4
    embedding_dimensions: 1024
    reranker: qwen3-rerank
  feature_flags:
    langgraph: explicit_enable_non_default
    natural_constraints: explicit_enable
    source_search: explicit_enable
    open_research: explicit_enable
    portfolio_online_domain_agent: explicit_enable
  secrets:
    persisted_in_manifest: false
    values_read_or_printed_for_freeze: false

freeze_groups:
  dependency_lock:
    aggregate_sha256: 1465bcbbd5826be130ae5305946b4e507c03a36cab605ceb36f6c8500ed1a9b7
    uv_lock_file_sha256: 8e2e889757a4369d0dfef9d5a262f50b6934ef0eede063434a726bb7b8ab94d8
    file_count: 1
    members:
      - vendor/youtu-rag/uv.lock

  prompts:
    aggregate_sha256: 04b060e43e26a7a326d10bded4d17e448627c0ec05fca77be030415b416ff01c
    file_count: 3
    members:
      - smartbuy/agent/ranking.py
      - smartbuy/agent/react.py
      - smartbuy/constraint_proposals/provider.py

  query_intent_product_reference_candidate_scope:
    aggregate_sha256: adf37280836ac1f050eabcc4f6812f0a363ded26dbb7fb958aa7b6e49ce0c586
    file_count: 11
    members:
      - smartbuy/decision_core/__init__.py
      - smartbuy/decision_core/canonical.py
      - smartbuy/decision_core/delta.py
      - smartbuy/decision_core/intent.py
      - smartbuy/decision_core/result.py
      - smartbuy/decision_core/safety.py
      - smartbuy/decision_core/scope.py
      - smartbuy/identity/__init__.py
      - smartbuy/identity/guards.py
      - smartbuy/identity/models.py
      - smartbuy/identity/resolver.py

  constraint_resolution_clarification:
    aggregate_sha256: c032cab0074577d0739a5ee2a2661cc80f25b684e6793dd432946c8786c3b556
    file_count: 7
    members:
      - smartbuy/constraint_proposals/__init__.py
      - smartbuy/constraint_proposals/coordinator.py
      - smartbuy/constraint_proposals/engine.py
      - smartbuy/constraint_proposals/models.py
      - smartbuy/constraint_proposals/provider.py
      - smartbuy/constraint_proposals/settings.py
      - smartbuy/constraint_proposals/spans.py

  tool_schema_and_contracts:
    aggregate_sha256: 34d045955883441975dd71b9c5d87c7cd582c4780855e6ae0945feedc4437c2f
    file_count: 14
    members:
      - smartbuy/contracts/__init__.py
      - smartbuy/contracts/models.py
      - smartbuy/contracts/product_pack.py
      - smartbuy/domain/__init__.py
      - smartbuy/domain/models.py
      - smartbuy/tools/__init__.py
      - smartbuy/tools/base.py
      - smartbuy/tools/domain.py
      - smartbuy/tools/evidence_check.py
      - smartbuy/tools/kb_search.py
      - smartbuy/tools/source_search.py
      - smartbuy/tools/text2sql.py
      - smartbuy/tools/web_extractor.py
      - smartbuy/tools/web_search.py

  evidence_check:
    aggregate_sha256: 04dd0376bc21a13a5f5f4dd769a1e4c0bc63735acfd94d3094dfafda63047303
    file_count: 5
    members:
      - smartbuy/contracts/models.py
      - smartbuy/open_research/evidence_check.py
      - smartbuy/product_packs/ledger.py
      - smartbuy/tools/domain.py
      - smartbuy/tools/evidence_check.py

  constraint_checker:
    aggregate_sha256: c685dfd9859a97f8994694dbb523f9cfb81147c77302093cff964df7014b50a1
    file_count: 7
    members:
      - smartbuy/constraints/__init__.py
      - smartbuy/constraints/models.py
      - smartbuy/constraints/normalize.py
      - smartbuy/constraints/scoring.py
      - smartbuy/constraints/verifier.py
      - smartbuy/contracts/models.py
      - smartbuy/tools/domain.py

  ranker:
    aggregate_sha256: 2387df67a0100a38b493d90b9c12a61e02915c4c1945e91af12e6edbbbe7dbfd
    file_count: 5
    members:
      - smartbuy/agent/ranking.py
      - smartbuy/ranking/__init__.py
      - smartbuy/ranking/models.py
      - smartbuy/ranking/profile.py
      - smartbuy/ranking/ranker.py

  memory:
    aggregate_sha256: 75158e621f9ce585e5350c5b666e5b1487dcc51d0d7fd89c11b713e35cf9b701
    file_count: 3
    members:
      - smartbuy/memory/__init__.py
      - smartbuy/memory/domain_store.py
      - smartbuy/memory/store.py

  domain_pack_config:
    aggregate_sha256: af9540f50e39e85dedb265b80a2a9eee6620db3558fbd2c416d3a88861ff1581
    file_count: 10
    members:
      - smartbuy/domain_packs/category_registry.json
      - smartbuy/domain_packs/headphone/fields.json
      - smartbuy/domain_packs/headphone/manifest.json
      - smartbuy/domain_packs/headphone/policies.json
      - smartbuy/domain_packs/laptop/fields.json
      - smartbuy/domain_packs/laptop/manifest.json
      - smartbuy/domain_packs/laptop/policies.json
      - smartbuy/domain_packs/monitor/fields.json
      - smartbuy/domain_packs/monitor/manifest.json
      - smartbuy/domain_packs/monitor/policies.json

  open_research_source_search:
    aggregate_sha256: ee70bf8ddf8dcda7220c42f253e8f372aea1725f2621a4dabfaa381673e29273
    file_count: 19
    members:
      - smartbuy/api/portfolio_runtime.py
      - smartbuy/open_research/__init__.py
      - smartbuy/open_research/evidence_check.py
      - smartbuy/open_research/extractor.py
      - smartbuy/open_research/html_parser.py
      - smartbuy/open_research/models.py
      - smartbuy/open_research/normalizer.py
      - smartbuy/open_research/service.py
      - smartbuy/open_research/settings.py
      - smartbuy/open_research/store.py
      - smartbuy/open_research/url_safety.py
      - smartbuy/source_search/__init__.py
      - smartbuy/source_search/cache.py
      - smartbuy/source_search/models.py
      - smartbuy/source_search/provider.py
      - smartbuy/source_search/settings.py
      - smartbuy/source_search/validator.py
      - smartbuy/tools/source_search.py
      - smartbuy/tools/web_extractor.py

  monitor_governed_data:
    aggregate_sha256: bb1bff6c03c9cc4032ce95026859bc197e51765cd50038f9456ae4c87b574256
    file_count: 19
    members:
      - smartbuy/data/catalog/monitors_v1.json
      - smartbuy/data/demo/fact_cards/asus-pa279crv-cn.md
      - smartbuy/data/demo/fact_cards/asus-pa27jcv-cn.md
      - smartbuy/data/demo/fact_cards/asus-pg27aqdm-cn.md
      - smartbuy/data/demo/fact_cards/benq-ex2710u-cn.md
      - smartbuy/data/demo/fact_cards/benq-pd2705u-us.md
      - smartbuy/data/demo/fact_cards/benq-pd2725u-ca.md
      - smartbuy/data/demo/fact_cards/dell-g2724d-cn.md
      - smartbuy/data/demo/fact_cards/dell-s2722qc-cn.md
      - smartbuy/data/demo/fact_cards/dell-u2723qe-cn.md
      - smartbuy/data/demo/fact_cards/dell-u2724d-cn.md
      - smartbuy/data/demo/fact_cards/lg-27gs95qe-b-cn.md
      - smartbuy/data/demo/fact_cards/lg-27up850k-w-cn.md
      - smartbuy/data/demo/manifest.json
      - smartbuy/data/processed/evidence_records.jsonl
      - smartbuy/data/processed/index_manifest.json
      - smartbuy/data/processed/price_observations.jsonl
      - smartbuy/data/processed/products.jsonl
      - smartbuy/data/processed/source_records.jsonl

  laptop_governed_data:
    aggregate_sha256: 8abce10a2c17ed0189964fcf4b4104d2b2d1aa59a32a487e8b1b19c99b0fb09c
    file_count: 2
    members:
      - smartbuy/data/laptop/laptop_configurations_v1.json
      - smartbuy/product_packs/examples/laptop-v1/pack.json

  headphone_governed_data:
    aggregate_sha256: 560d6727f2c70edf076db66eb0d6d2d27b114254e004ccadf49bb7f86c40c869
    file_count: 2
    members:
      - smartbuy/data/headphone/headphone_configurations_v1.json
      - smartbuy/product_packs/examples/headphone-v1/pack.json

  scoring_interface:
    aggregate_sha256: 9f979e65c43822f9c90728d24e1c5a2df7d4b262db5d9d23b128e39e40849bfc
    file_count: 7
    members:
      - smartbuy/eval/stage6_scoring.py
      - smartbuy/eval/v2_6c_r2_laptop_scorer.py
      - smartbuy/eval/v2_6c_r2_laptop_scoring_policy.json
      - smartbuy/eval/v2_6c_r3_validation.schema.json
      - smartbuy/eval/v2_6c_r3_validation_scorer.py
      - smartbuy/eval/v2_8_headphone_engineering.schema.json
      - smartbuy/eval/v2_8_headphone_engineering_policy.json

  test_baseline:
    aggregate_sha256: 82885144501c0cf8315d1a796195ed0065cb858d2a285ab5bc74c013b5c02b7c
    file_count: 51
    members:
      - .github/workflows/ci.yml
      - smartbuy/tests/fixtures/v2_checkpoint_worker.py
      - smartbuy/tests/integration/test_stage4_api.py
      - smartbuy/tests/integration/test_v2_9c_semantic_boundaries.py
      - smartbuy/tests/integration/test_v2_api_orchestration.py
      - smartbuy/tests/integration/test_v2_clarification_orchestration.py
      - smartbuy/tests/integration/test_v2_domain_pack_compat.py
      - smartbuy/tests/integration/test_v2_headphone_domain_pack.py
      - smartbuy/tests/integration/test_v2_headphone_toolchain.py
      - smartbuy/tests/integration/test_v2_laptop_agent_e2e.py
      - smartbuy/tests/integration/test_v2_laptop_domain_pack.py
      - smartbuy/tests/integration/test_v2_laptop_toolchain.py
      - smartbuy/tests/integration/test_v2_live_product_index.py
      - smartbuy/tests/integration/test_v2_open_research_agent.py
      - smartbuy/tests/integration/test_v2_product_pack_pipeline.py
      - smartbuy/tests/integration/test_v2_ranking_memory_api.py
      - smartbuy/tests/integration/test_v2_source_search_agent.py
      - smartbuy/tests/integration/test_v2_sqlite_checkpoint.py
      - smartbuy/tests/integration/test_v2_three_domain_isolation.py
      - smartbuy/tests/integration/test_youtu_bailian_adapters.py
      - smartbuy/tests/unit/test_bailian_config.py
      - smartbuy/tests/unit/test_bailian_provider.py
      - smartbuy/tests/unit/test_stage3_data.py
      - smartbuy/tests/unit/test_stage3_database.py
      - smartbuy/tests/unit/test_stage3_retrieval_contract.py
      - smartbuy/tests/unit/test_stage4_agent.py
      - smartbuy/tests/unit/test_stage4_evidence.py
      - smartbuy/tests/unit/test_stage4_kb_search.py
      - smartbuy/tests/unit/test_stage4_memory.py
      - smartbuy/tests/unit/test_stage4_text2sql.py
      - smartbuy/tests/unit/test_stage5_agent_gate.py
      - smartbuy/tests/unit/test_stage5_constraints.py
      - smartbuy/tests/unit/test_stage5_verifier.py
      - smartbuy/tests/unit/test_stage6_cache.py
      - smartbuy/tests/unit/test_stage6_eval_contract.py
      - smartbuy/tests/unit/test_stage7_reporting.py
      - smartbuy/tests/unit/test_v2_constraint_proposals.py
      - smartbuy/tests/unit/test_v2_decision_core_metamorphic.py
      - smartbuy/tests/unit/test_v2_decision_ranking.py
      - smartbuy/tests/unit/test_v2_domain_pack.py
      - smartbuy/tests/unit/test_v2_headphone_open_research.py
      - smartbuy/tests/unit/test_v2_layered_memory.py
      - smartbuy/tests/unit/test_v2_live_constraint_provider_contract.py
      - smartbuy/tests/unit/test_v2_open_research.py
      - smartbuy/tests/unit/test_v2_orchestration_contract.py
      - smartbuy/tests/unit/test_v2_portfolio.py
      - smartbuy/tests/unit/test_v2_product_identity_scope.py
      - smartbuy/tests/unit/test_v2_product_pack.py
      - smartbuy/tests/unit/test_v2_quote_span_contract.py
      - smartbuy/tests/unit/test_v2_source_search.py
      - vendor/youtu-rag/tests/rag/api/test_config_security.py

domain_versions:
  monitor:
    domain_pack_schema: 1.0.0
    data_version: monitor-cn-2026-08-26-v1
    index_version: monitor-fact-card-h2-v1
    collection: smartbuy_monitors_v1
    products: 12
    sources: 16
    evidence: 180
    documents: 60
    chunks: 60
  laptop:
    domain_pack_schema: 1.0.0
    data_version: laptop-governed-2026-09-02-v1
    data_manifest_hash: c9ae040dd8220febb417537418d45532f3afba35c2f35ab0d8b7c5c361692623
    index_version: laptop-governed-2026-09-02-v1-embedding1024-v1
    index_manifest_hash: 0f3690ba22fa5877e5cf77210828c6449a7535950903e2eb5ce50fdc959b0d54
    collection: proofpick_laptop_v2_4e6d332c11bf8f7c
    products: 12
    sources: 12
    evidence: 406
    documents: 12
    chunks: 12
  headphone:
    domain_pack_schema: 1.0.0
    data_version: headphone-governed-2026-09-03-v1
    data_manifest_hash: 36c0bf08ce945a67e7ecd0e485a9a269e7ad942788d428f2cb8af925208e8018
    index_version: headphone-governed-2026-09-03-v1-embedding1024-v1
    index_manifest_hash: 5b766ff067f730578011c90cfe81a3575b2291d6856af063a2008eef12336f86
    collection: proofpick_headphone_v2_cae477364b46ccae
    products: 12
    sources: 20
    evidence: 336
    documents: 12
    chunks: 12

runtime_index_manifests:
  aggregate_sha256: e415a13e43475863ad5171b3dfd2b0b68f000784a91e02b205f8a86427bf3f20
  file_count: 7
  members:
    - logical_path: monitor/index_manifest.json
      sha256: e7e4052e2270f2b77db2dd247c2afa18c0b61cfe4167133c40dc6059b94f3fa0
    - logical_path: laptop/data/current.json
      sha256: 16e1dc34475ff459f794d2b82797679822e85367191504d0e76f7fb55a527f94
    - logical_path: laptop/index/current_laptop_index.json
      sha256: f98daf59ee310ebfa9d50e1b52fe70b6c5d1a5b709405d341efeeb6cba24ec99
    - logical_path: laptop/index/index_manifest.json
      sha256: c211ee7ba89efa239040a17873932634f9326b171b6cf8d7e39d72c7ce5d6943
    - logical_path: headphone/data/current.json
      sha256: 4e848647eb2595bc143471b543f6720d250dc88810e88eba38589913c7fb56ae
    - logical_path: headphone/index/current_headphone_index.json
      sha256: 99791167936aefae9188daeef53d766cbc82c7e43037cfe7d957f92870a5d051
    - logical_path: headphone/index/index_manifest.json
      sha256: cb93f392349504d0b47977531958b5da774ce620a118d350d450cbb55eccabfe

open_research_source_search_contract:
  source_search_provider: zhipu
  primary_engine: search_pro
  bounded_fallback: search_pro_sogou
  trusted_promotion: disabled
  open_evidence_enters_checker: false
  target_region_required_for_usable_source: true
  request_level_temporary_evidence_only: true

historical_results_immutable:
  independent_evaluation_commit: 03ad070d242596c7121da4f7bcf21a1f15758551
  members:
    - path: smartbuy/eval/results/v2_9b_independent_trusted_first.json
      sha256: 00299408748c3cd3b5cfba4c5a00db60678189af3f958e29d82d38a04ef72e81
      result: 64/90
      classification: immutable_independent_first
    - path: smartbuy/eval/results/v2_9b_independent_online_first_rc2.json
      sha256: e813bafa327d8b8d94049196b7c4deb099be5b7ead4eb3f108366081d38ce8fa
      result: actual_evidence_2/15
      classification: immutable_independent_first_completed_online
    - path: smartbuy/eval/results/v2_9b_independent_online_harness_failure.json
      sha256: b2a9121b3be08c43bebf97811b941436d0a1626555829d60dd207e6a88db83ed
      classification: immutable_evaluator_harness_incident
    - path: smartbuy/eval/results/v2_9b_independent_summary.json
      sha256: 854b7cbf2262afd78b4028e5bb8e04715dad34eaa34da65fe86233eff469cd7c
      decision: needs_revision
    - path: smartbuy/docs/v2/v2_9b_independent_release_evaluation.md
      sha256: de41e3a2037eca3f150dabf381353afeb2c0c1e36dc4b50db31f213da2c43273
      classification: independent_report
  exposed_regression:
    path: smartbuy/eval/results/v2_9c_exposed_regression_summary.json
    sha256: d42e9bbab629718f2a77c5f68f7817b25ecaf4d8e4f1ada06a9e03df84624357
    result: 86/90
    classification: exposed_regression_not_release_evidence

quality_gate:
  pytest_ci_equivalent: 479/479
  pytest_v1_original_files_current: 98/98
  pytest_v1_historical_nodes_preserved: 94/94
  ruff: passed
  compileall: passed
  javascript_syntax: 13/13
  powershell_ast: 6/6
  markdown_relative_links_before_rc2_docs: 421/421
  high_confidence_sensitive_matches_in_changes: 0
  new_forbidden_runtime_artifacts: 0
  paid_api_calls_during_rc2_freeze: 0

windows_reproduction:
  preflight: 11/11
  runtime_location: outside_git
  sqlite_integrity: [monitor_ok, laptop_ok, headphone_ok]
  sqlite_foreign_key_violations: 0
  http_200: [root, health, monitor, portfolio_capabilities, minio_health]
  portfolio_domains: [monitor_12, laptop_12, headphone_12]
  demo_contracts: 5/5
  demo_api_calls: 0
  offline_replay_http: 200
  replay_disclosure_present: true
  released_ports_after_stop: [8000, 8088, 9000, 9001]

boundaries:
  independent_decision: needs_revision
  new_holdout_created_or_run: false
  exposed_tasks_reclassified_as_holdout: false
  future_scoring_rules_viewed_or_changed: false
  independent_branch_modified: false
  root_readme_release_status_modified: false
  pull_request_created: false
  main_modified: false
  v1_tag_moved: false
  v2_tag_created: false
  github_release_created: false
```
<!-- RC2-PAYLOAD-END -->

## 复核入口

- V2-9C 修复与 exposed regression：[v2_9c_independent_evaluation_repair_report.md](v2_9c_independent_evaluation_repair_report.md)
- RC2 独立评测交接：[v2_9c_rc2_handoff.md](v2_9c_rc2_handoff.md)
- 五个固定演示：[v2_demo_guide.md](v2_demo_guide.md)
- Windows 历史干净克隆基线：[v2_9a_windows_reproduction.md](v2_9a_windows_reproduction.md)

独立评测方必须先核对生产 Commit、Tree、Payload Hash、成员列表和三套外部索引清单，再在未见任务上形成新的发布判断。不得覆盖或重新命名历史首次结果。
