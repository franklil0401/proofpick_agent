# 阶段 2：阿里云百炼 Provider 与 Youtu-RAG 集成验证

- 日期：2026-08-26
- 主机：Windows 11、Python 3.12.3、uv 0.12.3
- 范围：`qwen-plus`、`text-embedding-v4`、`qwen3-rerank`、Youtu-RAG 建库/检索/二阶段排序
- 测试数据：[stage1_baseline.md](../tests/fixtures/stage1_baseline.md)，自制且不含隐私
- 成本上限：5 元；本阶段只执行有界小样本调用

## 结果摘要

| 检查项 | 结果 | 证据 |
|---|---|---|
| 统一配置 | 通过 | 两个变量只报告 `configured`；Key 不进入 repr、磁盘配置或前端 |
| `qwen-plus` 普通调用 | 通过 | HTTP 成功；12 input + 1 output tokens；约 351.5 ms |
| `qwen-plus` SSE 流式 | 通过 | 9 个 SSE JSON 块；正文非空；最终 usage 可取得 |
| `qwen-plus` Tool Calling | 通过 | 强制工具调用返回，工具名匹配；181 input + 14 output tokens；约 509.9 ms |
| `text-embedding-v4` | 通过 | 3 输入/3 输出；每条严格 1024 维；42 tokens；约 108.0 ms |
| Embedding 语义顺序 | 通过 | 相关相似度 0.790743，高于无关相似度 0.291717；仅为冒烟，不是检索质量评测 |
| `qwen3-rerank` | 通过 | 3 候选/3 结果；预期候选排第 1；145 tokens；约 139.5 ms |
| Youtu-RAG 强制重建 | 通过 | `pending/skipped` 最终进入 `completed`；API 与 Chroma 均为 2 chunks |
| 最小 KB Search | 通过 | 向量召回事件 1 次，答案非空且命中夹具关键事实 |
| 二阶段排序 | 通过 | Youtu-RAG 向量召回后调用 Reranker；成功事件 1 次；未降级 |
| WebUI / Monitor | 通过 | `/`、`/health`、`/monitor` 均为 HTTP 200 |
| 错误与降级 | 通过 | 离线模拟 401、429、超时、错误维度、Reranker 503；重试/降级符合策略 |
| 自动化测试 | 通过 | 17 passed；3 条为上游依赖弃用警告，无测试失败 |
| 静态检查 | 通过/已知基线 | `smartbuy/` 与三类核心 Provider 文件 Ruff 通过；全量供应商文件仍有上游既存 lint 债务，不在阶段 2 批量改写 |

## 最终小样本用量

以下是轮换并重启后的最终独立验证脚本记录；不包含任何请求或响应正文：

| 操作 | 调用数 | Input tokens | Output tokens | 估算费用（元） |
|---|---:|---:|---:|---:|
| 普通 Chat | 1 | 12 | 1 | 0.0000116 |
| 流式 Chat | 1 | 18 | 16 | 0.0000464 |
| Tool Calling | 1 | 181 | 14 | 0.0001728 |
| Embedding | 1 | 42 | 0 | 0.0000210 |
| Reranker | 1 | 145 | 0 | 0.0000725 |
| **合计** | **5** | **398** | **31** | **0.0003243** |

最终 Youtu-RAG 集成链路另记录：

- 建库与查询共 4 个 Embedding usage 事件，130 input tokens，估算 0.000065 元；延迟样本约 604.7、98.1、194.4、92.5 ms。
- 二阶段 Reranker 为 1 次、160 input tokens、约 840.1 ms，估算 0.000080 元。
- Youtu Agent 内部 LLM 调用未向当前阶段账本完整暴露 Token，因此不伪造精确总成本。全部测试为单文件和 3～5 条小样本，调用次数有界，实际消耗显著低于 5 元预算上限。
- 费用按验证时官方北京地域公开单价估算；未来价格变化时需重新校准。

## 错误与降级矩阵

| 场景 | 期望 | 实测 |
|---|---|---|
| 401 | 立即失败，不重试 | 1 次请求后抛出脱敏认证错误 |
| 429 | 有限退避 | 2 次 429 后第 3 次成功；总尝试数受上限控制 |
| Timeout | 有限退避 | 配置 1 次重试时共 2 次尝试后失败 |
| Embedding 数量/维度错误 | 阻断 | 抛出响应契约错误，不写入索引 |
| Reranker 503 | 保留向量顺序 | 返回 `degraded=true` 的保序结果 |
| Reranker 401 | 不重试并降级 | Youtu 适配返回向量顺序并设置 `last_degraded=true` |

## Windows 与上游兼容修复

1. PowerShell 启动脚本改为读取继承后的 Process 环境，并修复 Windows PowerShell 中参数默认值阶段 `$PSScriptRoot` 为空的问题。
2. YAML/JSON 文件显式用 UTF-8 读取，消除 GBK 默认编码导致的 Monitor 配置失败。
3. 默认 Agent 改为无 Web Search 的 `simple/base.yaml`；没有 Serper 凭据时启动不再失败。
4. Youtu Embedding 显式传 1024 维、验证返回数量/维度并去除文本预览日志。
5. 建库原先忽略 `VECTOR_STORE_PATH`，造成“报告 2 chunks、检索目录实际 0”；现已统一运行路径并以 Chroma 计数复核。
6. 上游 `force_rebuild` 在第二层增量判断中仍会跳过已完成源；现已把标志传入 `ProcessTask` 并验证强制重建实际处理 1 个文件。
7. Reranker 支持完整复数 `/reranks` 地址、顶层 `results`、有限重试和显式向量降级。

## 安全事件与处置

阶段 2 首次加载 KB Toolkit 时发现，上游 `SimpleAgent` 会把解析后的完整 `ToolkitConfig` 写入日志，其中包括 API Key。处置如下：

1. 立即停止 FastAPI 与 MinIO，不再使用受影响 Key。
2. 清空仓库外两份受影响运行日志；Key 未进入仓库、Git 暂存区或远端。
3. 用户禁用并轮换 Key，随后重启终端与智能体进程。
4. Toolkit、MCP 和自定义工具日志只记录名称、模式和字段名，不记录字段值；Chat 日志只记录长度和非敏感元数据。
5. 新增日志回归测试，虚构凭据未出现在 `caplog`。
6. 轮换后重新验证，运行日志和工作区的实际 Key/常见 Key 模式匹配数均为 0。

## 可复现命令

```powershell
uv sync --project vendor/youtu-rag --frozen
uv run --project vendor/youtu-rag python -m smartbuy.scripts.verify_bailian_stage2
uv run --project vendor/youtu-rag --group dev python -m pytest `
  smartbuy/tests/unit `
  smartbuy/tests/integration/test_youtu_bailian_adapters.py `
  vendor/youtu-rag/tests/rag/api/test_config_security.py -q
uv run --project vendor/youtu-rag --group dev ruff check `
  smartbuy `
  vendor/youtu-rag/utu/rag/embeddings/openai_embedder.py `
  vendor/youtu-rag/utu/rag/embeddings/factory.py `
  vendor/youtu-rag/utu/rag/rerankers/openai_reranker.py
```

真实 API 验证命令只应在已继承新环境变量的进程中运行。脚本只输出脱敏统计，但其调用会产生少量费用；不得在 CI 中默认执行。

## 阶段结论

阶段 2 的三模型、Youtu-RAG 建库、KB Search、二阶段 Rerank、错误策略、成本基线和安全回归均满足退出条件。显示器真实数据、评测集和 SmartBuy 业务 Agent 尚未实现，属于阶段 3 及以后工作。
