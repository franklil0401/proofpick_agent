# ProofPick V2 RC4 冻结记录

本轮仅冻结候选并交接，不是发布或独立评测通过。生产版本固定，后续文档提交的 HEAD 不得冒充生产 Commit。

| 冻结项 | 身份 |
|---|---|
| RC | `proofpick-v2-rc4` |
| 交接分支 | `release/proofpick-v2-rc4` |
| 生产 Commit | `99c7bccc523addc7e8904571dbe8e20a24615c66` |
| 生产 Git Tree | `6b6e98009cefe5aa13f64cf8fe1b24d001fbadb1` |
| Semantic Payload SHA-256 | `7126740e9a893a18575f829aff78ef48b346eca0f622db73c952ece4cff8eb25` |
| 成员 | 23组；725个唯一文件；组内成员共出现838次，交叉分组允许重复 |
| 产品定位 | Trusted Multi-domain Decision Core + Experimental/Beta Online Research |

机器合同：[rc4_semantic_runtime_manifest.json](rc4_semantic_runtime_manifest.json)。每组都包含完整、有序的 `members[{path, sha256}]` 和 `aggregate_sha256`，没有依赖外部隐含清单。运行配置和成员选择方法同时写入 `semantic_contract.freeze_recipe`；独立复现配方另存 [rc4_freeze_recipe.json](rc4_freeze_recipe.json)。

## 1. Git blob 冻结算法

复用已经验证的 [R1 Git object 方法](../../reproducibility/semantic_manifest.py)及[分组生成器](../../reproducibility/v2_9h_rc3_manifest.py)，不修改其源码。新增的 [冻结文档工具](rc4_freeze_manifest.py)不在生产调用链中，只对固定 Commit 生成/核对候选文档。

1. `git ls-tree -r -z --name-only <生产Commit>` 唯一决定可选成员；不枚举工作区文件来决定成员集。
2. 每个成员用 `git cat-file blob <生产Commit>:<path>` 获取原始字节并计算 SHA-256，不读取 `Path` checkout 字节作为成员哈希。
3. 每组按路径排序，对完整成员数组使用 UTF-8、`ensure_ascii=false`、`sort_keys=true`、紧凑分隔符的 canonical JSON 计算 Aggregate。
4. 对整个 `semantic_contract` 按相同 canonical JSON 算法计算 Payload。不能用 JSON 文件原始字节 SHA 替代这个语义 Payload。
5. 时间、延迟、Token、费用、机器路径和 CI 观测留在 `runtime_audit`/审计记录，不进入语义哈希。稳定模型参数、版本、Collection、文档数和数据逻辑哈希进入合同。

原19组保留并按新生产 Commit 重算；额外补齐 `domain_pack_runtime`、`upstream_api_and_runtime`、`frontend_runtime_assets`、`runtime_build_and_validation`，包括领域加载器、数据派生与SQL Schema、上游入口、配置、前端和构建脚本。`test_baseline`补入CI实际执行的上游安全测试及其conftest。原RC3 Tree本来已绑定这些文件；本次补足显式分组可审计性，没有修改它们。

所有组名：`agent_tool_orchestration`、`all_production_python`、`constraint_checker`、`constraint_resolution_clarification`、`dependency_lock`、`domain_pack_config`、`domain_pack_runtime`、`evidence_check`、`frontend_runtime_assets`、`governed_data`、`memory`、`open_research_source_search_beta`、`product_pack_contract_and_runtime`、`product_ui_and_demo_contract`、`prompt_contract`、`query_intent_product_reference_candidate_scope`、`ranker`、`runtime_build_and_validation`、`scoring_interface`、`test_baseline`、`tool_schema_and_contracts`、`upstream_api_and_runtime`、`windows_scripts`。完整SHA和成员以机器合同为准。

## 2. 数据与索引语义

| 品类 | Data Version | Index Version | Collection | 文档/Chunk | 维度 |
|---|---|---|---|---|---|
| Monitor | `monitor-cn-2026-08-26-v1` | `monitor-fact-card-h2-v1` | `smartbuy_monitors_v1` | 60/60 | 1024 |
| Laptop | `laptop-governed-2026-09-02-v1` | `laptop-governed-2026-09-02-v1-embedding1024-v1` | `proofpick_laptop_v2_4e6d332c11bf8f7c` | 12/12 | 1024 |
| Headphone | `headphone-governed-2026-09-03-v1` | `headphone-governed-2026-09-03-v1-embedding1024-v1` | `proofpick_headphone_v2_cae477364b46ccae` | 12/12 | 1024 |

三个 Domain Pack 版本均为1.0.0，每品类12个治理配置；没有加入第13显示器的可选Product Pack到默认Monitor路径。Embedding为`text-embedding-v4`，Reranker为`qwen3-rerank`。

本轮在新的仓库外临时目录离线重建三套SQLite/数据产物：Monitor 12商品/16来源/180证据，Laptop 12/12/406，Headphone 12/20/336；三套 `integrity_check=ok`、外键违规0。三套逻辑数据SHA均与合同一致。

哈希口径不得混用：Monitor `data_logical_sha256=079c4f74…`来自`build_stage3_data.py`对products/prices/derived sources/evidence对象的canonical JSON；SQLite行布局SHA为`3d37a2c3…`，不是同一算法。Laptop/Headphone使用`DomainProductPackManager`的`logical_data_sha256`。具体算法已写入配方。既有原始数据、数据库Schema及历史Manifest均不改。

本轮没有构建或探测真实向量索引。索引版本/数量来自固定生产版本已有建库证据及代码；独立方运行前必须检查其本机Data/Index指针、Collection、文档数和1024维合同，不能把生成Manifest当成当前索引存在的证明。

## 3. 实际默认产品配置

详细值见机器合同的`runtime_configuration`；这是固定代码与文档启动配置的审计，不是读取当前机器的敏感环境或假装已启动服务。

- WebUI默认是Headphone、Trusted、**回放**；只有主动选择实际运行才发送`POST /api/smartbuy/portfolio/run`。回放不是真实模型调用。
- Monitor：`ClarifyingOrchestrator → OrchestratorSelector → ReactOrchestrator → PurchaseDecisionAgent`，默认`ConstraintNormalizer`已具备V2-9J单位、完整性与身份修复，不需要开启Natural/Domain Pack隐藏开关。
- Laptop/Headphone：`PortfolioRuntimeManager → ReactOrchestrator → DomainDecisionAgent`，`NaturalConstraintEngine(pack, provider=None)`默认不调用qwen-plus提出约束，KB才使用云端Embedding/Reranker。不能用专用Runner的Qwen Proposal配置代替这个产品事实。
- `start.ps1`将`PROOFPICK_DOMAIN_AGENT_ENABLED`设为true；其他可选开关未设置时为配方中的代码默认值。脚本不清空继承开关，独立方必须核对有效的非敏感开关；不能偷偷开启另一条链路后称为默认产品结果。
- Monitor模型qwen-plus，temperature=0，max_tokens=800，最多8次模型循环/12次工具，工具20秒、任务估算¥0.25。循环后仍可能有确定性Evidence补查和强制Checker。领域入口不具备完全相同的统一金额/总时间预算，须由评测方外层预算控制。
- qwen-plus是未固定日期版本的供应商别名；top_p/seed未显式设置。默认不安装热缓存包装。价格as_of随构建/调用UTC时间变化，评测必须另存实际时间，不能伪称完全固定的线上确定性。
- 长期Memory默认不启用。Portfolio的Open请求返回HTTP409，Beta真实研究仍需独立有界脚本；浏览器PoC未接入生产。

## 4. 验证证据与历史保护

生产Commit的[开发回归记录](../../eval/results/v2_9j_development_regression.json)：全量597/597，新增定向79/79（其中默认Portfolio API23项），V1原始18个测试文件101/101。79项属于597项的子集，不可相加。

同一生产Commit的[Windows CI](https://github.com/franklil0401/proofpick_agent/actions/runs/33966853197)已核对为success：597 passed，3条既有弃用警告，211.53秒；Ruff、Compileall、JS13/13、PS6/6、当时链接501/501均通过。这些是离线/Fake Provider与本地数据合同证据，**不是真实模型发布评测通过**。本轮冻结验证另见[审计记录](rc4_freeze_audit.json)。

旧RC3生产`ba6606ae…`/Tree`84766c5d…`、失败Payload`4883f425…`及R1 Payload`abf65501…`原样保留。V2-9J首次开发失败、修复后回归和独立评测事故均不覆盖；历史7/11仅指已执行11题，不是三品类总体正确率。Online独立首测0/15、V2-9F暴露回归6/15与未投产Playwright保守投影7/15仍是历史边界，安全unknown不算完成取证。

交接：[RC4独立评测Handoff](v2_rc4_independent_evaluation_handoff.md) · [V2-9J修复报告](v2_9j_trusted_contracts_repair_report.md) · [项目结构](../development/PROJECT_STRUCTURE.md)。
