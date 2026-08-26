# 第三方软件声明

最后更新：2026-08-26（阶段 2）

## Youtu-RAG

- 项目：TencentCloudADP/youtu-rag
- 上游仓库：<https://github.com/TencentCloudADP/youtu-rag>
- 固定上游 Commit：`ce5c3010ff2e2a1c3e657ebcba14481ac5a2b066`
- 安全清理派生 Commit：`87af8dcf679f82779257c32c262d34285b6b9903`（其唯一父提交为上述固定上游 Commit）
- 纳入日期：2026-08-26
- 纳入方式：`git subtree --squash`，目录为 `vendor/youtu-rag/`
- 许可证：MIT License
- 上游许可证原文：[vendor/youtu-rag/LICENSE](vendor/youtu-rag/LICENSE)

Youtu-RAG 的版权归原权利人所有。本项目根目录 [LICENSE](LICENSE) 适用于本项目自行开发的代码；第三方目录继续受其自身许可证约束。数据不自动适用代码许可证，数据来源和再分发许可需单独记录。

### 本项目对供应商目录的阶段 1 修改

为建立 Windows 云 API 基线及修复凭据响应风险，本项目只修改/新增了下列上游目录文件：

| 文件 | 变更原因 |
|---|---|
| `vendor/youtu-rag/configs/rag/default.yaml` | Embedding 切换为 API 配置并从进程环境引用 Key；阶段 1 关闭 Reranker，避免在 Provider 适配前误调用 |
| `vendor/youtu-rag/configs/rag/file_management.yaml` | 关闭阶段 1 非必要 OCR；HiChunk 保持关闭 |
| `vendor/youtu-rag/utu/rag/api/routes/config.py` | 配置接口返回前执行递归脱敏 |
| `vendor/youtu-rag/utu/rag/api/utils/security.py` | 新增通用凭据字段脱敏函数 |
| `vendor/youtu-rag/tests/rag/api/test_config_security.py` | 使用虚构值验证递归脱敏及不修改原对象 |
| `vendor/youtu-rag/docs/content/docs/en/hichunk/deploying-locally.mdx` | 将同一 Python 类名拆成相邻字符串字面量，保持示例语义并避开 GitHub 对模型类名的 Mistral Key 误报 |
| `vendor/youtu-rag/docs/content/docs/zh/hichunk/deploying-locally.mdx` | 与英文说明做相同的无语义安全清理 |

其余 SmartBuy 场景代码、启动脚本、文档、数据和评测代码放在 `smartbuy/` 或仓库根目录，不与上游原生能力混写。后续若继续修改 `vendor/youtu-rag/`，必须同步更新本声明和[上游纳入 ADR](smartbuy/docs/adr/0001-vendor-youtu-rag.md)。

### 本项目对供应商目录的阶段 2 修改

| 文件 | 变更原因 |
|---|---|
| `vendor/youtu-rag/configs/rag/default.yaml` | 固定百炼 Embedding 1024 维和 OpenAI backend，启用 OpenAI-compatible Reranker |
| `vendor/youtu-rag/configs/rag/rag_tools/kb_search.yaml` | KB Search 改用百炼 Embedding/Reranker，避免本地 `/model_id` 与 Jina 路径 |
| `vendor/youtu-rag/utu/agents/simple_agent.py` | 工具配置日志只记录字段名，防止解析后的 Key 进入日志 |
| `vendor/youtu-rag/utu/rag/api/config.py` | 默认启动无 Web Search 的基础 Agent，缺少 Serper 时保持可用 |
| `vendor/youtu-rag/utu/rag/api/kb_config_routes.py` | 建库继承仓库外向量/SQLite 路径，并停止记录数据库密码值 |
| `vendor/youtu-rag/utu/rag/api/routes/chat.py` | Chat 日志不再记录查询正文预览 |
| `vendor/youtu-rag/utu/rag/embeddings/factory.py` | 从环境传递显式 Embedding 维度 |
| `vendor/youtu-rag/utu/rag/embeddings/openai_embedder.py` | 传递/校验 1024 维、验证数量与顺序、移除文本预览、限制重试并记录脱敏用量 |
| `vendor/youtu-rag/utu/rag/knowledge_builder/agent.py` | 将 `force_rebuild` 传到单源任务，避免第二层增量判断错误跳过 |
| `vendor/youtu-rag/utu/rag/knowledge_builder/config_analyzer.py` | 修复 storage config 参数引用并优先使用运行时存储路径 |
| `vendor/youtu-rag/utu/rag/rag_tools/base_toolkit.py` | 配置日志脱敏并把维度传入 Embedder |
| `vendor/youtu-rag/utu/rag/rag_tools/kb_search_toolkit.py` | 修复 `top_n/top_k` 参数错误，输出 Reranker 显式降级状态并移除查询预览日志 |
| `vendor/youtu-rag/utu/rag/rerankers/openai_reranker.py` | 支持完整 `/reranks`、顶层 `results`、`instruct`、有限重试、用量统计和向量降级标记 |
| `vendor/youtu-rag/utu/utils/path.py` | YAML/JSON 显式 UTF-8 读取，修复 Windows GBK 默认编码失败 |

阶段 2 的设计与回归证据见 [ADR-0002](smartbuy/docs/adr/0002-bailian-provider-and-index-contract.md) 和[阶段 2 验证记录](smartbuy/docs/stage2_bailian_verification.md)。这些修改保持通用 Youtu-RAG 主体结构不变；后续上游更新时需逐项复核是否已由上游等价修复。

## 本地开发依赖

阶段 1 在本机使用 MinIO Server 作为对象存储。MinIO 二进制和运行数据位于仓库外的 `C:/ai/`，未随本仓库分发；其许可证与使用条款以 MinIO 官方发行内容为准。
