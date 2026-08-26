# SmartBuy Research Agent

多源消费决策研究 Agent：在 Youtu-RAG 基础上构建可追踪、可评测、可执行硬约束复核的消费决策系统。

> 当前状态：**阶段 2 已完成，等待用户验收**。Windows 上的百炼三模型、1024 维文本建库、KB Search、二阶段 Rerank、有限重试和显式降级已经跑通；真实显示器数据与 SmartBuy 消费决策工作流仍在计划中。

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
- 已有 17 项阶段相关测试通过；自研代码与三类核心 Provider 文件 Ruff 检查通过。

### 尚未实现或尚未验证

- 显示器数据 Schema、合规数据集、SQLite、知识库、评测集和正式演示数据。
- KB Search + Text2SQL 的 Agentic 编排、确定性硬约束复核和消费决策报告。
- Web Search 凭据与动态价格/库存链路；无凭据不阻塞阶段 1～3。
- GraphRAG 不属于 MVP 或阶段 1～5 默认任务，不得视为已实现能力。

## 上游原生能力与本项目贡献

| 范围 | 内容 |
|---|---|
| Youtu-RAG 上游 | FastAPI/WebUI、文件管理、知识库框架、Agent 配置、检索与监控基础设施 |
| SmartBuy 阶段 1 新增 | 固定版本 subtree、Windows 云 API 启动脚本、运行清单、许可证/差异记录、阶段测试夹具、配置接口凭据脱敏及回归测试 |
| SmartBuy 阶段 2 新增 | 统一百炼配置与 Provider、1024 维索引契约、用量账本、Youtu Embedding/Reranker 适配、有限重试/降级和日志安全回归 |
| SmartBuy 后续计划 | 消费数据、KB/SQL 工具编排、硬约束复核、统一评测和演示界面 |

供应商目录差异见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，纳入决策见 [ADR-0001](smartbuy/docs/adr/0001-vendor-youtu-rag.md)。

## 技术路线

当前主线是 Agentic RAG，不是 GraphRAG：

```text
用户需求与偏好
      ↓
Youtu-RAG WebUI / FastAPI / SSE
      ↓
Agent 选择与多源工具编排（计划）
      ├─ KB Search：官方文档事实
      ├─ Text2SQL：SQLite 参数、硬约束与计算
      └─ Web Search：当前价格、库存和近期变化（有凭据时）
      ↓
向量召回 → qwen3-rerank 二阶段重排（阶段 2 已验证）→ 证据融合（计划）
      ↓
代码/SQL 确定性硬约束复核（计划）
      ↓
推荐、淘汰原因、证据、冲突、未知项和降级状态
```

## 技术栈

| 技术 | 当前状态 |
|---|---|
| Python 3.12、uv | 阶段 1 已验证 |
| Youtu-RAG / Youtu-Agent | 固定上游版本已纳入；基线已验证 |
| FastAPI、原生 WebUI、Monitor | 阶段 1 已验证 |
| MinIO、SQLite、Chroma、FAISS | MinIO/SQLite 基线与 Chroma 1024 维测试索引已运行；FAISS 未作为当前主链路 |
| 百炼 `qwen-plus` | 普通、流式、Tool Calling 已验证 |
| 百炼 `text-embedding-v4`（1024 维） | 批量、契约校验、建库与 KB Search 已验证 |
| 百炼 `qwen3-rerank` | 独立和 Youtu 二阶段排序、有限重试与降级已验证 |
| Pytest 与项目 Eval Runner | 阶段相关 17 tests passed；业务评测集仍在计划中 |

## 快速开始（阶段 2 已验证范围）

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

当前可验证上传、文件管理、知识库创建/关联、基础 Chat、文本建库、KB Search 和二阶段 Rerank。这里只使用一个自制文档，不能据此宣称检索质量达标。完整版本、路径和证据见 [Runtime Manifest](smartbuy/docs/runtime_manifest.md) 与[阶段 2 验证记录](smartbuy/docs/stage2_bailian_verification.md)。

### 4. 有界 Provider 验证（会产生少量费用）

```powershell
uv run --project vendor/youtu-rag python -m smartbuy.scripts.verify_bailian_stage2
```

该脚本只输出配置状态、计数、维度、Token、延迟和估算成本，不输出 Key 或模型正文。它不是默认 CI 测试；运行前应确认阶段预算。

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

结果：`17 passed`，另有 3 条上游依赖弃用警告。阶段 2 真实调用、错误矩阵、延迟和成本见[验证记录](smartbuy/docs/stage2_bailian_verification.md)。业务评测仍为计划：至少 30 条任务比较 Direct LLM、Fixed RAG、Agentic RAG 和 Agentic RAG + Constraint Check，覆盖 Recall@K、nDCG/MRR、硬约束满足率、引用正确率、无依据结论、成功率、延迟、成本和降级可用性。建议目标不是已取得结果，详见[开发指南验收指标](DEVELOPMENT_GUIDE.md#9-验收指标)。

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
