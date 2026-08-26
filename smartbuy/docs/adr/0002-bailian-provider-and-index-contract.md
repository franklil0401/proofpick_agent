# ADR-0002：百炼 Provider 与 1024 维索引契约

- 状态：已接受
- 日期：2026-08-26
- 决策范围：阶段 2 模型 Provider、Youtu-RAG 适配和索引兼容性

## 背景

SmartBuy 使用同一个阿里云百炼 API Key 调用 `qwen-plus`、`text-embedding-v4` 和 `qwen3-rerank`，但三类接口的地址、请求和响应并不完全相同。上游 Youtu-RAG 的通用适配还存在以下不兼容：Embedding 未传维度、可能探测不适用于百炼的 `model_id`，Reranker 会把完整的 `/reranks` 地址再次拼接为错误路径，配置对象和文本预览还可能进入日志。

## 决策

1. 自研统一配置由 `smartbuy.config.BailianSettings` 承担，只读取当前进程继承的 `Qianwen_api_key` 和 `Qianwen_workspace_id`。
2. Key 在数据类中使用 `repr=False`，安全状态只允许输出 `configured/missing`；不从注册表、`.env`、源码或前端读取。
3. 三类模型分别使用 Workspace 专属接口：LLM/Embedding 使用 OpenAI-compatible base URL，Reranker 使用完整的 `/compatible-api/v1/reranks`。
4. `text-embedding-v4` 显式固定 `dimensions=1024`。返回数量、索引顺序和每条向量维度必须校验；模型、维度或预处理变化必须使用新目录重建索引。
5. Youtu-RAG 直接使用 OpenAI-compatible Embedding Provider，不访问 `/model_id`；知识库构建和检索必须共享 `VECTOR_STORE_PATH`。
6. `qwen3-rerank` 从顶层 `results` 解析，完整 `/rerank` 或 `/reranks` 地址原样使用。失败时返回原向量顺序并显式标记 `rerank_degraded`，不得伪装为重排成功。
7. 401/403 不重试；429、5xx、连接错误和超时最多在初次请求后重试 2 次，指数退避并加入小幅抖动。
8. 用量账本只保存操作类型、模型、状态、尝试次数、延迟、Token、条目数和估算费用，不保存请求/响应正文、Authorization 或 Key。
9. 启动脚本只读取继承后的 Process 环境；Key 轮换后必须重启终端、IDE、服务和智能体进程。

## 影响

- 索引格式形成明确契约：`text-embedding-v4` + 1024 维 + 当前切分策略。
- 供应商目录需保留少量兼容和安全补丁，具体文件记录在根目录 [THIRD_PARTY_NOTICES.md](../../../THIRD_PARTY_NOTICES.md)。
- Reranker 故障不会导致 KB Search 整体失败，但输出必须显示降级状态。
- Embedding 失败或维度错误会阻断建库，避免产生不可检索或混维索引。
- Web Search 没有凭据时继续使用基础 Chat 或 KB 主链路，不在默认启动时加载 Serper。

## 验证

验证证据、Token、延迟、费用和故障矩阵见[阶段 2 验证记录](../stage2_bailian_verification.md)。
