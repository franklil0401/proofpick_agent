# ProofPick V2-2 Product Pack 运行说明

最后更新：2026-08-31

适用范围：Windows 本地 Product Pack 构建、发布、独立 Chroma 建库、查看与回滚。它不是在线搜索、生产数据平台或实时价格指南。

## 前置与安全边界

- 使用 Python 3.12 和仓库已冻结的 `uv.lock`；本阶段未新增依赖。
- Product Pack 运行根目录必须位于 Git 工作区外，默认 `C:\ai\proofpick-v2\product-packs`。
- 数据 CLI 不读取百炼 Key；只有显式 `build-index` 和验收脚本读取当前进程继承的百炼配置。命令不会打印 Key 或 Workspace ID，也不会把运行 SQLite、Chroma、临时证据或版本指针写入仓库。
- 示例只含 Dell 官方 URL、来源元数据、自制短摘要和结构化字段；不包含网页原文。

以下命令从仓库根目录执行：

```powershell
$packRoot = "C:\ai\proofpick-v2\product-packs"
$packFile = "smartbuy\product_packs\examples\monitor-u2725qe-us\pack.json"

uv run --project vendor/youtu-rag --group dev python -m smartbuy.product_packs.cli `
  --runtime-root $packRoot import --pack $packFile
uv run --project vendor/youtu-rag --group dev python -m smartbuy.product_packs.cli `
  --runtime-root $packRoot validate --data-version monitor-multi-region-2026-08-31-v2
uv run --project vendor/youtu-rag --group dev python -m smartbuy.product_packs.cli `
  --runtime-root $packRoot publish --data-version monitor-multi-region-2026-08-31-v2
```

使用真实 `text-embedding-v4` 构建独立 1024 维索引；接口每批最多 10 条，成本门不得高于 ¥1：

```powershell
$dataVersion = "monitor-multi-region-2026-08-31-v2"
$indexVersion = "monitor-multi-region-h2-v2-embedding1024-r1"

uv run --project vendor/youtu-rag --group dev python -m smartbuy.product_packs.cli `
  --runtime-root $packRoot build-index --data-version $dataVersion `
  --index-version $indexVersion --batch-size 10 --cost-limit-cny 1
uv run --project vendor/youtu-rag --group dev python -m smartbuy.product_packs.cli `
  --runtime-root $packRoot validate-index --index-version $indexVersion
uv run --project vendor/youtu-rag --group dev python -m smartbuy.product_packs.cli `
  --runtime-root $packRoot activate-index --index-version $indexVersion
```

只有 `validate-index` 对 65 个 ID、向量维度、必需元数据、Data Manifest 和逻辑哈希全部通过后，`activate-index` 才原子更新 `current_index.json`。候选目录构建失败、数量/维度错误、Manifest 不符或未完成时均 fail closed，旧指针不变。

查看和回滚数据/索引：

```powershell
uv run --project vendor/youtu-rag --group dev python -m smartbuy.product_packs.cli `
  --runtime-root $packRoot versions
uv run --project vendor/youtu-rag --group dev python -m smartbuy.product_packs.cli `
  --runtime-root $packRoot current
uv run --project vendor/youtu-rag --group dev python -m smartbuy.product_packs.cli `
  --runtime-root $packRoot rollback --data-version monitor-multi-region-2026-08-31-v2
uv run --project vendor/youtu-rag --group dev python -m smartbuy.product_packs.cli `
  --runtime-root $packRoot index-versions
uv run --project vendor/youtu-rag --group dev python -m smartbuy.product_packs.cli `
  --runtime-root $packRoot current-index
uv run --project vendor/youtu-rag --group dev python -m smartbuy.product_packs.cli `
  --runtime-root $packRoot rollback-index --index-version $indexVersion
```

输出只包含 command、status、data version、Manifest hash 和聚合计数，不输出 Pack 正文、私人路径或凭据。

## 特性开关

默认行为等同于：

```powershell
$env:PROOFPICK_PRODUCT_PACK_ENABLED = "false"
```

此时 API 不读取 Product Pack 指针，继续使用 V1 数据路径。只有在外部版本已经发布、所有产物完成校验且所需 Chroma collection 已按 Manifest 契约构建后，才可以在当前进程显式选择：

```powershell
$env:PROOFPICK_PRODUCT_PACK_ENABLED = "true"
$env:PROOFPICK_PRODUCT_PACK_ROOT = "C:\ai\proofpick-v2\product-packs"
```

开关只接受 `true/false`。版本指针缺失、Manifest 损坏、SQLite 不完整、artifact hash 不符或索引元数据不一致会 fail closed，不静默切回 V1。关闭开关后无需迁移数据即可恢复 V1 路径。

## 索引状态与最小在线验收

`import` 生成 65 份带完整元数据的 `vector_documents.jsonl`，Data Manifest 状态保持 `documents_ready`；`build-index` 另建不可变的 Chroma 目录和 Live Index Manifest，成功状态为 `completed`。当前已验证版本为：

- Data Version：`monitor-multi-region-2026-08-31-v2`；
- Index Version：`monitor-multi-region-h2-v2-embedding1024-r1`；
- Collection：`proofpick_monitor_v2_b9e7bc6d41a735fa`；
- 65 documents / 65 chunks，`text-embedding-v4` / 1024。

最小在线验收会执行 6 条查询，不运行 LLM、Demo 或 40 条评测；结果文件必须写在仓库外：

```powershell
uv run --project vendor/youtu-rag python -m smartbuy.scripts.verify_v2_product_pack_live `
  --runtime-root $packRoot --output C:\ai\proofpick-v2\v2_2b_live_results.json
```

本机 V2-2B 结果为：7 次建库 Embedding + 11 次最终查询 Embedding/Reranker，连同两次首次失败估算总成本约 ¥0.0169。模型、维度、切分或 Data Version 任一变化必须使用新的 Index Version 和 collection；不得原地覆盖。

## 请求级临时证据

`RequestEvidenceWorkspace` 只能指向仓库外目录。临时记录固定为 `temporary/not_reviewed`，支持读取和清理，但不会自动写入正式 Ledger、SQLite、事实卡或索引。本阶段没有 Source Search，调用方不能把它描述成已核验的联网证据。

实现与验收见 [V2-2 报告](v2_2_product_pack_report.md)，决策见 [ADR-0010](../adr/0010-versioned-product-pack-and-evidence-ledger.md)。
