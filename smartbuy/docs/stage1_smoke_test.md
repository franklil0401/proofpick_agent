# 阶段 1 Windows 基线冒烟记录

- 日期：2026-08-26
- 范围：固定上游、依赖同步、MinIO、FastAPI/WebUI、文件、基础 Chat、最小知识库结构和配置脱敏
- 明确不在本次范围：`text-embedding-v4` 真实调用、向量索引、KB Search、Youtu-RAG Reranker 适配、SmartBuy 业务流程
- 测试数据：[stage1_baseline.md](../tests/fixtures/stage1_baseline.md)，本项目自制且不含隐私

## 结果摘要

| 编号 | 检查项 | 结果 | 证据/说明 |
|---|---|---|---|
| S0 | Git、Python、uv、subtree | 通过 | `main`；Python 3.12.3；uv 0.12.3；Git 2.54.0；subtree 可用 |
| S1 | `uv sync --frozen` | 通过 | 约 163.79 秒；锁文件未变化；关键依赖导入通过 |
| S2 | MinIO | 通过 | API 9000 健康检查 200；Console 9001；均绑定回环地址 |
| S3 | FastAPI / WebUI / Monitor | 通过 | `/`、`/health`、`/monitor` 均为 200 |
| S4 | Markdown 上传和管理 | 通过 | 上传约 6.4 秒；文件列表可见；OCR/HiChunk 均跳过 |
| S5 | 知识库结构 | 通过 | 创建 KB ID 1；文件关联成功；状态 `pending`、0 chunks、无错误 |
| S6 | 基础 Chat | 通过 | 切换 `simple/base.yaml`；非流式请求 200；约 2.081 秒；回答非空 |
| S7 | KB Build / KB Search | 延后，不阻塞阶段 1 | 不调用未验证的 Embedding；阶段 2 完成 Provider 与 1024 维验证后执行 |
| S8 | 配置脱敏 | 通过 | 接口 Key 字段为 `<redacted>`，无 Authorization 内容；单测 1 passed |

阶段 1 触发 2 次 `qwen-plus` 用户级操作（上传元数据提取、基础 Chat），均成功；上游响应未提供可核对的 Token/费用字段，因此 Token 与估算成本记录为“未知”，不伪造数值。阶段 1 未调用 Embedding 或 Reranker。阶段 2 需先建立安全的用量账本，再在 5 元上限内进行三模型适配测试。

## 可复现命令

以下命令不包含真实凭据。MinIO 用户名和密码只应在当前测试进程中设置，两个服务进程必须使用一致值；不要将真实值写入脚本、命令历史或仓库。

```powershell
Set-Location vendor/youtu-rag
uv sync --frozen
uv run pytest tests/rag/api/test_config_security.py -q
```

MinIO 从官方 Windows 发行包下载到 `C:/ai/minio/minio.exe` 后，在单独的本地测试终端启动。Youtu-RAG 在具备同一 MinIO 当前进程配置的终端运行：

```powershell
Set-Location <repo-root>
./smartbuy/scripts/start_youtu_rag.ps1
```

启动脚本要求 Windows 持久化环境中存在 `Qianwen_api_key` 与 `Qianwen_workspace_id`，只报告 `configured/missing`，不得用打印值的方式排查。

## 关键配置与 Windows 处理

- 供应商目录较深；仓库和运行数据均使用短 ASCII 路径，运行数据移至 `C:/ai/youtu-rag-runtime/`。
- 上游锁文件可直接用于 Python 3.12.3，无需修改。
- OCR、HiChunk、Reranker、Memory 和本地模型在基线中关闭，减少 Windows/GPU 和阶段边界干扰。
- MinIO 未预装到 PATH，使用仓库外固定二进制和数据目录。
- 启动脚本绑定 `127.0.0.1`，不把 Python Executor 或开发服务暴露公网。

## 安全事件与修复

阶段 1 初次检查上游 `/api/config/{kb_id}` 时发现：上游会先解析环境变量，再把完整配置对象返回，导致凭据字段可能出现在 API 响应中。该响应曾在当前开发会话的工具输出中暴露旧 Key。发现后立即完成以下处置：

1. 停止 API 与 MinIO，确认端口关闭。
2. 检查工作区、diff 和 Git；未发现 Key 被写入源码、文档、日志、数据库快照或待提交内容，也未发生推送。
3. 用户已禁用旧 Key，并把新值写入同名 Windows 系统变量。
4. 配置接口增加递归敏感字段脱敏；测试只使用 `dummy-*` 虚构值。
5. 启动脚本不再读取可能残留旧值的 Process 作用域，只读取 Machine/User 持久化作用域。
6. 重新启动后仅断言脱敏哨兵、凭据前缀缺失和状态码，不再输出原始配置响应。

安全回归命令结果：`1 passed`；重新运行接口检查结果为 Key 字段已脱敏、未发现 Authorization 内容。轮换后的新 Key 从未在测试输出或文件中显示。

## 阶段边界与退出结论

阶段 1 已证明未进行 SmartBuy 业务改造时，Youtu-RAG 的依赖、对象存储、WebUI、监控、文件管理、知识库配置骨架和基础 LLM Chat 可在目标 Windows 主机运行。知识库文件尚未向量化，因此不能宣称已完成 KB Search。

阶段 2 必须先完成：

1. `text-embedding-v4` 真实最小调用与严格 1024 维断言。
2. Youtu-RAG Embedding Provider 的请求/响应兼容性与索引元数据。
3. `qwen3-rerank` 请求路径、`results` 解析和关闭/降级策略。
4. 完成后重新构建本测试 KB，并补跑 KB Search。

这些是已确认的阶段 2 依赖边界，不是阶段 1 的阻断失败。
