# RC3 独立评测在出题前被冻结合同阻断

## 技术结论

`proofpick-v2-rc3` **暂时不能进入独立 Holdout 评测**。生产 Commit `ba6606ae249bafc89c18b320935c767a3f756c34` 和 Tree `84766c5d8840b50a27c612e24379b6dd63736741` 均与交接文档一致，保存的 Semantic Manifest Payload 也能自洽地得到 `4883f425...e266b367`；但是，它不能从不可变生产 Git blob 或新的 Windows 克隆中复现。

这属于发布冻结证据缺陷，不等同于 Agent 功能失败。按照 RC3 Handoff 中“任一冻结合同不一致时停止”的规则，本轮在创建题集、Gold 和评分器之前终止，没有调用任何模型或搜索 API。

## 审计范围与口径

- 文档 Commit：`f1df16d8536b9ab6a0dafe7c8362f204db33a7e7`
- 冻结生产 Commit：`ba6606ae249bafc89c18b320935c767a3f756c34`
- 冻结生产 Tree：`84766c5d8840b50a27c612e24379b6dd63736741`
- 冻结 Payload：`4883f4251c8cb1f4dc6b86b6777b3d19ace74bee92943129c1146fc4e266b367`
- 冻结组：19 组
- 成员出现次数：370
- 去重成员：267

独立审计没有使用当前工作区内容替代冻结对象，而是逐项读取 `production_commit:path` 对应的 Git blob 原始字节，计算单文件 SHA-256，再按 Manifest 的排序和规范 JSON 规则重算组聚合哈希。

评测者没有参与 V2-9E～V2-9H 的开发，但已经从此前对话了解历史聚合指标和部分失败类型。因此后续即使冻结修复完成，也只能表述为“非开发方、全新题集、首次结果不可覆盖”，不能声称对项目历史完全盲测。

## 四个冻结组没有绑定生产 Git blob

共有 6 个唯一成员的 Manifest SHA-256 与生产 Git blob 不一致，影响 4 个冻结组。

| 冻结组 | 文件 | Manifest 与 Git blob | 换行证据 |
|---|---|---|---|
| dependency_lock | `vendor/youtu-rag/pyproject.toml` | 不一致 | 不是简单的全文件 LF→CRLF 结果 |
| governed_data | `stage6_metrics_summary.csv` | 不一致 | Manifest 精确匹配 Git blob 的 CRLF 变体 |
| governed_data | `stage7_demo_presentation_regression.json` | 不一致 | Manifest 精确匹配 Git blob 的 CRLF 变体 |
| scoring_interface | `v2_8_headphone_engineering.schema.json` | 不一致 | Manifest 精确匹配 Git blob 的 CRLF 变体 |
| scoring_interface | `v2_8_headphone_engineering_policy.json` | 不一致 | Manifest 精确匹配 Git blob 的 CRLF 变体 |
| test_baseline | `.github/workflows/ci.yml` | 不一致 | 不是简单的全文件 LF→CRLF 结果 |

四个纯换行变体说明，至少部分冻结哈希来自开发机器的工作区字节，而不是生产 Commit 中的 Git blob。`pyproject.toml` 和 CI 文件还存在非纯换行差异，不能只通过统一 EOL 解释或修复。

完整单文件哈希见[机器审计结果](../../eval/results/v2_9i_rc3_freeze_audit_failure.json)。

## 干净 Windows 克隆不能复现 Payload

在 `core.autocrlf=true` 的新 Windows 克隆中，使用仓库提供的生成器和同一生产 Commit 重新生成 Manifest：

| 检查 | 冻结值 | 独立重算 |
|---|---|---|
| Production Tree | `84766c5d...` | 相同 |
| Payload SHA-256 | `4883f425...` | `1b77000d...` |
| 19 组聚合哈希 | 冻结值 | 19/19 不同 |

这里的 19/19 不同不表示 267 个文件的 Git 内容都被修改，而是生成器对工作区原始字节敏感。Windows 换行转换会改变大量文本文件的字节，即使 `git status` 仍然干净。

## 根因位于哈希输入，不在生产功能

当前 `build_file_group` 通过 `Path.read_bytes()` 读取工作区文件；前置 `_assert_worktree_matches` 使用 `git diff --quiet`。Git diff 会按属性和换行规则比较规范化内容，因此“diff 为空”并不能证明工作区原始字节等于 Git blob。

结果是：

1. Manifest 声称绑定生产 Commit，但成员哈希实际可能绑定某台机器的 checkout 字节。
2. `core.autocrlf` 或文件历史换行状态变化会改变 Payload。
3. 顶层 Payload 自哈希通过，只能证明 JSON 内部自洽，不能证明它准确描述生产 Tree。

严重性为 **High**：不影响现有 Agent 运行，却破坏了独立评测对“被测对象未变化”的证明。如果忽略该问题继续出题，后续发布结论无法严格绑定 RC3 冻结对象。

## 开发方所需的最小修复

1. 从固定 `production_commit` 直接读取 Git blob 原始字节计算成员 SHA-256，不再使用工作区文件字节作为冻结输入。
2. 组成员集合继续从固定 Commit 的 `git ls-tree` 获取。
3. 对 blob 哈希、成员列表、组聚合和顶层 Payload 分别校验。
4. 新增 `core.autocrlf=true`、`core.autocrlf=false` 和 LF 工作树三种复现测试，三者必须得到相同 Payload。
5. 对上述 6 个成员明确比较旧 Manifest、生产 blob 和修复后 Manifest，不能只重新生成后跳过差异解释。
6. 保持生产 Commit/Tree 不变，发布一个新的 Manifest 修订和 Handoff Commit；旧 `4883f425...` 必须永久保留为失败历史。

建议将修复标记为 `proofpick-v2-rc3-manifest-r1`，不要把新 Hash 覆盖成旧 Hash，也不要因此声称 RC3 已通过功能评测。

## 本轮停止状态

- Trusted 新题：0
- Online 新题：0
- Gold：0
- 模型、Embedding、Reranker、搜索 API：0 次
- 费用：¥0
- 生产代码修改：0
- Holdout 运行：0
- 服务端口：8000、8088、9000、9001 均未监听

冻结修复后，应由独立评测分支先重新执行本报告的 Git-blob 审计。只有 Commit、Tree、267 个唯一成员、19 组聚合和顶层 Payload 全部一致，才能开始创建并冻结新的 Trusted/Online 任务。
