# V2-9B 独立发布评测

本目录由未参与 V2 生产实现的评测方创建。评测对象固定为 `proofpick-v2-9a-rc1`，生产提交为 `dac24123b82683c6708f0d487d9ab9753b172aed`。

- `trusted_cases.jsonl`：90 条新题，Monitor/Laptop/Headphone 各 30 条。
- `online_cases.jsonl`：15 条真实 Source Search / Web Extractor 任务，各品类 5 条。
- `case_manifest.json`：题集数量、哈希与未运行状态。
- `scoring_policy.json`：首测前冻结的指标口径和联合门槛。
- `trusted_case.schema.json`、`online_case.schema.json`：严格数据契约。
- `generate_cases.py`：只读取冻结治理数据，不调用生产 Checker/Resolver 生成金标。

纪律：定义、Schema、评分器和运行器必须在首次 E2E 前提交；首测结果只追加，不覆盖；若 RC 未通过，只能形成失败报告并交回开发分支，不得在本分支修业务逻辑后重跑冒充首次结果。
