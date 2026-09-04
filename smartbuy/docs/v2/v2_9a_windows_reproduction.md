# V2-9A Windows 干净克隆复现

## 结论

2026-09-04 在新的短 ASCII 路径 `C:\ppv2rc` 完成普通 clone、冻结依赖、三品类数据/索引、服务、五 Demo、离线回放和停止验证。运行数据库、Chroma、MinIO、Memory 与日志全部位于 `C:\ppv2run`，Git 工作区保持干净。

## 环境

| 项目 | 实测 |
|---|---|
| Windows / Python | Windows 11 / Python 3.12.3 |
| Git / uv | Git 2.54.0.windows.1 / uv 0.12.3 |
| 冻结依赖 | `uv sync --frozen`，296 packages |
| 克隆 Commit | `db3293a464ded8d6558fc19853dc2b722b2b250c`（启动指针修复提交；最终 RC Commit 见 RC Manifest） |
| 外部运行根 | Monitor `C:\ppv2run\m`；Laptop/Headphone `C:\ppv2run\v`；服务 `C:\ppv2run\s` |

环境变量只检查 `configured/missing`。本文和运行日志没有保存 `Qianwen_api_key`、`Qianwen_workspace_id` 或 MinIO 凭据值。

## 可复现命令

```powershell
git clone --branch feature/proofpick-v2 --single-branch https://github.com/franklil0401/proofpick_agent.git C:\ppv2rc
Set-Location C:\ppv2rc
uv sync --project vendor\youtu-rag --frozen
.\smartbuy\scripts\preflight.ps1 -MinioPath C:\ai\minio\minio.exe -RuntimeRoot C:\ppv2run\v
.\smartbuy\scripts\bootstrap.ps1 -MinioPath C:\ai\minio\minio.exe -RuntimeRoot C:\ppv2run\m -V2RuntimeRoot C:\ppv2run\v
.\smartbuy\scripts\start.ps1 -MinioPath C:\ai\minio\minio.exe -MinioData C:\ppv2run\minio -SmartBuyRuntimeRoot C:\ppv2run\m -YoutuRuntimeRoot C:\ppv2run\youtu -ServiceRuntimeRoot C:\ppv2run\service -V2RuntimeRoot C:\ppv2run\v
```

完整服务检查 `http://127.0.0.1:8000/health`、`/`、`/monitor`、`/api/smartbuy/portfolio/capabilities` 与 MinIO health 均为 HTTP 200。停止：

```powershell
.\smartbuy\scripts\stop.ps1 -ServiceRuntimeRoot C:\ppv2run\service
```

无 Key/MinIO 的回放路径：

```powershell
.\smartbuy\scripts\replay.ps1 -Port 8088 -ServiceRuntimeRoot C:\ppv2run\replay
# 浏览 http://127.0.0.1:8088/app.html
.\smartbuy\scripts\replay.ps1 -ServiceRuntimeRoot C:\ppv2run\replay -Stop
```

## 实测步骤与耗时

| 步骤 | 结果 | 耗时 |
|---|---|---:|
| clone | 成功，vendor subtree 完整 | 4.791s |
| `uv sync --frozen` | 成功，296 packages | 21.747s |
| preflight | 11/11 | 0.213s |
| 首次 bootstrap | SQLite + 三索引完成 | 74.365s |
| 重复 bootstrap | 哈希/版本复用，无重复向量化 | 9.469s |
| 服务启动与 HTTP 检查 | 8000/9000/9001 ready | 约 28s |
| 五 Demo 本地合同 | 5/5 | 0.979s |
| Offline Replay | HTTP 200、5 个 Demo、声明正确 | 2.183s |
| stop | 只停止记录的进程 | 1.093s |

## 数据、SQLite 与索引

| Domain | 数据 / SQLite | Index / Collection | 结果 |
|---|---|---|---|
| Monitor | 12 products、16 sources、180 evidence；`monitor-cn-2026-08-26-v1` | 60 docs/chunks，`smartbuy_monitors_v1`，1024 维 | integrity `ok`，FK 0 |
| Laptop | 12 products、12 sources、406 evidence；`laptop-governed-2026-09-02-v1` | `laptop-governed-2026-09-02-v1-embedding1024-v1` / `proofpick_laptop_v2_4e6d332c11bf8f7c`，12 docs | integrity `ok`，FK 0 |
| Headphone | 12 products、20 sources、336 evidence；`headphone-governed-2026-09-03-v1` | `headphone-governed-2026-09-03-v1-embedding1024-v1` / `proofpick_headphone_v2_cae477364b46ccae`，12 docs | integrity `ok`，FK 0 |

Embedding 均为 `text-embedding-v4` / 1024 维。首次构建 64 个 Embedding HTTP 请求（Monitor 60，Laptop/Headphone 各 2 个批次），记录成本 ¥0.015586；两次 Trusted UI smoke 各执行 1 次查询 Embedding 与 1 次 Reranker，未触发 qwen-plus，Provider Token 未进入公开 API 响应，因此只记录请求数并把总成本保守限定在 ¥0.03 内。无重试、无 401/403。

## 收尾与限制

- Trusted Headphone 在线 smoke 两次均 completed，Checker 未降级；第二次公开轨迹为 Product Query → KB → 5 次 Evidence Check → Checker。
- Offline Replay 不需要任何模型或存储凭据；它不等价于在线 Agent。
- `stop.ps1` 后 8000/9000/9001 全部 free，`replay.ps1 -Stop` 后 8088 free。
- 干净克隆 `git status --short` 为空。脚本不会删除非本项目记录的进程，也不会把外部运行资产提交到仓库。
