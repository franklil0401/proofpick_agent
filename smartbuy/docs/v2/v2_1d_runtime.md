# ProofPick V2-1D Domain Pack 运行说明

最后更新：2026-08-31

适用范围：Windows 本地兼容验证；不是生产部署或 Product Pack 导入指南。

## 默认行为

不设置 V2 Domain Pack 变量时，API 继续使用未包装的 V1 路径：

```powershell
Remove-Item Env:PROOFPICK_DOMAIN_PACK_ENABLED -ErrorAction SilentlyContinue
.\smartbuy\scripts\start.ps1
```

默认值等同于 `PROOFPICK_DOMAIN_PACK_ENABLED=false`。此时不读取 Monitor Pack、不改变 ReAct/LangGraph 选择、不创建数据库或迁移数据。

## 显式兼容验证

只在当前 PowerShell 进程中启用已提交的 Monitor Pack：

```powershell
$env:PROOFPICK_DOMAIN_PACK_ENABLED = "true"
$env:PROOFPICK_DOMAIN_ID = "monitor"
$env:PROOFPICK_DOMAIN_PACK_PATH = "C:\ai\proofpick\smartbuy\domain_packs\monitor"
.\smartbuy\scripts\start.ps1
```

实际 clone 路径不同时，应把 `PROOFPICK_DOMAIN_PACK_PATH` 改为该 clone 内的 `smartbuy\domain_packs\monitor`。不要把个人路径写回仓库配置。开关只接受 `true/false`；Domain ID、Pack 版本、Catalog 哈希或策略校验不一致会明确失败，不会静默切换到未包装路径。

关闭后回滚：

```powershell
$env:PROOFPICK_DOMAIN_PACK_ENABLED = "false"
.\smartbuy\scripts\start.ps1
```

无需转换 V1 SQLite、Chroma、事实卡、Memory 或请求数据。`PROOFPICK_ORCHESTRATOR` 仍独立默认 `react`；V2-1D 没有把 LangGraph 设为默认值。

## 安全边界

- Pack 只加载固定 JSON，不执行 Pack 中的代码或任意模块引用。
- Pack 失败、Catalog 哈希不一致或通用结果与 V1 Checker 不一致时关闭失败。
- 事件只公开 Domain ID、Pack 版本、状态和脱敏错误类别，不包含 Prompt、Key、Workspace ID、用户正文或私人路径。
- 本阶段没有 Product Pack 导入、Evidence Ledger、第二品类或收费 API 调用。

## 离线验证

```powershell
uv run --project vendor/youtu-rag --group dev python -m pytest `
  smartbuy/tests/unit/test_v2_domain_pack.py `
  smartbuy/tests/integration/test_v2_domain_pack_compat.py -q
```

实现证据见 [V2-1D 报告](v2_1d_domain_pack_report.md)，决策见 [ADR-0009](../adr/0009-domain-contracts-and-monitor-pack.md)。
