# ProofPick V2 Release Candidate Manifest

## 冻结声明

本文件冻结 `proofpick-v2-9a-rc1`，供后续独立评测复核。它不是 Git Tag、GitHub Release、生产 SLA 或 V2 最终验收；本轮没有运行 V2-9B 最终 Holdout。`production_commit` 是 Manifest 生成前最后一个业务、UI、脚本与说明提交，Manifest 之后如需修改生产文件，必须创建新的 RC 编号与哈希。

Manifest SHA-256 的计算对象是下方 `RC-PAYLOAD-BEGIN/END` 标记之间的 UTF-8 文本，去除首尾空白后补一个 LF；不包含本段、标记本身或 SHA 行。

**Manifest SHA-256：** `7db3b3a63011848b260c06ea98e6cf9b5e874267df298c042ac56760f8d2c5f5`

<!-- RC-PAYLOAD-BEGIN -->
```yaml
manifest_schema: proofpick-release-candidate-v1
release_candidate: proofpick-v2-9a-rc1
generated_at_utc: 2026-09-04T05:12:16.319Z
branch: feature/proofpick-v2
production_commit: dac24123b82683c6708f0d487d9ab9753b172aed
v1_stable_commit: d51b6668a6a45c1b01ef4e64da3c4b9ac84ed10c
v1_tag: v1.0.0-portfolio

runtime:
  os: Windows 11
  python: 3.12.3
  uv: 0.12.3
  git: 2.54.0.windows.1
  dependency_lock_sha256: 8e2e889757a4369d0dfef9d5a262f50b6934ef0eede063434a726bb7b8ab94d8
  default_orchestrator: react
  agent_limits:
    max_steps: 8
    max_tool_calls: 12
  models:
    llm: qwen-plus
    embedding: text-embedding-v4
    embedding_dimensions: 1024
    reranker: qwen3-rerank
  source_search:
    provider: zhipu
    primary_engine: search_pro
    bounded_fallback: search_pro_sogou
  feature_flags:
    portfolio_online_domain_agent: explicit_enable
    langgraph: explicit_enable_non_default
    natural_constraints: explicit_enable
    source_search: explicit_enable
    open_research: explicit_enable
  secrets:
    persisted_in_manifest: false
    values_read_or_printed_for_freeze: false

contracts:
  prompt_sha256: 2cfcbee7f03a83f40ad6d4e2553157b2aabf026a0f42d0dbb855624c9ef6ac7d
  prompt_file_count: 2
  tool_schema_sha256: 4a34e0b50100a40e04aa209fbbc2f70e13d51866fe1781619621c9b9972ac8b9
  tool_schema_file_count: 19
  checker_sha256: cbaae8b38a67b95a7ed95ab4aacd1345df21ac3bc4de905a65a682a93b7074a7
  checker_file_count: 9
  ranker_sha256: 7e3eb2e9a76359c1aeed22f217cba2cc9bc02176b45d60a6a043c45012a15c28
  ranker_file_count: 7
  memory_sha256: 944d30c336f74820affd50eef14e6acb1d8608dea3afd3273aef8d391a8d1f3e
  memory_file_count: 3
  versions:
    v1_constraint_checker: smartbuy-constraint-checker-v1
    domain_checker: proofpick-domain-checker-v2-6b
    layered_memory: proofpick-layered-memory-v1
    constraint_proposal: proofpick-constraint-proposal-v1
    constraint_resolution: proofpick-constraint-resolution-v1
    natural_constraints: proofpick-natural-constraints-v1

domain_packs:
  aggregate_config_sha256: 952d23545fea8454674672ef42a6919958f5f94582a3b239a809d26f802cff85
  aggregate_file_count: 10
  monitor:
    schema_version: 1.0.0
    data_version: monitor-cn-2026-08-26-v1
    index_version: monitor-fact-card-h2-v1
    collection: smartbuy_monitors_v1
    products: 12
    sources: 16
    evidence: 180
    vector_documents: 60
  laptop:
    schema_version: 1.0.0
    data_version: laptop-governed-2026-09-02-v1
    index_version: laptop-governed-2026-09-02-v1-embedding1024-v1
    collection: proofpick_laptop_v2_4e6d332c11bf8f7c
    products: 12
    sources: 12
    evidence: 406
    vector_documents: 12
    data_manifest_sha256: 0f3690ba22fa5877e5cf77210828c6449a7535950903e2eb5ce50fdc959b0d54
  headphone:
    schema_version: 1.0.0
    data_version: headphone-governed-2026-09-03-v1
    index_version: headphone-governed-2026-09-03-v1-embedding1024-v1
    collection: proofpick_headphone_v2_cae477364b46ccae
    products: 12
    sources: 20
    evidence: 336
    vector_documents: 12
    data_manifest_sha256: 5b766ff067f730578011c90cfe81a3575b2291d6856af063a2008eef12336f86

frozen_repository_inputs:
  governed_data_sha256: b0589cc8a24da84b01dcdffdea8eecbf3b8e1b20a8ecc2bf2d35c04975205f5e
  governed_data_file_count: 37
  evaluation_definitions_sha256: 672f5899f24fbe95226c03f74b7fc56a164d35efb08767a0b5014d2e363e1a15
  evaluation_definition_file_count: 62
  historical_results_sha256: adece94b14573f1e0564911fab7e8cf6139c4a90e722edc38cc17d8502659413
  historical_result_file_count: 43
  demo_inputs_sha256: 7c6674365f4643892b14c615aeb1be1a63e94f212d491fa54c8d86b67742f9ed
  demo_input_file_count: 1
  hash_method: "sorted tracked relative path + NUL + binary file SHA-256 + LF"

clean_windows_reproduction:
  clone_path: C:\\ppv2rc
  runtime_root: C:\\ppv2run
  frozen_sync_packages: 296
  preflight: 11/11
  demo_contracts: 5/5
  http_200: [root, health, monitor, portfolio_capabilities, minio_health]
  released_ports_after_stop: [8000, 8088, 9000, 9001]
  repository_status_after_run: clean
  embedding_build_calls: 64
  trusted_smoke_calls:
    embedding: 2
    reranker: 2
    llm: 0
  estimated_stage_api_cost_cny: "<0.03"

quality_gate:
  pytest_ci_scope: 467_passed
  pytest_v1_original_scope: 94_passed
  v2_8_regression: 40/40
  v2_7_regression: 32/32
  v2_6c_engineering_regression: 109/109
  v2_5c_regression: 48/48
  portfolio_tests: 8_passed
  demo_contracts: 5/5
  ruff: passed
  compileall: passed
  javascript_syntax: 13/13
  powershell_ast: 6/6
  markdown_relative_links: 415/415
  archify_showcase: 9/9
  current_tracked_high_confidence_credentials: 0
  git_history_high_confidence_credentials: 0
  git_history_blobs_scanned: 1680
  unexpected_tracked_runtime_or_secret_artifacts: 0
  api_calls_during_final_offline_quality_gate: 0

boundaries:
  independent_v2_final_holdout_run: false
  v2_9b_started: false
  pull_request_created: false
  main_modified: false
  v1_tag_moved: false
  github_release_created: false
  production_sla_claimed: false
```
<!-- RC-PAYLOAD-END -->

## 独立复核入口

- Windows 干净克隆证据：[v2_9a_windows_reproduction.md](v2_9a_windows_reproduction.md)
- 五个固定演示：[v2_demo_guide.md](v2_demo_guide.md)
- 阶段结论与能力边界：[v2_9a_release_candidate_report.md](v2_9a_release_candidate_report.md)
- V2-9B 交接和回滚：[v2_9a_handoff.md](v2_9a_handoff.md)

独立评测应先校验本 Manifest、Commit 和输入哈希，再创建并冻结新的评测任务。历史 exposed regression、五 Demo 与工程测试不得冒充未见 Holdout。
