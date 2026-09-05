# V2-9H RC3 Windows 干净复现记录

## 范围

2026-09-05 在一个此前不存在的新短 ASCII clone 目录和独立仓库外运行目录验证 RC3。本文不记录用户名、私有路径、密钥值或 Workspace 值。使用的是生产 Commit `ba6606ae249bafc89c18b320935c767a3f756c34`。

## 结果

| 检查 | 结果 |
|---|---|
| 普通 clone / vendor subtree | 通过；HEAD 与生产 Commit 一致，工作区干净 |
| `uv sync --frozen` | 通过；Python 3.12.3，解析/安装 296 个锁定包 |
| `preflight.ps1 -OfflineReplay` | 11/11 |
| `bootstrap.ps1 -OfflineReplay` | 通过；仓库外幂等生成三品类 SQLite/事实卡/待索引文档，不调用模型 |
| Monitor 数据 | 12 products / 4 brands / 16 sources / 4 prices / 180 evidence；SQLite ok，FK 0 |
| Laptop 数据 | 12 products / 12 sources / 406 evidence；SQLite ok，FK 0 |
| Headphone 数据 | 12 products / 20 sources / 336 evidence；SQLite ok，FK 0 |
| Monitor 索引 | Collection `smartbuy_monitors_v1`，60 documents/chunks，12 models，1024 维 |
| Laptop 索引 | Collection `proofpick_laptop_v2_4e6d332c11bf8f7c`，12 documents/chunks，1024 维 |
| Headphone 索引 | Collection `proofpick_headphone_v2_cae477364b46ccae`，12 documents/chunks，1024 维 |
| 完整 preflight | 11/11；环境变量只显示 configured/missing |
| FastAPI / WebUI / Monitor / MinIO | `/`、`/health`、`/monitor`、capabilities、classic WebUI 与 MinIO health 均 HTTP 200 |
| 模式展示 | `Trusted Mode · Stable` 与 `Online Research · Experimental` 均可见；Online 需显式确认 |
| 五个固定 Demo | 5/5，API 调用 0，费用 ¥0 |
| Offline Replay | HTTP 200，脱敏回放与 Experimental 声明可见 |
| Stop | 8000、8088、9000、9001 均已释放 |
| 最终 clone 状态 | 干净 |

## 复现命令

```powershell
git clone --branch release/proofpick-v2-rc3 --single-branch https://github.com/franklil0401/proofpick_agent.git C:\ppv2rc3
Set-Location C:\ppv2rc3
uv sync --project vendor\youtu-rag --frozen
.\smartbuy\scripts\preflight.ps1 -RuntimeRoot C:\ppv2run\v
.\smartbuy\scripts\bootstrap.ps1 -RuntimeRoot C:\ppv2run\m -V2RuntimeRoot C:\ppv2run\v
.\smartbuy\scripts\start.ps1 -SmartBuyRuntimeRoot C:\ppv2run\m -V2RuntimeRoot C:\ppv2run\v
```

访问 `http://127.0.0.1:8000/`，验证完成后执行：

```powershell
.\smartbuy\scripts\stop.ps1
```

无 Key/MinIO 时可用 `replay.ps1` 启动固定脱敏回放。完整参数和外部运行目录边界见 [V2-9A Windows 说明](v2_9a_windows_reproduction.md)。

## 语义 Manifest 说明

fresh bootstrap 生成的 Laptop/Headphone 原始运行 Manifest 会因 Domain Pack 指纹与运行元数据变化而有不同字节哈希，但 Data Version、记录数、逻辑数据哈希与索引合同一致。RC3 因而使用排除时间、延迟、Token、费用和机器路径的 [Semantic Manifest](v2_release_candidate_rc3_manifest.md)作为跨机器门禁；原始运行字段仍保留用于本机审计。

本次没有重新构建收费 Embedding，也没有运行在线 Source Search、Open Research 或独立评测。
