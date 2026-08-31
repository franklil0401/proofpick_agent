# ProofPick V2-2 Product Pack 运行说明

最后更新：2026-08-31

适用范围：Windows 本地 Product Pack 离线构建、发布、查看与回滚。它不是在线搜索、生产数据平台或实时索引指南。

## 前置与安全边界

- 使用 Python 3.12 和仓库已冻结的 `uv.lock`；本阶段未新增依赖。
- Product Pack 运行根目录必须位于 Git 工作区外，默认 `C:\ai\proofpick-v2\product-packs`。
- CLI 不读取百炼 Key，不调用网络或收费 API，不把运行 SQLite、索引文档、临时证据或版本指针写入仓库。
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

查看和回滚：

```powershell
uv run --project vendor/youtu-rag --group dev python -m smartbuy.product_packs.cli `
  --runtime-root $packRoot versions
uv run --project vendor/youtu-rag --group dev python -m smartbuy.product_packs.cli `
  --runtime-root $packRoot current
uv run --project vendor/youtu-rag --group dev python -m smartbuy.product_packs.cli `
  --runtime-root $packRoot rollback --data-version monitor-multi-region-2026-08-31-v2
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

## 索引状态

离线 `import` 会生成 65 份带完整元数据的 `vector_documents.jsonl` 和独立 collection 名，Manifest 状态为 `documents_ready`。它不等于真实 Chroma 已完成：

- Embedding 必须继续使用 `text-embedding-v4` 且显式固定 1024 维；
- 数据、切分、模型或维度任一变化必须构建新 collection；
- 真实构建完成前不能把 `documents_ready` 改写成 `completed`；
- 本阶段没有提供自动联网建库命令，也没有发生百炼调用或费用。

## 请求级临时证据

`RequestEvidenceWorkspace` 只能指向仓库外目录。临时记录固定为 `temporary/not_reviewed`，支持读取和清理，但不会自动写入正式 Ledger、SQLite、事实卡或索引。本阶段没有 Source Search，调用方不能把它描述成已核验的联网证据。

实现与验收见 [V2-2 报告](v2_2_product_pack_report.md)，决策见 [ADR-0010](../adr/0010-versioned-product-pack-and-evidence-ledger.md)。
