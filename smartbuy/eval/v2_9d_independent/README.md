# V2-9D RC2 第二次独立发布评测

本目录评测 `proofpick-v2-9c-rc2`，生产提交固定为 `2d41773981c69b815efa21c0bf21675d095b920d`。评测方不参与 V2-9C 生产修复。

- `trusted_cases.jsonl`：全新 90 条 Trusted 题，三品类各 30 条。
- `online_cases.jsonl`：全新 15 条真实联网题，三品类各 5 条。
- `case_manifest.json`：题量、哈希、未运行状态和重复检查。
- `scoring_policy.json`：首次运行前冻结的指标与联合门槛。
- `release_candidate.json`：把题集、评分器、RC2、V1 与仓库外运行时绑定在一起。
- `runner.py`：只追加首次结果；不修改生产实现。
- `validate_freeze.py`：独立读取治理数据，验证 Gold 完整性和候选集合。

Online 同时考核两层能力：安全终止不等于完成取证。只有产生 Open Evidence 且全部请求字段得到验证，才计为实际完成；总完成率至少 50%，每个品类至少 40%。

纪律：定义、Schema、评分器和运行器必须先提交并推送；首次结果不可覆盖；失败后题集只能转为 exposed regression，不能调参重跑冒充独立首测。本分支不修改 `feature/proofpick-v2`、`main`、V1 Tag、生产代码、Prompt、数据或既有结果。

最终结果：

- [Trusted 首次结果](../results/v2_9d_independent_trusted_first.json)：72/90，未通过联合门槛。
- [Online 评测器事故](../results/v2_9d_independent_online_harness_failure.json)：8 题后因评测 Schema 漏掉 70 字符上限而中止。
- [Online RC2 首次完整结果](../results/v2_9d_independent_online_first_rc2.json)：安全终态 15/15，实际完成取证 0/15。
- [机器摘要](../results/v2_9d_independent_summary.json)、[运行 Manifest 审计](../results/v2_9d_runtime_manifest_audit.json)与[独立发布报告](../../docs/v2/v2_9d_second_independent_rc2_evaluation.md)。
