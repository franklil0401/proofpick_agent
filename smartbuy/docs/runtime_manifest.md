# SmartBuy Runtime Manifest

最后更新：2026-08-26
当前阶段：阶段 3 已完成，等待用户验收
运行范围：Windows 11 原生 Youtu-RAG + 阿里云百炼三模型 + SmartBuy 显示器数据/SQLite/Chroma

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

详细纳入方式见 [ADR-0001](adr/0001-vendor-youtu-rag.md)，Provider/索引决策见 [ADR-0002](adr/0002-bailian-provider-and-index-contract.md)，数据和索引版本见 [ADR-0003](adr/0003-governed-monitor-data-and-index.md)，供应商差异见根目录 [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)。

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
- API/WebUI：`127.0.0.1:8000`；MinIO API/Console：`127.0.0.1:9000` / `127.0.0.1:9001`。
- 运行数据库、向量索引、MinIO 数据和日志均在仓库外，不进入 Git。

## 模型与配置契约

| 能力 | 配置 | 当前状态 |
|---|---|---|
| LLM | `qwen-plus` | 普通、SSE 流式、Tool Calling 均通过 |
| Embedding | `text-embedding-v4`，固定 1024 维 | 批量数量、顺序、维度、语义顺序和 Youtu 建库均通过 |
| Reranker | `qwen3-rerank`，完整 `/compatible-api/v1/reranks` | 独立排序与 Youtu 二阶段排序均通过；失败可显式降级 |
| OCR / HiChunk | 关闭 | 阶段 2 文本夹具不需要 |
| Web Search | 未配置 | 不阻塞；默认基础 Agent 不加载 Serper |
| 本地模型 | 关闭 | 不作为主要在线链路 |

配置只从当前进程继承的 `Qianwen_api_key` 和 `Qianwen_workspace_id` 读取。启动脚本将其映射为子进程 `UTU_*`，不读取 Windows 注册表、不写 `.env`、不输出值。轮换 Key 后必须重启所有长运行进程。

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

## 测试与成本

- 自动化：17 passed，3 条上游依赖弃用警告。
- 静态检查：`smartbuy/` 与三类核心 Provider 文件 Ruff 通过。
- 独立三模型最终验证：5 次调用、398 input + 31 output tokens，估算 0.0003243 元。
- 最终 Youtu 建库/查询：Embedding 130 input tokens，估算 0.000065 元；Reranker 160 input tokens，估算 0.000080 元。
- Youtu Agent 内部 LLM Token 尚未完整进入自研账本，精确阶段总成本记为未知；调用均为有界小样本，远低于 5 元阶段上限。

阶段 3：

- 40 条固定任务中 36 条有检索金标；Vector-only / Reranker Recall@5 为 0.8912 / 0.9838，nDCG@5 为 0.8170 / 0.9541。
- 相似型号 Top-1 错误率从 0.50 降为 0；固定阈值拒答为 0/4，是阶段 4 必须处理的已知边界。
- 最终评测 4 次查询 Embedding + 39 次 Rerank，45,266 input tokens，估算 0.022633 元；平均/P95 约 219.9/344.8ms。
- 全量建库 5,225 input tokens，估算 0.0026125 元；含小样本、一次元数据失败后的复跑和一次观测补全评测，阶段 3 总估算不超过 0.0493 元。
- 自动化：23 passed，3 条上游依赖弃用警告；`smartbuy/` 与阶段 2 核心供应商 Provider 文件 Ruff 通过。

阶段 2 模型错误矩阵见[阶段 2 验证记录](stage2_bailian_verification.md)，阶段 3 数据与检索证据见[阶段 3 报告](stage3_data_and_retrieval_report.md)。

## 已知边界

- 阶段 1/2 夹具知识库仍只有一个自制文档和 2 chunks；阶段 3 正式知识库另有 12 个型号和 60 chunks。
- 阶段 3 已测检索 Recall/nDCG/P95；业务任务完成率、引用正确率和硬约束满足率仍须阶段 4～6 测量。
- 上游供应商目录存在既有 lint 债务，本阶段只保证自研代码及三类核心 Provider 文件通过；不做无关批量格式化。
- Web Search、Agent 中的 SQLite/Text2SQL 编排和确定性硬约束复核尚未实现；SQLite 数据库本身已可重建。
