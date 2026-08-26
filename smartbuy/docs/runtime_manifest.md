# SmartBuy 阶段 1 Runtime Manifest

最后更新：2026-08-26
运行范围：Windows 11 原生 Youtu-RAG 基线，不含阶段 2 Embedding/Reranker Provider 适配

## 代码与纳入方式

| 项目 | 固定值 |
|---|---|
| 当前项目分支 | `main` |
| Youtu-RAG 上游仓库 | <https://github.com/TencentCloudADP/youtu-rag> |
| Youtu-RAG Commit | `ce5c3010ff2e2a1c3e657ebcba14481ac5a2b066` |
| 安全清理派生 Commit | `87af8dcf679f82779257c32c262d34285b6b9903`；仅处理 GitHub 对模型类名的 Secret 误报 |
| 纳入日期/方式 | 2026-08-26，`git subtree --squash` |
| 供应商目录 | `vendor/youtu-rag/` |
| 上游许可证 | MIT，见 `vendor/youtu-rag/LICENSE` |
| `uv.lock` SHA-256 | `726A4CC25B64C0B0C98DBADB51218F86433C7C424B52D40C88FE0910B1BFB659` |

详细决策见 [ADR-0001](adr/0001-vendor-youtu-rag.md)，差异与归属见根目录 [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)。

## 主机与关键版本

| 项目 | 阶段 1 实测值 |
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

MinIO 二进制与运行数据均位于仓库外的 `C:/ai/`，不会提交到 Git。

## 依赖与运行路径

- 依赖同步：在 `vendor/youtu-rag/` 执行 `uv sync --frozen`，成功且未修改 `uv.lock`，实测约 163.79 秒。
- 关键导入：`fastapi`、`chromadb`、`faiss`、`pandas`、`openpyxl`、`minio` 均成功，实测约 31.58 秒。
- 虚拟环境：`vendor/youtu-rag/.venv/`，由 Git 忽略。
- MinIO Server：`C:/ai/minio/minio.exe`。
- MinIO 数据：`C:/ai/minio-data/`。
- Youtu-RAG 运行数据：`C:/ai/youtu-rag-runtime/`。
- API/WebUI：`127.0.0.1:8000`，仅绑定本机回环地址。
- MinIO API/Console：`127.0.0.1:9000` / `127.0.0.1:9001`，仅本机访问。

## 模型与环境配置状态

| 能力 | 配置 | 阶段 1 状态 |
|---|---|---|
| LLM | `qwen-plus` | 用户先前最小调用成功；阶段 1 基础 Chat 使用轮换后的系统 Key 再次返回 200 |
| Embedding | `text-embedding-v4`，计划固定 1024 维 | **未真实调用、未验证、未建索引**；留待阶段 2 |
| Reranker | `qwen3-rerank` | 用户先前最小调用成功；阶段 1 配置关闭，Youtu-RAG 适配留待阶段 2 |
| OCR | 关闭 | 文件上传状态为 `ocr_skipped` |
| HiChunk | 关闭 | 文件上传状态为 `chunk_skipped` |
| 本地模型 | 关闭 | 不作为在线主链路 |

启动脚本 [start_youtu_rag.ps1](../scripts/start_youtu_rag.ps1)只从 Windows `Machine`/`User` 持久化作用域读取 `Qianwen_api_key` 与 `Qianwen_workspace_id`，并只在子进程环境映射为 `UTU_*`。特意不读取父进程 `Process` 作用域，避免密钥轮换后复用陈旧值。脚本不写 `.env`，也不输出变量值。

## 阶段 1 服务结果

- WebUI `/`、`/health`、`/monitor`：HTTP 200。
- Markdown 文本上传与文件管理：通过。
- 知识库创建与文件关联：通过；文件保持 `pending`、0 chunks。
- 基础 Chat：HTTP 200，约 2.081 秒，有非空回答。
- KB Build / KB Search：未执行；依赖阶段 2 完成 Embedding API、1024 维和索引元数据验证。
- 配置接口：凭据字段返回 `<redacted>`；安全回归测试通过。

## API 调用记录

| 模型 | 阶段 1 用户级操作次数 | Token | 估算成本 | 测试目的 |
|---|---:|---:|---:|---|
| `qwen-plus` | 2（上传元数据提取、基础 Chat） | 上游阶段 1 响应未提供，未知 | 未建立可靠 Token 账本，未知 | 验证文件链路和最小 Chat |
| `text-embedding-v4` | 0 | 0 | 0 | 阶段 2 再验证 |
| `qwen3-rerank` | 0 | 0 | 0 | 阶段 1 主动关闭；用户此前独立测试的 106 tokens 不计入阶段 1 |

“用户级操作次数”不等同于底层 HTTP 重试次数；当前未发现重试证据。阶段 2 必须新增不含请求正文和凭据的调用/Token/成本账本，预算上限为 5 元。未知值不得伪造成 0。

完整证据、降级边界和安全事件处理见 [阶段 1 冒烟记录](stage1_smoke_test.md)。
