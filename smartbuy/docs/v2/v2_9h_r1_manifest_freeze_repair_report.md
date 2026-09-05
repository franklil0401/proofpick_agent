# V2-9H-R1 Manifest 冻结修复报告

## 结论

独立评测分支 `eval/v2-9i-independent-rc3` 在出题前正确阻断了 RC3：旧 Manifest 内部自洽，但成员哈希来自 checkout 字节，无法证明不可变 Git Tree。R1 已把成员枚举和内容散列分别改为 `git ls-tree` 与 `git cat-file blob`；生产 Commit `ba6606ae…` 和 Tree `84766c5d…` 完全不变。

旧 Payload `4883f4251c8cb1f4dc6b86b6777b3d19ace74bee92943129c1146fc4e266b367`及旧 JSON 原样保留为失败历史。新规范 Payload 是 `abf655017bdb0b27dfe3dd220d1e173e8a0e3e0ff2244590efc0d42d79fd6791`。

## 根因与修复

旧 `build_file_group` 使用 `Path.read_bytes()`，而 `_assert_worktree_matches` 使用会执行文本规范化的 `git diff --quiet`。因此 Windows 工作区即使 `git status` 干净，CRLF 或混合换行字节仍可能进入 Manifest。

R1 的 `build_git_file_group`只接受生产 Commit 的 `git ls-tree`成员，并直接散列该 Commit 的 blob 原始字节。新的精确工作区检查逐文件比较 `Path.read_bytes()`和 blob，只用于解释 checkout 差异；Manifest 不再读取工作区文件。

## 六个旧不匹配成员

| 文件 | 旧 Manifest | 生产 blob / R1 | 原因 |
|---|---|---|---|
| `vendor/youtu-rag/pyproject.toml` | `7f327844…` | `a34be624…` | blob 为 201 个 LF；旧工作区为 199 个 CRLF + 2 个 LF，属于混合换行，不是全文件纯转换 |
| `stage6_metrics_summary.csv` | `c52ede8e…` | `d30744f1…` | 5 个 LF 被 checkout 转为 5 个 CRLF |
| `stage7_demo_presentation_regression.json` | `ff74739f…` | `ed336e18…` | 828 个 LF 被转为 828 个 CRLF |
| `v2_8_headphone_engineering.schema.json` | `a0a1deb1…` | `7514d1d8…` | 78 个 LF 被转为 78 个 CRLF |
| `v2_8_headphone_engineering_policy.json` | `c0c0b9ca…` | `73d35ef8…` | 24 个 LF 被转为 24 个 CRLF |
| `.github/workflows/ci.yml` | `55990cdf…` | `9eaa9e4e…` | blob 为 100 个 LF；旧工作区为 84 个 CRLF + 16 个 LF，属于混合换行 |

完整旧/新 SHA-256 位于[机器复现摘要](../../eval/results/v2_9h_r1_manifest_reproduction.json)和独立分支的原失败审计中。六个旧 SHA 都精确匹配生成旧 Manifest 时的工作区字节；R1 六个 SHA 均精确匹配生产 Git blob。

## 跨 EOL 复现

测试创建三份独立 checkout：

1. `core.autocrlf=true`，并把探针文件工作区字节显式置为 CRLF；
2. `core.autocrlf=false`；
3. `core.autocrlf=false + core.eol=lf` 的 LF 工作树。

三者的成员路径/成员 SHA、19 组 Aggregate、Semantic Contract 和 Payload 全部一致。第一次测试夹具因 Windows 跨盘 `--local` hardlink 返回 `Improper link`，未触及算法断言；改为 `--no-hardlinks` 后最终定向测试 `5/5` 通过。

## 变更边界

- 修改：通用 Semantic Manifest Git object 读取、V2-9E/V2-9H 生成器、R1 测试与冻结文档。
- 未修改：Agent、Prompt、Domain/Product Pack、数据、索引、Evidence、Checker、Ranker、Memory、评测题、Gold 和历史结果。
- 新 Holdout、独立评测运行、模型/API 调用、PR、Tag、Release：均为 0。

## 质量门结果

- Manifest 定向：最终 `5/5`；其中 Git blob/EOL 新增测试 `2/2`。
- 全仓 CI 等价：`518/518`，仅有 3 条既有依赖弃用警告。
- V1 Tag 所含 18 个原始测试文件：当前 `101/101`。
- Ruff、Compileall：通过；JavaScript `13/13`；PowerShell AST `6/6`。
- Markdown 相对链接：`487/487`；`git diff --check`通过。
- 高置信凭据命中 `0`；新增数据库、索引、缓存、日志、模型或密钥产物 `0`。
- 真实 API 调用 `0`，费用 `¥0`。

R1 只修复冻结可复现性，不代表 RC3 已通过功能独立评测。独立方必须先按 [R1 Handoff](v2_9h_r1_rc3_handoff.md)重新完成 blob 审计。
