# V2-8 Headphone 运行说明

## 离线构建

```powershell
uv run --project vendor/youtu-rag python -m smartbuy.scripts.build_headphone_product_pack --help
uv run --project vendor/youtu-rag --group dev python -m pytest smartbuy/tests/integration/test_v2_headphone_domain_pack.py -q
```

Product Pack staging、SQLite、事实卡、向量文档和 Manifest 均写入调用方指定的仓库外目录。正式版本为 `headphone-governed-2026-09-03-v1`；失败构建不切换 current 指针。

## 真实索引

| 项目 | 值 |
|---|---|
| Collection | `proofpick_headphone_v2_cae477364b46ccae` |
| Index Version | `headphone-governed-2026-09-03-v1-embedding1024-v1` |
| 文档 / Chunk | 12 / 12 |
| Embedding | `text-embedding-v4`, 1024 维，batch ≤ 10 |
| 路径 | `%LOCALAPPDATA%\ProofPick\v2_8_headphone` |

索引没有覆盖 Monitor/Laptop；输入数据或模型/维度变化必须创建新 Index Version。真实检索结果保存在 [`v2_8_headphone_retrieval_first.json`](../../eval/results/v2_8_headphone_retrieval_first.json)。

## 工程评测

```powershell
uv run --project vendor/youtu-rag --group dev python -m pytest smartbuy/tests/integration/test_v2_headphone_domain_pack.py smartbuy/tests/integration/test_v2_headphone_toolchain.py smartbuy/tests/integration/test_v2_three_domain_isolation.py -q
```

30 条工程集已运行一次并保留首次失败；修复后文件明确标为 exposed regression，不能称为新 Holdout。不要在普通单元测试中调用真实 API。

## Open Research

仅在 `ZhiPu_api_key` 已由进程继承、且明确允许联网时运行：

```powershell
uv run --project vendor/youtu-rag python -m smartbuy.scripts.verify_v2_8_headphone_open_research
```

脚本从搜索结果发现 URL，不硬编码目标页面；完整临时 Evidence 写在仓库外。公开结果仅保留脱敏元数据和哈希。Open Evidence 的 `trusted_eligible=false`，不会进入治理 Ledger 或 Checker。

## 配置与安全

- API Key 只从系统环境变量读取，检查时只输出 `configured/missing`。
- 401/403 不重试；429/5xx/超时只有限重试。
- 不提交 SQLite、Chroma、临时 Evidence、缓存或日志。
- V2 功能关闭时仍回到 V1 稳定路径；默认编排器仍是 ReAct。
