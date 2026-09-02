# V2-6A Laptop Pack 本地运行说明

最后更新：2026-09-02

本说明仅用于离线生成和校验 Laptop Product Pack。不会调用 qwen-plus、Embedding、Reranker 或搜索 API，也不会构建 Chroma。

## 前置条件

- Windows 11、Python 3.12、Git、uv。
- 当前目录为仓库根目录，分支为 `feature/proofpick-v2`。
- 运行根目录必须在 Git 仓库外，例如 `$env:TEMP\proofpick-laptop-runtime`。

## 生成可提交的 Product Pack

```powershell
uv run --project vendor/youtu-rag python smartbuy/scripts/build_laptop_product_pack.py `
  --input smartbuy/data/laptop/laptop_configurations_v1.json `
  --output smartbuy/product_packs/examples/laptop-v1/pack.json
```

该命令应输出 12 products、12 sources、406 evidence；输入未变时输出字节稳定。

## staging、校验、发布与回滚

```powershell
$runtimeRoot = Join-Path $env:TEMP "proofpick-laptop-runtime"
$domainPath = "smartbuy/domain_packs/laptop"
$packPath = "smartbuy/product_packs/examples/laptop-v1/pack.json"

uv run --project vendor/youtu-rag python -m smartbuy.product_packs.domain_cli --runtime-root $runtimeRoot --domain-pack $domainPath stage --pack $packPath
uv run --project vendor/youtu-rag python -m smartbuy.product_packs.domain_cli --runtime-root $runtimeRoot --domain-pack $domainPath validate --data-version laptop-governed-2026-09-02-v1
uv run --project vendor/youtu-rag python -m smartbuy.product_packs.domain_cli --runtime-root $runtimeRoot --domain-pack $domainPath publish --data-version laptop-governed-2026-09-02-v1
uv run --project vendor/youtu-rag python -m smartbuy.product_packs.domain_cli --runtime-root $runtimeRoot --domain-pack $domainPath current
uv run --project vendor/youtu-rag python -m smartbuy.product_packs.domain_cli --runtime-root $runtimeRoot --domain-pack $domainPath versions
uv run --project vendor/youtu-rag python -m smartbuy.product_packs.domain_cli --runtime-root $runtimeRoot --domain-pack $domainPath rollback --data-version laptop-governed-2026-09-02-v1
```

构建目录含 EAV SQLite、JSONL、Evidence Ledger、事实卡、待索引文档和 Manifest。路径在仓库外，不能提交运行 SQLite 或派生产物。

## 验证

```powershell
uv run --project vendor/youtu-rag --group dev python -m pytest smartbuy/tests/integration/test_v2_laptop_domain_pack.py -q
uv run --project vendor/youtu-rag --group dev ruff check smartbuy
uv run --project vendor/youtu-rag python -m compileall -q smartbuy
```

验收应看到 12 个互不合并的配置、4 个品牌、406 条 Evidence，SQLite integrity 为 `ok`、外键 0，两次独立构建 Manifest SHA-256 均为 `d44373c8214cb996776445e5a5c1da60c233ce5d4b770c261399d913211ac1ad`。

## 索引安全边界

`index_manifest.json` 仅声明 `documents_ready`、12 documents、`text-embedding-v4` 和 1024 维，`paid_index_build_performed=false`。这不是可用 Chroma 索引；调用 `require_completed_index` 必须失败。真实索引、独立 collection 和 KB Search 属于 V2-6B，未经授权不得执行。
