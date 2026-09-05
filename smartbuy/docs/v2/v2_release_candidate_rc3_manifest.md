# ProofPick V2-9H RC3 Semantic Release Manifest

## 冻结声明

`proofpick-v2-rc3` 的正式定位是 **Trusted Multi-domain Decision Core + Experimental/Beta Online Research**。生产代码固定在 Commit `ba6606ae249bafc89c18b320935c767a3f756c34`，Git Tree 固定为 `84766c5d8840b50a27c612e24379b6dd63736741`。本文件及其后的验证文档不属于该生产 Tree。

RC3 只是交给独立评测方的候选，不是 Git Tag、GitHub Release、生产 SLA 或发布通过结论。本阶段没有创建、查看或运行新的 Holdout。

规范机器清单是 [`v2_9h_rc3_semantic_runtime_manifest.json`](../../eval/results/v2_9h_rc3_semantic_runtime_manifest.json)。其中每个冻结组都列出**完整的成员路径、单文件 SHA-256 和聚合 SHA-256**；独立评测方不得从当前工作区重新猜测成员集合。

**Semantic Manifest Payload SHA-256：** `4883f4251c8cb1f4dc6b86b6777b3d19ace74bee92943129c1146fc4e266b367`

哈希对象只包含稳定语义合同：生产 Commit/Tree、完整文件组、三品类数据与索引合同、评分接口、测试基线和 RC3 能力边界。`created_at`、延迟、Token、费用和机器路径只保留在 `runtime_audit`，不参与 Payload 哈希。相同生产 Commit 的第二次仓库外生成得到同一 Payload SHA-256。

## 冻结组

| 冻结组 | 文件数 | Aggregate SHA-256 |
|---|---:|---|
| agent_tool_orchestration | 13 | `5615bd91cba95529bfe00012cd99a54fd0f9c3e4fcfcb70a411d36715d67dbce` |
| all_production_python | 112 | `f82a2015f708f899510ab0c658821f2c6d3e53e642f8d9124a16f89d44dfceda` |
| constraint_checker | 5 | `18d1fda357cb8e68b6504b85e6ff8e96471a7add9f0da104603700e4171d729c` |
| constraint_resolution_clarification | 7 | `9cf516b4e2ba9368be94ce18abf3680b32100b231acb74289fdfd788cdaa1e58` |
| dependency_lock | 2 | `d0802f956a36e0ae65d9306fea81b4c80614ace2237ab32f24616fdc7e3fdf9c` |
| domain_pack_config | 10 | `822b494e9b0c6320b9f9c03148c0471f4b1bf97eb9c40c9d1e23e59b7fe47c7c` |
| evidence_check | 3 | `c977ef1fe3e249d60d83b2b8b1e66725a386cbaae7fa59ad70cb224bfd61a96b` |
| governed_data | 70 | `58804852ff1031fd576a0ae5ed0553b6b390106837171c57c21fb26f3f7799f9` |
| memory | 3 | `b22a0bc751344d429d8310418ca6b8a050009417b7b58268e788b0d327ef2dc6` |
| open_research_source_search_beta | 22 | `55f3e39be11549e040970f996f9134f481dd68d466d521ae2395bb058466b583` |
| product_pack_contract_and_runtime | 14 | `2e7457d03604c51d8a8e8ebc7a90499a433af2f5e25438302a1e0aad90aac90d` |
| product_ui_and_demo_contract | 6 | `fb5c5cf15669834d8e5f8b0e9eae5f5354dcc3b8de2a821b563f246d44f1682e` |
| prompt_contract | 3 | `8c577e1501b82a5f2d7d2788883f1fa5e41eb994bf3aaddd295a0579ed89de7b` |
| query_intent_product_reference_candidate_scope | 11 | `b60a872eee4cc7ff2d60424f8df7cbde297fcbc232c40aaae2c5ee65e14ad3ca` |
| ranker | 4 | `4a8cba4a1333b83545c4456dc07c6cdb2b528e9eb1b521239e9f802affee2715` |
| scoring_interface | 10 | `0caf6c39b80a51982f4ea19db6dcdcb1ba31232dcb0050a712fb3cb705107725` |
| test_baseline | 55 | `6cfa05cdf43a1cf4c79a988d1f318b50794935f069251071e6b17e2661d5549b` |
| tool_schema_and_contracts | 14 | `f6957181de292f39b4709becc0dfb447650281fa2f7b20cb9e0eefbe92c55c91` |
| windows_scripts | 6 | `0368c621181fcc6f5996e5541541922cfc70d3de4934ab3d4746dc2d5c6d1382` |

## 三品类数据与索引合同

| Domain | Data Version | Index Version / Collection | 文档 | Embedding |
|---|---|---|---:|---|
| Monitor | `monitor-cn-2026-08-26-v1` | `monitor-fact-card-h2-v1` / `smartbuy_monitors_v1` | 60 | `text-embedding-v4`, 1024 |
| Laptop | `laptop-governed-2026-09-02-v1` | `laptop-governed-2026-09-02-v1-embedding1024-v1` / `proofpick_laptop_v2_4e6d332c11bf8f7c` | 12 | `text-embedding-v4`, 1024 |
| Headphone | `headphone-governed-2026-09-03-v1` | `headphone-governed-2026-09-03-v1-embedding1024-v1` / `proofpick_headphone_v2_cae477364b46ccae` | 12 | `text-embedding-v4`, 1024 |

完整逻辑数据哈希位于机器清单的 `semantic_contract.domains`。Embedding 模型或维度变化必须创建新索引，不能复用上述 Collection。

## 能力和门槛合同

- 默认模式：`trusted`。
- Stable：三品类 Pack、工具编排、Product Query/Text2SQL、KB/Embedding/Reranker、多跳 Evidence、Checker、Ranker、Memory、澄清、Scope 单调收窄和 Windows 本地复现。
- Experimental/Beta：Source Search、Web Extractor、请求级 Open Evidence 和 Online Research。
- Trusted 发布门槛与 Online 安全门槛均写入 Payload；Online 完成率明确为非 Trusted Core 发布阻断指标。
- Open Evidence 不能进入治理 Ledger 或 Trusted Checker；失败时返回 unknown，不得用安全终态冒充研究完成。

## 复现命令

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run --project vendor/youtu-rag python -m smartbuy.reproducibility.v2_9h_rc3_manifest `
  --production-commit ba6606ae249bafc89c18b320935c767a3f756c34 `
  --output C:\ppv2run\rc3-manifest-check.json
```

比较输出中的 `payload_sha256`，不要比较 `runtime_audit.created_at` 或文件原始字节哈希。
