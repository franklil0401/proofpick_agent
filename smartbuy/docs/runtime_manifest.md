# ProofPick Runtime Manifest（SmartBuy 显示器场景）

最后更新：2026-09-02
当前阶段：V1 已冻结；V2-4 Web Extractor、临时 Open Evidence 与开放研究模式已完成，默认关闭
运行范围：V1 Windows 11 原生 Youtu-RAG + 百炼三模型 + SmartBuy 数据/SQLite/Chroma + 有界 Agent + 确定性 Checker；V2 opt-in 编排/Domain/Product Pack/Source Search/Open Research 兼容层

## 代码与纳入方式

| 项目 | 固定值 |
|---|---|
| 当前项目分支 | V1 稳定版 `main`；V2 开发 `feature/proofpick-v2` |
| Youtu-RAG 上游仓库 | <https://github.com/TencentCloudADP/youtu-rag> |
| Youtu-RAG Commit | `ce5c3010ff2e2a1c3e657ebcba14481ac5a2b066` |
| 安全清理派生 Commit | `87af8dcf679f82779257c32c262d34285b6b9903`；仅处理 GitHub 对模型类名的 Secret 误报 |
| 纳入日期/方式 | 2026-08-26，`git subtree --squash` |
| 供应商目录 | `vendor/youtu-rag/` |
| 上游许可证 | MIT，见 `vendor/youtu-rag/LICENSE` |
| `uv.lock` SHA-256 | `726A4CC25B64C0B0C98DBADB51218F86433C7C424B52D40C88FE0910B1BFB659` |

详细纳入方式见 [ADR-0001](adr/0001-vendor-youtu-rag.md)，Provider/索引决策见 [ADR-0002](adr/0002-bailian-provider-and-index-contract.md)，数据和索引版本见 [ADR-0003](adr/0003-governed-monitor-data-and-index.md)，Agent/Memory 决策见 [ADR-0004](adr/0004-bounded-react-evidence-and-memory.md)，确定性安全门见 [ADR-0005](adr/0005-deterministic-constraint-gate.md)，评测/缓存/韧性决策见 [ADR-0006](adr/0006-reproducible-evaluation-cache-and-resilience.md)，V2 编排决策见 [ADR-0007](adr/0007-langgraph-orchestration-decision.md)与 [ADR-0008](adr/0008-langgraph-compatibility-and-checkpointing.md)，Domain Pack 决策见 [ADR-0009](adr/0009-domain-contracts-and-monitor-pack.md)，Product Pack/Ledger 决策见 [ADR-0010](adr/0010-versioned-product-pack-and-evidence-ledger.md)，Source Search 决策见 [ADR-0011](adr/0011-auditable-zhipu-source-search.md)，供应商差异见根目录 [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)。

## 主机与关键版本

| 项目 | 实测值 |
|---|---|
| 操作系统 | Windows 11 |
| CPU / 内存 / GPU | Intel i5-10400F / 32 GB / GTX 960 2 GB |
| Python | 3.12.3 |
| uv | 0.12.3 |
| Git | 2.54.0.windows.1；`git subtree` 可用 |
| FastAPI | 0.116.2 |
| ChromaDB | 1.3.4 |
| FAISS | 1.12.0 |
| MinIO Python Client | 7.2.18 |
| MinIO Server | `RELEASE.2025-09-07T16-13-09Z` |
| MinIO 二进制 SHA-256 | `AF709E6BA68488404E85ACDD22A3030D0F5E56A108D4B27D744F18CEB50861B4` |

## 依赖与运行路径

- 依赖同步：`uv sync --project vendor/youtu-rag --frozen` 成功，294 packages checked，锁文件未修改。
- 虚拟环境：`vendor/youtu-rag/.venv/`，由 Git 忽略。
- MinIO Server / 数据：`C:/ai/minio/minio.exe`、`C:/ai/minio-data/`。
- Youtu-RAG 运行根目录：`C:/ai/youtu-rag-runtime/`。
- 1024 维向量索引：`C:/ai/youtu-rag-runtime/vector_store_bailian_v4_1024/`。
- 阶段 3 SQLite：`C:/ai/smartbuy-stage3/smartbuy_monitors_v1.sqlite`。
- 阶段 3 Chroma：`C:/ai/smartbuy-stage3/vector_store_text_embedding_v4_1024/`，collection `smartbuy_monitors_v1`。
- 阶段 4 长期偏好（本地运行时）：`C:/ai/smartbuy-stage4/preferences.json`；评测偏好使用独立文件，不进入 Git。
- 阶段 5 在线评测偏好：`C:/ai/smartbuy-stage5/eval_preferences.json`；只含评测生命周期数据，不进入 Git。
- 阶段 6 分片检查点和临时缓存：`C:/ai/smartbuy-stage6/`；仅用于可恢复运行，原始检查点不进入 Git，合并审计和脱敏汇总进入仓库。
- 阶段 7 服务状态、日志和截图浏览器临时数据：`C:/ai/smartbuy-stage7/`；不进入 Git。
- 发布脚本通过 `SMARTBUY_DB_PATH`、`SMARTBUY_INDEX_PATH`、`SMARTBUY_MEMORY_PATH` 将实际服务绑定到明确的仓库外短路径。
- API/WebUI：`127.0.0.1:8000`；MinIO API/Console：`127.0.0.1:9000` / `127.0.0.1:9001`。
- 运行数据库、向量索引、MinIO 数据和日志均在仓库外，不进入 Git。
- V2 Product Pack 运行根目录：默认 `C:/ai/proofpick-v2/product-packs/`；staging、不可变版本、SQLite、事实卡、向量文档、临时证据与指针均不进入 Git。

## 模型与配置契约

| 能力 | 配置 | 当前状态 |
|---|---|---|
| LLM | `qwen-plus` | 普通、SSE 流式、Tool Calling 均通过 |
| Embedding | `text-embedding-v4`，固定 1024 维 | 批量数量、顺序、维度、语义顺序和 Youtu 建库均通过 |
| Reranker | `qwen3-rerank`，完整 `/compatible-api/v1/reranks` | 独立排序与 Youtu 二阶段排序均通过；失败可显式降级 |
| OCR / HiChunk | 关闭 | 阶段 2 文本夹具不需要 |
| Web Search | 未配置 | 不阻塞；默认基础 Agent 不加载 Serper |
| V2 Source Search | 智谱 `search_pro` → `search_pro_sogou`；默认关闭 | 只发现官方 URL；6/8 精确地区命中，2/8 安全降级；不进入 Evidence/Checker |
| SmartBuy Agent | qwen-plus Tool Calling；8 steps / 12 tool calls | KB/SQL/Evidence/Memory/报告通过；Web 只验证 unavailable 降级 |
| Constraint Checker | `smartbuy-constraint-checker-v1`；只读 SQLite/evidence | 完整候选池、来源门禁、四态、边界、fail-closed 和重复执行通过；0 API 调用 |
| Stage 6 Eval | qwen-plus，temperature=0，max output=800；固定数据/索引/as_of | A/B/C/D 相同 40 条自然任务，各 3 次；配置和数据哈希已冻结 |
| Safe Cache | `smartbuy-stage6-cache-v1`；默认关闭 | 仅公开稳定中间结果；TTL/容量/版本/校验和/手动清空及损坏绕过通过 |
| Eval Ledger | `smartbuy-eval-ledger-v1` | 记录运行、步骤、Token、成本、延迟、重试、命中和降级；禁止 Prompt、Key、Authorization 和思维链 |
| 本地模型 | 关闭 | 不作为主要在线链路 |

百炼配置只从当前进程继承的 `Qianwen_api_key` 和 `Qianwen_workspace_id` 读取。V2 Source Search 仅在 `PROOFPICK_SOURCE_SEARCH_ENABLED=true` 时读取 `ZhiPu_api_key`；默认关闭时不读取该 Key。启动脚本不读取 Windows 注册表、不写 `.env`、不输出任何值。轮换 Key 后必须重启所有长运行进程。

## 服务与知识库结果

- WebUI `/`、`/health`、`/monitor`：HTTP 200。
- 阶段 1 自制 Markdown 文件仍可管理。
- 测试知识库 ID 1，源最终状态 `completed`。
- API 报告 `chunks_created=2`；目标 Chroma collection 实际 `count=2`。
- KB Search：向量召回成功，答案非空并命中夹具关键事实。
- 二阶段 Rerank：成功事件 1 次，未触发降级。
- 最终一次 Chat 端到端约 9.096 秒；单样本只证明链路可用，不代表 P95。

阶段 3 正式显示器知识库：

- 数据/Schema：`monitor-cn-2026-08-26-v1` / `1.0.0`；12 型号、4 品牌、16 来源、180 证据。
- SQLite：products 12、price_observations 4、source_records 16、evidence_records 180；0 外键违规，`integrity=ok`。
- 索引：`monitor-fact-card-h2-v1`；60 文档/60 chunks；Youtu 构建器与 Chroma 计数一致。
- Chunk 元数据：12 个必需字段无缺失；12 个唯一型号；地区标签 CN/US/CA；Embedding 模型/维度为 `text-embedding-v4`/1024。
- Reranker 降级：强制故障用例保持前五向量顺序并显式标记 degraded。

阶段 4 SmartBuy Agent：

- API：`POST /api/smartbuy/chat`（JSON 或 SSE）、`GET /api/smartbuy/monitor`、`/api/smartbuy/memory/{user_id}` 生命周期接口。
- WebUI：聊天页 SmartBuy 开关切换到独立端点；复用上游 `tool_call/tool_output/done` 卡片；`/monitor` 追加脱敏摘要。
- 有界执行：最多 8 步、12 工具调用、20 秒单工具超时、0.25 元单任务预算。
- 数据库：Text2SQL 只读打开阶段 3 SQLite；单 SELECT、表列白名单、authorizer、执行时限和 20 行上限。
- 证据：按稳定型号/地区/字段/时效/冲突输出四态；Reranker 分数不作为主要拒答规则。
- 真实服务冒烟：`127.0.0.1:8001` 的根页面、WebUI、`/monitor`、SmartBuy SSE 均 HTTP 200；SSE 三类事件与 Monitor 运行计数通过，敏感标记为 0；测试后进程已关闭。

阶段 5 Constraint Checker：

- 入口：ReAct 有界循环结束后由运行时强制调用；不在 LLM 工具白名单中，输入为 SQL/KB/Evidence 累计的完整稳定 `model_id` 池。
- 数据：复用 `monitor-cn-2026-08-26-v1`、Schema `1.0.0` 和工作区外只读 SQLite；价格最大年龄 30 天，固定评测 `as_of=2026-08-27T00:00:00Z`。
- 契约：`smartbuy-constraint-checker-v1`；只有全部受支持硬约束 passed 才 eligible，unknown/conflict/unsupported/ambiguous 和 Checker 异常均 fail closed。
- 输出：`DecisionReport smartbuy-decision-v3` 含 ConstraintSet、完整 VerificationBatch、证据/来源 ID、显式 unknown/conflict、语义指纹和 Checker 延迟。
- 前端：SSE 增加 `constraint_check_started/completed`；WebUI 和 `/monitor` 展示脱敏候选字段状态、版本和延迟。

阶段 6 评测与韧性：

- 冻结自然集 40 条（regression 16 + holdout 24），SHA-256 `6082ac83d72441fedf7ac3083a3c53f31d538ca54216f2cf99d3a9de5068e0ef`；故障集 13 条、Memory 集 5 条另行计分。
- 公平配置哈希 `c5001c9707c5cb7302c26745407cf989676e832b6984109604dec829754ab096`；主实验禁用缓存，A/B/C/D 各 40 条 × 3 次，共 480 个唯一预测。
- 首次运行 E2E：Direct LLM 16/40、Fixed RAG 17/40、Agentic RAG 28/40、Agentic RAG + Checker 31/40；增强组违规候选推荐 0/43。
- 三次聚合 E2E：A 46/120、B 51/120、C 81/120、D 92/120；增强组候选集合 40/40、拒答 39/40 一致，工具路径 33/40 一致。
- 同输入 Checker 三次执行 40/40 字节级一致；不调用模型、不产生额外 API 成本。
- 缓存基准 5 条公开 KB 查询：冷/热平均 1441.682/10.436ms，输出 5/5 一致，热缓存命中 5/5；动态价格明确绕过。
- 受控故障注入 13/13 正确识别、重试或降级，静默伪装 0；Checker 异常 fail closed。Memory 修复前 4/5，修复后 5/5，首次结果保留。
- 当前阶段 4 全量回归 16/16；阶段 4 原始 15/16、阶段 5 首次 13/16 和后续定向修复保持为独立历史记录。
- 详细精确分母、首次失败、缓存、故障、Token/成本和有效性威胁见[阶段 6 报告](stage6_evaluation_and_resilience_report.md)。

阶段 7 发布候选与 Demo：

- 相同冻结配置仅运行 D 组一次：E2E 34/40、regression 16/16、holdout 18/24；字段硬约束 183/183、违规推荐 0/56、多跳 23/23。
- 首次 unknown/conflict 为 2/5；三条问题定向回归各 1/1，两个报告展示收敛回归 2/2。首次 40 条结果未覆盖。
- 四个固定本地 API Demo 4/4；6 次 Agent 调用估算 ¥0.2202436；WebUI 首页与 4 张脱敏回放截图进入仓库。
- Windows 发布脚本在当前开发仓库完成 11/11 preflight、294 个冻结包检查、SQLite 12/4/16/180、Chroma 60 chunks、WebUI/health/monitor HTTP 200 与 stop 后端口释放。
- 首次全新 clone 的依赖、SQLite 和索引虽通过，但暴露 CRLF 原始字节哈希与仓库内索引运行清单造成的工作树差异；第二个 clone 的预检/冻结安装通过，但旧校验器仍按原始字节复核 catalog 并主动阻断。两次均保留且未宣称成功。
- 第三个全新 clone 在 Commit `79e5575198919d323d22b6cb23719540610ea966` 通过 11/11 preflight、294 包、SQLite、60-chunk Chroma、三页面 HTTP 200、四 Demo 4/4、stop 端口释放与工作区 0 变化。
- 阶段 7 可审计在线成本 ¥2.1072924，低于 ¥5；最终自动化 95 passed，静态/语法/冻结/数据质量门通过。
- 详细证据见[阶段 7 发布报告](release_report.md)与[Demo 指南](demo_guide.md)。

V2-1C ～ V2-2 兼容层：

- 默认编排器仍为 `react`；LangGraph 只能通过 `PROOFPICK_ORCHESTRATOR=langgraph` 显式开启，当前仍是完整 V1 ReAct 的兼容封装，不具备切换默认值的条件。
- `PROOFPICK_DOMAIN_PACK_ENABLED` 默认 `false`；关闭时不加载 Pack、不包装请求、不迁移 V1 数据。显式开启后加载 `smartbuy/domain_packs/monitor/`，缺失、损坏、版本或冻结 Catalog 哈希不兼容均 fail closed。
- Domain 契约版本 `proofpick-domain-contract-v1`；Monitor Manifest/Pack/Loader 为 `1.0.0`，映射 23 个字段、12 个现有 Checker 字段、8 个 Memory key 和 V1 `smartbuy-decision-v3` 响应。
- Monitor Pack 保留 V1 `monitor-cn-2026-08-26-v1` 兼容项，并新增可选数据版本 `monitor-multi-region-2026-08-31-v2`；V1 canonical Catalog、事实卡、SQLite/Chroma 和冻结评测均未修改。
- Product Pack `1.0.0` 示例以数据方式增加美国版 `dell-u2725qe-us`；离线快照为 13 products、4 prices、17 sources、196 evidence、13 事实卡和 65 向量文档。Manifest/SQLite 逻辑哈希、artifact hashes、许可与来源字段均受校验。
- 字段级 Ledger 共 196 条，正式记录绑定来源、片段、地区、配置版、来源版本和观察时间；请求级临时证据必须位于仓库外且不会自动晋升。
- `PROOFPICK_PRODUCT_PACK_ENABLED` 默认 `false`；开启后只接受完整已发布版本，异常 fail closed，不静默回退。数据关闭后可无迁移恢复 V1。
- Product Pack 主体离线测试 20/20；V2-2B 增加 3 条本地事务测试，并在仓库外完成 `monitor-multi-region-2026-08-31-v2` / `monitor-multi-region-h2-v2-embedding1024-r1` / `proofpick_monitor_v2_b9e7bc6d41a735fa` 的真实 65-chunk Chroma。Embedding 固定 `text-embedding-v4`/1024；建库与最小查询（含首次失败估算）约 ¥0.0169。Product Pack 仍默认关闭，未完成索引会 fail closed。
- 历史 V1/V2-1C 的 95/120 是 CI 等价范围；`smartbuy/tests` 对应为 94/119，唯一差异是显式加入的上游配置安全 node，不存在实际测试缺失。详见 [V2-2 报告](v2/v2_2_product_pack_report.md)。
- 本地导入、发布、回滚和安全边界见 [V2-2 运行说明](v2/v2_2_runtime.md)。

V2-3 受控 Source Search：

- `PROOFPICK_SOURCE_SEARCH_ENABLED` 默认 `false`；关闭后不注册新工具，V1 `web_search` unavailable 和 KB + SQL 主链保持不变。
- `SourceSearchProvider` 当前只实现智谱；百炼/智谱/博查只读预选覆盖分别为 4/8、6/8、1/8，三家组合 7/8，未实现 Composite Provider。
- 最终精确站点复测：`search_pro` 直接 4/8、搜狗恢复 2 条，总计 6/8；另 2/2 返回 `no_region_matched_source`。错误地区、unknown、白名单外和错误型号进入 usable 均为 0。
- Source Candidate 固定不能进入 Evidence Ledger 或 Checker。V2-3 不抓网页正文，不核验页面规格，不提供实时价格或库存。
- 最终复测 12 次调用、估算 ¥0.44、平均 1,780.551ms、小样本 P95 4,337.367ms；首次根域过滤 4/8、14 次/¥0.54 原样保留。详见 [V2-3 报告](v2/v2_3_source_search_report.md)。

V2-4 Web Extractor 与 Open Research：

- `PROOFPICK_OPEN_RESEARCH_ENABLED` 默认 `false`；只有同时开启 Source Search 且请求 `mode=open` 时注册 Web Extractor。关闭后恢复 Trusted/V1 本地路径。
- 网页抽取只接受本轮 Source Candidate，执行官方域名、SSRF/DNS、每跳重定向、HTML 类型、5 MiB 解压后大小和总超时安全门；不继承系统代理，不保存完整 HTML。
- Open Evidence 位于仓库外，按 user/session/thread/request 不透明 token 隔离，TTL 24 小时；查看、删除、过期清理、关闭和损坏降级均受测试。
- `BenQ PD3226G/US` 数据库外真实链路最终 6/6 目标字段 matched、21 条临时证据、conflict 0；`Dell P2725QE/CN` 的 USB-C 供电多值按 conflict 保留。
- LG 27GS95QE-B/CN 与 BenQ PD2725U/CA 的 canonical/hreflang 自动恢复 0/2，均明确降级且未硬编码 URL。Open 商品进入 Trusted eligible、正式 Ledger/Checker 均为 0。
- 阶段已知 28 次智谱搜索估算 ¥1.08，LLM/Embedding/Reranker 调用 0。详见 [V2-4 报告](v2/v2_4_open_research_report.md)和[运行说明](v2/v2_4_runtime.md)。

V2-5 自然约束与主动澄清：

- `PROOFPICK_NATURAL_CONSTRAINTS_ENABLED` 默认 `false`，请求还需显式 `use_natural_constraints=true`；关闭后恢复 V1 解析与默认 ReAct，不迁移数据。
- 中文数字、范围、单位、否定、双重否定、覆盖和取消由确定性规则优先；规则无结果时才允许 qwen-plus 严格 Function Calling 提案，逐条经过原文 span 和 Monitor Pack 校验。
- ambiguous/needs_confirmation/unsupported/invalid 在确认前进入 Checker 为 0；pending 不写长期 Memory；当前输入继续覆盖会话和已启用偏好。
- ReAct 使用仓库外严格 JSON 暂停状态，LangGraph 使用现有 interrupt/checkpoint；两者共享同一 Resolution。默认目录 `C:/ai/proofpick-v2/clarifications`，拒绝仓库内路径和 Pickle。
- 50 条冻结表达（30 Regression、20 Holdout）最终 55/55 字段、50/50 任务；首次实现 46/50 保留。双编排器 5 类澄清各通过一次，暂停前 Agent 调用 0、恢复后 1。
- 本阶段 API、Token、费用均为 0；离线规则平均/P95 0.457/0.703 ms，仅为本机小样本。详见 [V2-5 报告](v2/v2_5_constraint_clarification_report.md)和[运行说明](v2/v2_5_runtime.md)。

## 测试与成本

- V2-2B 最终自动化：`smartbuy/tests` 177/177，加入上游配置安全测试后的 CI 等价套件 178/178；Product Pack/实时索引定向套件 23/23。Ruff、Compileall、JavaScript 12/12、PowerShell AST 5/5 和 Markdown 262/262 通过，详见 [V2-2 报告](v2/v2_2_product_pack_report.md)。
- V2-3 定向离线套件 24/24；`smartbuy/tests` 201/201，加入上游安全 node 的 CI 等价套件 202/202；Ruff、Compileall、JavaScript 12/12、PowerShell 5/5、Markdown 277/277 和安全门通过。真实收尾两次合计估算 ¥0.98；含此前授权的三 Provider 只读诊断，已知估算仍低于 ¥2 阶段上限。详见 [V2-3 报告](v2/v2_3_source_search_report.md)。
- V2-4 定向 21/21；`smartbuy/tests` 222/222，加入上游配置脱敏 node 的 CI 等价套件 223/223；Ruff、Compileall、JavaScript 12/12、PowerShell 5/5、Markdown 289/289 与安全/禁止产物门通过。详见 [V2-4 报告](v2/v2_4_open_research_report.md)。
- V2-4C 将单一错误地区证据由 conflict 修正为 `unknown/region_mismatch_only`，并分离目标地区状态与跨地区比较；六组地区专项和四类双边冲突通过，PD3226G/US 仓库外证据回放仍为 6/6 matched。`smartbuy/tests` 228/228、CI 等价 229/229、V1 原始 node 94/94；本轮 API 调用 0。详见 [V2-4C 报告](v2/v2_4c_regional_evidence_report.md)。
- V2-5 定向 23/23；`smartbuy/tests` 251/251，加入上游配置脱敏 node 的 CI 等价套件 252/252；V1 原始 node 首次暴露适配属性回归 92/94，修复后 94/94，Checker/Memory/阶段 4 代表组合 30/30。Ruff、Compileall、JavaScript 12/12、PowerShell 5/5、Markdown 312/312 与安全门通过，详见 [V2-5 报告](v2/v2_5_constraint_clarification_report.md)。本轮 API 调用和费用为 0。
- 独立三模型最终验证：5 次调用、398 input + 31 output tokens，估算 0.0003243 元。
- 最终 Youtu 建库/查询：Embedding 130 input tokens，估算 0.000065 元；Reranker 160 input tokens，估算 0.000080 元。
- Youtu Agent 内部 LLM Token 尚未完整进入自研账本，精确阶段总成本记为未知；调用均为有界小样本，远低于 5 元阶段上限。

阶段 3：

- 40 条固定任务中 36 条有检索金标；Vector-only / Reranker Recall@5 为 0.8912 / 0.9838，nDCG@5 为 0.8170 / 0.9541。
- 相似型号 Top-1 错误率从 0.50 降为 0；固定阈值拒答为 0/4，是阶段 4 必须处理的已知边界。
- 最终评测 4 次查询 Embedding + 39 次 Rerank，45,266 input tokens，估算 0.022633 元；平均/P95 约 219.9/344.8ms。
- 全量建库 5,225 input tokens，估算 0.0026125 元；含小样本、一次元数据失败后的复跑和一次观测补全评测，阶段 3 总估算不超过 0.0493 元。
- 自动化：23 passed，3 条上游依赖弃用警告；`smartbuy/` 与阶段 2 核心供应商 Provider 文件 Ruff 通过。

阶段 4：

- 4 条最终 dry run 端到端 4/4；45 次模型操作，154,182 input + 4,133 output tokens，估算 0.1291333 元。
- 16 条最终全量：工具选择 16/16，正例型号召回 7/7，应拒答 9/9，多跳 8/8，Schema 16/16，端到端 15/16；平均/P95 25,900.192/40,194.556ms。
- 最终全量 147 次模型操作，478,162 input + 16,510 output tokens，估算 0.4073413 元。
- 唯一失败是 LLM 臆加显示尺寸约束；只接受用户显式给值字段后，单条回归 1/1，估算 0.023361 元。
- 已记录开发迭代估算 2.0659403 元；加一次未持久化 Token 的 HTTP smoke 后严格上界小于 2.3159403 元，低于 10 元。
- 阶段 4 提交前完整项目回归 56 passed、3 条上游依赖弃用警告；`smartbuy/` Ruff、Python compileall 与前端 JavaScript 语法检查通过。

阶段 5：

- 固定自然套件：55/55 字段、10/10 任务、12/12 不合规候选拦截、9/9 合规候选保留；Checker 平均/P95 1.332/1.994ms。
- 独立故障注入：21/21 字段、12/12 任务、12/12 拦截、unknown/conflict 6/6、unsupported 2/2、重复执行 12/12；平均/P95 0.966/1.402ms。
- 阶段 4 固定池 A/B：任务级 10/12 → 12/12，合规候选误杀 3/10 → 0/10，恢复 3 个候选；候选池 12/12 完全一致。
- 在线 dry run 4/4；首次完整 E2E 13/16，安全门完整性 16/16、Checker 平均/P95 2.014/4.975ms。三个失败原样保留；`s4-004`、`s4-007` 与最终 `s4-012` 定向回归均通过对应失败项。
- 保存的在线评测与回归累计 271 次账本调用，1,097,782 input + 26,510 output tokens，估算 0.8967852 元；Checker 本身 0 次 API、0 元。
- 提交前完整项目回归 76 passed、3 条上游依赖弃用警告；Ruff、Python compileall 和前端 JavaScript 语法检查通过。

阶段 6：

- 主实验 480 个唯一预测；首次运行/三次聚合 E2E 分别为 A 16/40、46/120，B 17/40、51/120，C 28/40、81/120，D 31/40、92/120。
- 首次 D 组硬约束任务 24/30、违规推荐 0/43、拒答 33/40；C/D 的关键结论最小金标证据覆盖均为 56/71，错型号/错地区引用均为 0。
- 首次运行平均/P95：A 1573.456/1889.912ms，B 5339.969/12200.512ms，C 27497.519/50946.717ms，D 24802.374/41327.653ms；主实验为冷运行，不与热缓存混比。
- 首次 Fixed RAG 有 10 次结构化输出解析失败；首次 C/D 各有 4 条 `resolution >= 3840x2160` 证据比较错误。修复后 4 条定向回归 D 4/4、C 1/4，且无同类异常；首次结果未覆盖。
- 故障 13/13、Memory 5/5、缓存输出一致 5/5、Checker 确定性 40/40；统一脱敏账本和四组指标 CSV 已提交。
- 可审计 API 成本下界 11.4491691 元；考虑未完整持久化 usage 的异常路径后保守估计仍小于 13 元，低于阶段 20 元上限，项目累计低于 50 元上限。
- 提交前完整项目回归 89 passed、3 条上游依赖弃用警告；不使用真实 Web Search，不宣称 GraphRAG 或生产 SLA。

阶段 2 模型错误矩阵见[阶段 2 验证记录](stage2_bailian_verification.md)，阶段 3 数据与检索证据见[阶段 3 报告](stage3_data_and_retrieval_report.md)，阶段 4 Agent 证据见[阶段 4 报告](stage4_agent_workflow_report.md)，阶段 5 安全门证据见[阶段 5 报告](stage5_constraint_verification_report.md)，阶段 6 四组主实验与韧性证据见[阶段 6 报告](stage6_evaluation_and_resilience_report.md)。

## 已知边界

- 阶段 1/2 夹具知识库仍只有一个自制文档和 2 chunks；阶段 3 正式知识库另有 12 个型号和 60 chunks。
- 阶段 6 已完成完整四组对照、核心组三次重复、统一账本、缓存和故障注入；holdout 首次增强组仍有 9/24 未完成，主要边界是证据覆盖与上游 LLM 路由/结构化输出稳定性。
- 上游供应商目录存在既有 lint 债务，本阶段只保证自研代码及三类核心 Provider 文件通过；不做无关批量格式化。
- V1 动态 Web Search 仍是 unavailable 降级接口；V2 Source Search 只发现官方 URL，默认关闭，尚无网页正文抽取、Evidence Promotion 或实时价格/库存。首批约束词表有意收窄，unsupported/ambiguous 会 fail closed。
