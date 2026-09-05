# V2-9H-R1 RC3 独立评测交接修订

## 使用这个身份

- RC：`proofpick-v2-rc3`
- Manifest Revision：`r1`
- 生产 Commit：`ba6606ae249bafc89c18b320935c767a3f756c34`
- 生产 Tree：`84766c5d8840b50a27c612e24379b6dd63736741`
- R1 Payload：`abf655017bdb0b27dfe3dd220d1e173e8a0e3e0ff2244590efc0d42d79fd6791`

旧 Payload `4883f4251c8cb1f4dc6b86b6777b3d19ace74bee92943129c1146fc4e266b367`是不可复现的失败历史，禁止再作为冻结门禁。旧 Manifest、旧 Handoff 和独立失败审计都不得删除或覆盖。

## 评测前必须重新审计

1. 从 R1 文档 Commit 读取[机器 Manifest](../../eval/results/v2_9h_rc3_semantic_runtime_manifest_r1.json)。
2. 核对 `production_commit^{tree}`严格等于冻结 Tree。
3. 独立运行 `git ls-tree -r -z --name-only`，核对 267 个唯一成员和 370 次组内成员出现。
4. 对每个 `production_commit:path`使用 `git cat-file blob`读取原始字节，核对所有成员 SHA。
5. 重算 19 个组 Aggregate 和顶层 R1 Payload。
6. 在 `core.autocrlf=true`、`false` 与 LF checkout 中重复；三种结果必须完全一致。
7. 确认 Agent、Prompt、Pack、数据、Checker 和评分结果相对原 RC3 生产 Commit没有变化。

任一步失败都应在出题前停止。全部通过后，才可以由独立评测方创建和冻结全新任务；本次 R1 修复没有创建或预览题目。

## 继续沿用的 RC3 规则

- Trusted Multi-domain Decision Core 是 Stable/default；Online Research 是 Experimental/Beta。
- Trusted 与 Online 分开评分；安全 unknown 不计为网页研究完成。
- V2-9B/V2-9D 的 90+15、V2-9C/E/F 暴露回归和 V2-9G PoC 都不能作为新 Holdout。
- 首次失败、恢复和评测器事故永久保存；开发方不得预览或修改未来任务、Gold 或评分规则。
- 未经用户授权，不创建 PR、Tag、Release，不合并 `main`。

详细算法与六文件说明见 [R1 修复报告](v2_9h_r1_manifest_freeze_repair_report.md)和 [R1 Manifest](v2_release_candidate_rc3_manifest_r1.md)。
