# V2-6B Laptop 索引与工具运行说明

最后更新：2026-09-02

本说明只复现 Laptop 数据快照、真实索引和独立检索评测。它不会运行 V2-6A 的 30 条 Agent 冻结任务，也不会调用 qwen-plus。

## 前置条件与安全边界

- Windows 11、Python 3.12、Git、uv。
- 系统环境变量 `Qianwen_api_key`、`Qianwen_workspace_id` 已配置；程序只输出 configured/missing，不输出值。
- 运行目录必须在仓库外，例如 `$env:TEMP\proofpick-v2-6b-runtime`。
- Embedding 固定 `text-embedding-v4`/1024 维，批次不超过 10；Reranker 使用 `qwen3-rerank`。
- 本 Runner 的在线费用硬上限为 ¥1；不使用 qwen-plus。

## 运行首次检索评测

```powershell
$runtimeRoot = Join-Path $env:TEMP "proofpick-v2-6b-runtime"

uv run --project vendor/youtu-rag python -m smartbuy.eval.v2_6b_laptop_retrieval_runner `
  --runtime-root $runtimeRoot `
  --output (Join-Path $runtimeRoot "v2_6b_laptop_retrieval_reproduction.json")
```

冻结检索集为 `smartbuy/eval/v2_6b_laptop_retrieval_cases.jsonl`，30 条，SHA-256 `7c70e4da196c17d3d09f6ee5c42162d16995963c2ee18c0c4254af55d6903e8c`。Runner 在哈希变化时拒绝运行。
Runner 也拒绝覆盖已存在的输出；仓库中的首次结果是不可覆盖历史证据，复现结果应留在仓库外运行目录。

首次结果应对应：

- Data Version：`laptop-governed-2026-09-02-v1`。
- Index Version：`laptop-governed-2026-09-02-v1-embedding1024-v1`。
- Collection：`proofpick_laptop_v2_4e6d332c11bf8f7c`。
- Documents/Chunks：12/12。
- Vector/Reranker Recall@5：30/30、30/30。

## 离线工具闭环

```powershell
uv run --project vendor/youtu-rag --group dev python -m pytest `
  smartbuy/tests/integration/test_v2_laptop_toolchain.py -q
```

测试覆盖只读 Product Query、Evidence 四态、Checker 完整候选池、10 条组合任务、Reranker 降级、索引失败、冲突注入以及 Monitor/Laptop 的 Pack、字段、Memory 和 Checkpoint 隔离。所有 SQLite/Chroma 测试产物写入 pytest 临时目录，不进入 Git。

## 回滚与 fail-closed

`DomainIndexManager` 只在完整校验后写入 `current_laptop_index.json`。构建失败不会更改指针；指针缺失、损坏、跨域或 Manifest/Data 不匹配时 KB Search 返回 failed。恢复旧索引时必须调用对应 Manager 的 `activate(old_index_version)`，且该索引必须属于当前 Laptop Data Version。

Laptop 与 Monitor 的指针和 collection 名分别隔离。不要手工复制 Chroma 目录、修改 Manifest 或把运行目录放进仓库。
