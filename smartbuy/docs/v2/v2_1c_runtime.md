# ProofPick V2-1C 本地运行说明

最后更新：2026-08-31

适用范围：Windows 11 本地 MVP；不是生产部署指南

## 默认与显式开关

不设置任何 V2 变量时仍运行 V1 ReAct：

```powershell
Remove-Item Env:PROOFPICK_ORCHESTRATOR -ErrorAction SilentlyContinue
Remove-Item Env:PROOFPICK_LANGGRAPH_FALLBACK_TO_REACT -ErrorAction SilentlyContinue
```

只在当前 PowerShell 进程显式试用 LangGraph：

```powershell
$env:PROOFPICK_ORCHESTRATOR = "langgraph"
$env:PROOFPICK_CHECKPOINT_PATH = "C:\ai\proofpick-v2\checkpoints.sqlite3"
$env:PROOFPICK_LANGGRAPH_FALLBACK_TO_REACT = "false"
.\smartbuy\scripts\start.ps1
```

恢复默认路径只需重启前设置：

```powershell
$env:PROOFPICK_ORCHESTRATOR = "react"
.\smartbuy\scripts\start.ps1
```

`PROOFPICK_ORCHESTRATOR` 只接受 `react` 或 `langgraph`。非法值会明确失败，不会静默选择。`PROOFPICK_LANGGRAPH_FALLBACK_TO_REACT=true` 只允许**初始化失败**显式回退；运行中失败不自动重放，避免重复调用。

## Checkpoint 约束

- 默认路径：`C:/ai/proofpick-v2/checkpoints.sqlite3`。
- 路径必须在 Git 仓库外；仓库内路径会被代码拒绝。
- SQLite、WAL/SHM、缓存和运行日志均不得提交 Git。
- Checkpoint 按 user/session/thread 的不可逆摘要隔离；恢复前校验状态版本。
- 原始 user/session/thread 和完整请求对象不作为图状态字段写入 SQLite。
- 测试使用 `InMemorySaver`；Windows 本地使用 `AsyncSqliteSaver`。
- SQLite 只适用于本地 MVP，不代表生产级多实例、HA 或多租户能力。
- PostgreSQL 只保留后端接口。未来迁移需另行确定连接管理、Schema migration、保留/删除策略、加密、备份和租户隔离。

如需删除某个 thread，调用 `LangGraphOrchestrator.clear_checkpoint(request)`；不要在服务运行中直接编辑 SQLite。清理整个本地文件前应先停止服务并确认精确路径位于 `C:/ai/proofpick-v2/`。

## 安全设置

- Checkpoint 序列化关闭 Pickle fallback。
- JSON constructor 使用精确模块白名单，不允许任意模块反序列化。
- 状态中不保存 API Key、Workspace ID、Authorization、完整 Prompt、隐藏思维链、连接对象或查询正文日志。
- 环境中的百炼变量仍按 V1 方式由当前进程继承；本说明不读取、显示或写入其值。

## 验证

离线 V2-1C 验证不调用百炼：

```powershell
uv sync --project vendor/youtu-rag --frozen
uv run --project vendor/youtu-rag --frozen python -m pytest `
  smartbuy/tests/unit/test_v2_orchestration_contract.py `
  smartbuy/tests/integration/test_v2_sqlite_checkpoint.py `
  smartbuy/tests/integration/test_v2_api_orchestration.py -q
```

详细结果与限制见 [V2-1C 报告](v2_1c_compatibility_report.md)。
