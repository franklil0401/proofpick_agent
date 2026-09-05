# ProofPick V2 RC3 Manifest R1

## 修订身份

- Release Candidate：`proofpick-v2-rc3`
- Manifest Revision：`r1`
- 生产 Commit：`ba6606ae249bafc89c18b320935c767a3f756c34`
- 生产 Tree：`84766c5d8840b50a27c612e24379b6dd63736741`
- 新 Payload SHA-256：`abf655017bdb0b27dfe3dd220d1e173e8a0e3e0ff2244590efc0d42d79fd6791`
- 旧失败 Payload：`4883f4251c8cb1f4dc6b86b6777b3d19ace74bee92943129c1146fc4e266b367`

旧文件 [`v2_9h_rc3_semantic_runtime_manifest.json`](../../eval/results/v2_9h_rc3_semantic_runtime_manifest.json)永久保留为冻结失败历史，不再作为独立评测门禁。新的规范机器清单是 [`v2_9h_rc3_semantic_runtime_manifest_r1.json`](../../eval/results/v2_9h_rc3_semantic_runtime_manifest_r1.json)。它逐组列出完整成员路径、直接从生产 Commit Git blob 原始字节计算的 SHA-256，以及组聚合哈希。

## 冻结算法

1. 使用 `git ls-tree -r -z --name-only <production_commit>`取得唯一成员全集。
2. 只从该集合选择每组成员，工作区新增、删除或换行转换不能改变集合。
3. 使用 `git cat-file blob <production_commit>:<path>`读取原始 Git blob 字节。
4. 对 blob 原始字节直接计算 SHA-256。
5. 对按路径排序的 `[{path, sha256}]`规范 JSON 计算组 Aggregate。
6. 对稳定语义合同计算 Payload；时间、延迟、Token、费用和机器路径仍排除在外。

`build_file_group`继续只服务非发布的工作区散列；发布冻结统一使用 `build_git_file_group`。`_assert_worktree_matches`兼容入口已改为逐字节对比工作区和 Git blob，仅作诊断，不再作为冻结输入的证明。

## 19 个冻结组

| 冻结组 | 文件数 | R1 Aggregate SHA-256 |
|---|---:|---|
| agent_tool_orchestration | 13 | `5615bd91cba95529bfe00012cd99a54fd0f9c3e4fcfcb70a411d36715d67dbce` |
| all_production_python | 112 | `f82a2015f708f899510ab0c658821f2c6d3e53e642f8d9124a16f89d44dfceda` |
| constraint_checker | 5 | `18d1fda357cb8e68b6504b85e6ff8e96471a7add9f0da104603700e4171d729c` |
| constraint_resolution_clarification | 7 | `9cf516b4e2ba9368be94ce18abf3680b32100b231acb74289fdfd788cdaa1e58` |
| dependency_lock | 2 | `7e1b2afd1e8242fcc41a9b9f3a692b73e096a4d4c722ea779fcc5c7e05355cf5` |
| domain_pack_config | 10 | `822b494e9b0c6320b9f9c03148c0471f4b1bf97eb9c40c9d1e23e59b7fe47c7c` |
| evidence_check | 3 | `c977ef1fe3e249d60d83b2b8b1e66725a386cbaae7fa59ad70cb224bfd61a96b` |
| governed_data | 70 | `f581ac765a1d2e4d6e5458883b6b856de1d6f1393eabae7882eaa1e9c07ca052` |
| memory | 3 | `b22a0bc751344d429d8310418ca6b8a050009417b7b58268e788b0d327ef2dc6` |
| open_research_source_search_beta | 22 | `55f3e39be11549e040970f996f9134f481dd68d466d521ae2395bb058466b583` |
| product_pack_contract_and_runtime | 14 | `2e7457d03604c51d8a8e8ebc7a90499a433af2f5e25438302a1e0aad90aac90d` |
| product_ui_and_demo_contract | 6 | `fb5c5cf15669834d8e5f8b0e9eae5f5354dcc3b8de2a821b563f246d44f1682e` |
| prompt_contract | 3 | `8c577e1501b82a5f2d7d2788883f1fa5e41eb994bf3aaddd295a0579ed89de7b` |
| query_intent_product_reference_candidate_scope | 11 | `b60a872eee4cc7ff2d60424f8df7cbde297fcbc232c40aaae2c5ee65e14ad3ca` |
| ranker | 4 | `4a8cba4a1333b83545c4456dc07c6cdb2b528e9eb1b521239e9f802affee2715` |
| scoring_interface | 10 | `3ac62087ce033861c8cfaaac4774382fb1dd6a8a793ab53113a0451c16ce15fb` |
| test_baseline | 55 | `d5698799acc3919ca700b688860264efa088fb9b48e27e205d2f7e988d209291` |
| tool_schema_and_contracts | 14 | `f6957181de292f39b4709becc0dfb447650281fa2f7b20cb9e0eefbe92c55c91` |
| windows_scripts | 6 | `0368c621181fcc6f5996e5541541922cfc70d3de4934ab3d4746dc2d5c6d1382` |

成员出现 370 次、去重成员 267 个。R1 与旧 Manifest 相比只有 `dependency_lock`、`governed_data`、`scoring_interface` 和 `test_baseline` 四组因 6 个错误成员哈希而改变；其他 15 组相同。

## 跨环境结果

`core.autocrlf=true`、`core.autocrlf=false` 和显式 LF 工作树三种独立 clone 均得到：

- 同一 267 个唯一成员和逐文件 blob SHA-256；
- 同一 19 个 Aggregate；
- 同一 Payload `abf655017bdb0b27dfe3dd220d1e173e8a0e3e0ff2244590efc0d42d79fd6791`。

机器摘要见 [`v2_9h_r1_manifest_reproduction.json`](../../eval/results/v2_9h_r1_manifest_reproduction.json)，测试见 [`test_v2_9h_git_blob_manifest.py`](../../tests/unit/test_v2_9h_git_blob_manifest.py)。

## 复现

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run --project vendor/youtu-rag --frozen python -m smartbuy.reproducibility.v2_9h_rc3_manifest `
  --production-commit ba6606ae249bafc89c18b320935c767a3f756c34 `
  --output C:\ppv2run\rc3-manifest-r1-check.json
```

独立方应比较新 Payload、19 组 Aggregate 和 267 个唯一成员；不得继续使用旧 `4883f425…`。
