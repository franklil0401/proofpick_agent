# SmartBuy Research Agent

多源消费决策研究 Agent：在 Youtu-RAG 基础上构建可追踪、可评测、可执行硬约束复核的消费决策系统。

> 当前状态：**阶段 5 已完成，等待用户验收**。在阶段 4 有界 Agent 后新增不可由 LLM 绕过的确定性 Constraint Checker：自然硬约束 55/55 字段、10/10 任务，故障注入 12/12 候选拦截，unknown/conflict、unsupported 与重复执行均通过阻断门槛。首次在线 16 条 E2E 为 13/16，安全门完整性 16/16；3 个失败均保留并完成定向回归。

## 项目场景

SmartBuy 面向参数复杂、资料分散且信息可能过期的真实消费选择。MVP 聚焦显示器：用户给出预算、用途、尺寸、接口、面板等要求，系统计划组合官方资料知识库、SQLite 参数查询和可选动态网页信息，输出候选、淘汰原因、证据、冲突、未知项和降级状态。

目标用户是希望减少手工查证的普通消费者、需要严谨比较型号的数码爱好者，以及希望复用长期偏好的重复使用者。本项目用于展示一个真实 Agent 工程，不是秋招流程辅助工具。

## 当前能力

### 已实现并验证

- 将 Youtu-RAG 上游 Commit `ce5c3010ff2e2a1c3e657ebcba14481ac5a2b066` 以 `git subtree --squash` 固定纳入 `vendor/youtu-rag/`。
- 在 Windows 11、Python 3.12.3、uv 0.12.3 上完成 `uv sync --frozen`，锁文件无需修改。
- 本机回环地址启动 MinIO、FastAPI、Youtu-RAG WebUI 和 `/monitor`，相关入口均返回 HTTP 200。
- 上传自制 Markdown 测试文件、查看文件列表、创建知识库并关联文件。
- `qwen-plus` 普通调用、SSE 流式和 Tool Calling 均通过有界真实调用。
- `text-embedding-v4` 批量返回数量与顺序正确，每条严格为 1024 维。
- 阶段 1 自制文档已重建为 2 chunks；API 状态与目标 Chroma collection 实际计数一致。
- KB Search 能召回夹具事实，`qwen3-rerank` 在向量召回后完成二阶段排序；失败时可显式回退向量顺序。
- 401 不重试；429、5xx 和超时有限退避；错误 Embedding 维度阻断索引写入。
- 使用无 Web Search 工具的基础 Agent，缺少 Serper 凭据不影响默认启动、Chat 或 KB 主链路。
- OCR、HiChunk、本地模型和 Memory 在当前文本基线中保持关闭。
- 修复上游配置接口返回解析后凭据的风险；递归脱敏单测和真实接口回归通过。
- 修复上游 Toolkit 配置日志泄露、Windows UTF-8、向量路径分裂和 `force_rebuild` 仍被跳过的问题。
- 建立 12 型号、4 品牌、16 来源、4 条价格观察、180 条字段级证据和 12 张自制事实卡的显示器数据 v1。
- SQLite 可由源 JSON 原子重建；连续重建逻辑哈希一致，0 外键违规且 `integrity=ok`，运行数据库不进入 Git。
- 正式知识库构建状态 `completed`，60 文档/60 chunks 与 Chroma 一致；每块保留型号、地区、来源、时间、切分和 Embedding 契约元数据。
- 40 条检索任务中，Vector-only / Reranker Recall@5 为 0.8912 / 0.9838，nDCG@5 为 0.8170 / 0.9541；相似型号 Top-1 错误率从 50% 降至 0%。
- Reranker 强制降级保留向量结果；固定阈值无证据拒答为 0/4，已明确记录为后续边界。
- 实现最多 8 步、12 次工具调用的 qwen-plus Tool Calling 循环；依赖门禁保证组合任务按 SQL → KB → Evidence 观察链推进，轨迹不记录隐藏思维链。
- Text2SQL 使用只读 SQLite、单 SELECT、表列白名单、SQLite authorizer、超时与最大行数；非法 SQL 可受控模板降级，禁止无条件全表降级。
- Evidence Check 按字段证据、型号/地区、时效和冲突输出 `matched/not_matched/unknown/conflict`，不再以固定 Reranker 阈值拒答。
- Web Search 标准工具当前返回 `unavailable`；无凭据时 KB + SQLite 主链路仍可完成稳定 Demo，未宣称动态搜索已实现。
- 短期会话约束和候选可继承/覆盖；长期偏好须明确确认，支持查看、覆盖、删除和关闭，且拒绝保存价格、库存和商品事实。
- 结构化报告经 Pydantic Schema 校验并渲染 Markdown；WebUI 展示工具卡片，`/monitor` 展示脱敏运行摘要。
- 最终 16 条 E2E：工具选择 16/16、正例型号召回 7/7、9 条应拒答样本 9/9、多跳 8/8、Schema 16/16、端到端 15/16；修复后失败用例独立回归 1/1。
- 建立带来源 `ConstraintSet`：当前输入 > 会话确认 > 已启用长期偏好 > 系统默认；模型推测、工具结果和商品资料不能反向成为用户硬约束。
- Checker 从 SQL、KB 和 Evidence 阶段累计的完整候选池读取只读 SQLite 与同地区证据，逐字段输出 `passed/failed/unknown/conflict`；只有全部受支持硬约束通过才可推荐。
- LLM 只能在完整合规集合内按软偏好排序；集合外新增项会被删除，遗漏合规项会由代码补回。SSE/Monitor 已展示 Checker 版本、字段状态、证据和降级。
- 阶段 5 固定套件：自然用例 55/55 字段、10/10 任务；故障注入 21/21 字段、12/12 任务、12/12 拦截；合规候选误杀 0，Checker 不调用 API。

### 尚未实现或尚未验证

- 真实 Web Search 与动态价格/库存补充；当前没有凭据，只验证 unavailable/degraded 接口。
- 阶段 6 的 Direct LLM / Fixed RAG / Agentic RAG / + Constraint Check 四组完整消融与重复运行。
- GraphRAG 不属于 MVP 或阶段 1～5 默认任务，不得视为已实现能力。

## 上游原生能力与本项目贡献

| 范围 | 内容 |
|---|---|
| Youtu-RAG 上游 | FastAPI/WebUI、文件管理、知识库框架、Agent 配置、检索与监控基础设施 |
| SmartBuy 阶段 1 新增 | 固定版本 subtree、Windows 云 API 启动脚本、运行清单、许可证/差异记录、阶段测试夹具、配置接口凭据脱敏及回归测试 |
| SmartBuy 阶段 2 新增 | 统一百炼配置与 Provider、1024 维索引契约、用量账本、Youtu Embedding/Reranker 适配、有限重试/降级和日志安全回归 |
| SmartBuy 阶段 3 新增 | 显示器数据治理、四实体 Schema、可重建 SQLite、自制事实卡、正式 Chroma 知识库、40 条检索集和 Vector/Reranker 基线 |
| SmartBuy 阶段 4 新增 | 有界 ReAct、KB/只读 SQL/Evidence/Web 降级工具、分层 Memory、Schema 报告、SSE/Monitor 与 16 条 E2E |
| SmartBuy 阶段 5 新增 | 来源门禁、完整候选池、只读确定性 Checker、软排序护栏、SSE/Monitor 字段审计、自然/故障注入消融 |
| SmartBuy 后续计划 | 阶段 6 四组完整消融、重复运行与稳定性优化；阶段 7 发布演示整理 |

供应商目录差异见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，纳入决策见 [ADR-0001](smartbuy/docs/adr/0001-vendor-youtu-rag.md)。

## 技术路线

当前主线是 Agentic RAG，不是 GraphRAG：

```text
用户需求与偏好
      ↓
Youtu-RAG WebUI / FastAPI / SSE
      ↓
有界 Agent 规划、工具观察与继续规划（阶段 4 已实现）
      ├─ KB Search：官方文档事实
      ├─ Text2SQL：SQLite 参数、硬约束与计算
      └─ Web Search：当前价格、库存和近期变化（有凭据时）
      ↓
向量召回 → qwen3-rerank 二阶段重排 → 字段 Evidence Check（阶段 4 已实现）
      ↓
最终确定性 Constraint Checker（阶段 5 已实现）
      ↓
推荐、淘汰原因、证据、冲突、未知项和降级状态
```

## 技术栈

| 技术 | 当前状态 |
|---|---|
| Python 3.12、uv | 阶段 1 已验证 |
| Youtu-RAG / Youtu-Agent | 固定上游版本已纳入；基线已验证 |
| FastAPI、原生 WebUI、Monitor | 阶段 1 已验证 |
| MinIO、SQLite、Chroma、FAISS | MinIO 基线已运行；SQLite 可重建；Chroma 60-chunk 正式索引已验证；FAISS 未作为当前主链路 |
| 百炼 `qwen-plus` | 普通、流式、Tool Calling 已验证 |
| 百炼 `text-embedding-v4`（1024 维） | 批量、契约校验、建库与 KB Search 已验证 |
| 百炼 `qwen3-rerank` | 独立和 Youtu 二阶段排序、有限重试与降级已验证 |
| Pytest 与项目 Eval Runner | 数据/索引、SQL/Evidence/Memory/Agent、Constraint Checker、API/SSE 回归已加入；检索、Agent、固定池和故障注入均有真实结果 |

## 快速开始（阶段 5 已验证范围）

### 1. 前置条件

- Windows 11、Python 3.12、uv。
- 从 MinIO 官方发行渠道取得 Windows Server 二进制，放在短 ASCII 仓库外路径，例如 `C:/ai/minio/minio.exe`。
- 在 Windows 系统环境变量中配置 `Qianwen_api_key` 和 `Qianwen_workspace_id`，然后重启终端/IDE/服务，使新进程继承变量。正式程序只通过 `os.getenv` 读取当前进程；不要打印值，也不要创建真实 `.env`。

### 2. 同步依赖

```powershell
Set-Location vendor/youtu-rag
uv sync --frozen
Set-Location ../..
```

该命令已在目标主机验证。若 `uv.lock` 被意外修改，应先查明原因，不要把非必要锁文件变化混入阶段提交。

### 3. 启动本地服务

MinIO 和 Youtu-RAG 必须使用一致的当前进程 MinIO 凭据。真实值只放在本地进程环境，不写入仓库、脚本或命令示例；开发服务只绑定 `127.0.0.1`。

```powershell
# 在当前 PowerShell 中安全设置 MINIO_ROOT_USER、MINIO_ROOT_PASSWORD、
# MINIO_ACCESS_KEY、MINIO_SECRET_KEY 后，启动仓库外 MinIO Server。
# 随后在继承同一环境的终端运行：
./smartbuy/scripts/start_youtu_rag.ps1
```

阶段 2 验证入口：

- WebUI：`http://127.0.0.1:8000/`
- 健康检查：`http://127.0.0.1:8000/health`
- Monitor：`http://127.0.0.1:8000/monitor`
- MinIO Console：`http://127.0.0.1:9001/`

阶段 2 服务链路可验证上传、文件管理、知识库创建/关联、基础 Chat、文本建库、KB Search 和二阶段 Rerank；该服务冒烟仍只使用一个自制文档。阶段 3 的检索质量由独立 12 型号/40 任务语料测量，不能把两套证据混为一谈。完整版本和路径见 [Runtime Manifest](smartbuy/docs/runtime_manifest.md)。

聊天页勾选 **SmartBuy** 后会调用 `/api/smartbuy/chat`，在现有工具卡片中展示脱敏步骤，并在最终卡片渲染结构化 Markdown 报告。Memory 开关只控制按需召回已确认的长期偏好；不会保存本轮价格、库存或模型推测。

### 4. 有界 Provider 验证（会产生少量费用）

```powershell
uv run --project vendor/youtu-rag python -m smartbuy.scripts.verify_bailian_stage2
```

该脚本只输出配置状态、计数、维度、Token、延迟和估算成本，不输出 Key 或模型正文。它不是默认 CI 测试；运行前应确认阶段预算。

### 5. 重建阶段 3 数据与 SQLite（离线）

```powershell
python -m smartbuy.scripts.build_stage3_data
python -m smartbuy.scripts.validate_stage3_data
python -m smartbuy.db.build_database --output C:\ai\smartbuy-stage3\smartbuy_monitors_v1.sqlite
```

命令从版本化源数据生成 processed JSONL、12 张事实卡和工作区外 SQLite。当前应得到 products 12、prices 4、sources 16、evidence 180，且连续重建逻辑哈希一致。数据范围和许可边界见[数据卡](smartbuy/docs/data_card.md)。

### 6. 重建正式知识库与运行检索评测（会产生少量费用）

```powershell
$env:PYTHONPATH="$PWD;$PWD\vendor\youtu-rag"
vendor\youtu-rag\.venv\Scripts\python.exe -m smartbuy.scripts.build_stage3_index --mode pilot
vendor\youtu-rag\.venv\Scripts\python.exe -m smartbuy.scripts.build_stage3_index --mode full
vendor\youtu-rag\.venv\Scripts\python.exe -m smartbuy.scripts.verify_stage3_index
vendor\youtu-rag\.venv\Scripts\python.exe -m smartbuy.eval.run_retrieval_eval
```

先跑 3 个型号的小样本，再全量构建；输入未变化时不要重复全量向量化。真实索引和评测结果见[阶段 3 报告](smartbuy/docs/stage3_data_and_retrieval_report.md)。Chroma 默认位于 `C:/ai/smartbuy-stage3/`，不进入 Git。

### 7. 运行阶段 4 Agent 评测（会产生费用）

```powershell
$env:PYTHONPATH="$PWD;$PWD\vendor\youtu-rag"
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_stage4_eval --dry-run
# 只有 dry run 通过且预算允许时再运行：
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_stage4_eval
```

脚本先支持 4 条 dry run，再运行 16 条完整集合；每任务有步骤、工具调用和成本硬上限。真实指标、失败样本和成本见[阶段 4 技术报告](smartbuy/docs/stage4_agent_workflow_report.md)。

### 8. 运行阶段 5 Constraint Checker 评测

```powershell
$env:PYTHONPATH="$PWD;$PWD\vendor\youtu-rag"

# 纯本地：固定候选池、自然硬约束与独立故障注入，不调用 API
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_stage5_eval --fixed

# 在线命令会产生费用；只有本地门槛和 4 条 dry run 通过后才运行 full
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_stage5_eval --dry-run
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_stage5_eval --full
```

首次完整在线结果及后续定向回归分开保存，不用重跑覆盖失败。精确分母、延迟、成本和已知边界见[阶段 5 技术报告](smartbuy/docs/stage5_constraint_verification_report.md)。

## Windows 环境

| 项目 | 配置 |
|---|---|
| 操作系统 | Windows 11 |
| Python | 3.12.3 |
| CPU | Intel i5-10400F |
| 内存 | 32 GB |
| GPU | GTX 960 2 GB |

GTX 960 2 GB 不作为本地大模型或 Embedding 的主要在线推理设备，云端 API 是主方案。本地模型仅可作为后续实验或明确降级。仓库依赖可位于 `vendor/youtu-rag/.venv/`，运行数据库、对象存储和索引统一放在仓库外短 ASCII 路径。

## 环境变量

仓库只记录变量名，不保存真实值：

| 变量名 | 用途 | 规则 |
|---|---|---|
| `Qianwen_api_key` | 百炼三模型共用 API Key | 敏感；仅从继承后的 Process 环境读取，禁止输出或持久化 |
| `Qianwen_workspace_id` | 百炼业务空间 ID | 配置项；由统一配置层读取，不在业务代码散落硬编码 |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | 本地 MinIO Server | 仅本地进程环境；不得提交 |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | Youtu-RAG 访问本地 MinIO | 与 Server 当前进程配置一致；不得提交 |

启动脚本在子进程中映射 `UTU_LLM_*`、`UTU_EMBEDDING_*` 和 `UTU_RERANKER_*`，不会写 `.env`。Embedding 模型、维度或预处理发生变化后必须建立新索引并全量重建。

## 测试与评测

当前阶段相关回归命令：

```powershell
uv run --project vendor/youtu-rag --group dev python -m pytest `
  smartbuy/tests/unit `
  smartbuy/tests/integration/test_youtu_bailian_adapters.py `
  vendor/youtu-rag/tests/rag/api/test_config_security.py -q
```

阶段 5 新增来源优先级、取消记忆、模型臆加/软转硬、别名与边界、null/conflict、错误/重复型号、Prompt 注入、完整池恢复、Checker 报告与 SSE/Monitor 回归。提交前完整回归为 `76 passed`、3 条上游弃用警告；`smartbuy/` Ruff、Python 编译和前端 JavaScript 语法检查通过。详见[阶段 5 技术报告](smartbuy/docs/stage5_constraint_verification_report.md)。

阶段 3 的 40 条任务只评估检索；阶段 4 的 16 条任务评估 Agent；阶段 5 的自然/故障注入固定套件评估硬约束安全门。阶段 5 首次完整在线 E2E 为 13/16，安全门完整性 16/16；三个失败保留并逐项定向回归。阶段 6 仍需完成 Direct LLM、Fixed RAG、Agentic RAG 和 Agentic RAG + Constraint Check 四组完整、重复运行对照。

## 文档导航

- [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)：主要开发依据、阶段计划、验收指标和 DoD。
- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)：当前真实项目结构事实来源。
- [FINAL 开发交接文档](FINAL_多源消费决策研究Agent开发交接总文档.md)：原始范围和总体调研结论。
- [阿里云百炼 API 调用说明](阿里云百炼API-Key调用与Youtu-RAG接入说明.md)：百炼安全、端点与适配规则。
- [Runtime Manifest](smartbuy/docs/runtime_manifest.md)：固定版本、依赖和运行状态。
- [阶段 1 冒烟记录](smartbuy/docs/stage1_smoke_test.md)：通过项、边界和安全修复。
- [ADR-0001](smartbuy/docs/adr/0001-vendor-youtu-rag.md)：Youtu-RAG 纳入决策。
- [阶段 2 验证记录](smartbuy/docs/stage2_bailian_verification.md)：三模型、建库、KB Search、错误矩阵与成本。
- [ADR-0002](smartbuy/docs/adr/0002-bailian-provider-and-index-contract.md)：百炼 Provider 与索引契约。
- [阶段 3 数据卡](smartbuy/docs/data_card.md)：数据范围、字段、来源、缺失、许可和质量检查。
- [阶段 3 验证报告](smartbuy/docs/stage3_data_and_retrieval_report.md)：SQLite、知识库、检索指标、成本和失败案例。
- [ADR-0003](smartbuy/docs/adr/0003-governed-monitor-data-and-index.md)：数据治理、Schema 和索引版本决策。
- [阶段 4 技术报告](smartbuy/docs/stage4_agent_workflow_report.md)：ReAct、工具、Memory、E2E、成本、失败与服务冒烟。
- [ADR-0004](smartbuy/docs/adr/0004-bounded-react-evidence-and-memory.md)：有界执行、SQL/Evidence、轨迹和 Memory 决策。
- [阶段 5 技术报告](smartbuy/docs/stage5_constraint_verification_report.md)：固定池消融、故障注入、在线 E2E、Checker 延迟与成本。
- [ADR-0005](smartbuy/docs/adr/0005-deterministic-constraint-gate.md)：来源门禁、完整候选池、只读复核和 LLM 权限边界。
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)：上游归属、许可和供应商目录差异。

## 上游参考与致谢

项目基于腾讯开源 [TencentCloudADP/youtu-rag](https://github.com/TencentCloudADP/youtu-rag)，并参考 [TencentCloudADP/youtu-agent](https://github.com/TencentCloudADP/youtu-agent)。感谢上游维护者。上游能力与本项目贡献必须保持可追溯边界。

## 许可证

本项目自行开发的代码采用 [MIT License](LICENSE)。Youtu-RAG 保留其[上游 MIT License](vendor/youtu-rag/LICENSE)。代码许可证不自动覆盖数据；每份数据必须单独记录来源、获取时间、哈希和再分发许可。

## 安全说明

- 绝不提交或展示 API Key、Authorization 请求头、真实 `.env` 或其他凭据。
- 配置接口必须在返回前递归脱敏；不得把解析后的原始配置写入日志或测试快照。
- 模型请求只由后端发起，密钥不得进入前端 JavaScript。
- Python Executor 不是安全沙箱，只能本地处理可信文件，不能暴露公网。
- 不提交受限 PDF、个人隐私、登录后内容、运行数据库、模型权重、缓存或未经检查的日志。
- 怀疑凭据泄露时立即停止服务、轮换凭据、扫描工作区与 Git，并只记录不含原值的处置事实。
