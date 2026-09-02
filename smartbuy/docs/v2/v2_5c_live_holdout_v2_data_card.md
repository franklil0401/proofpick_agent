# V2-5C Live Holdout V2 数据卡

最后更新：2026-09-02

## 用途与冻结

- 文件：`smartbuy/eval/v2_stage5c_live_holdout_v2.jsonl`
- Manifest：`smartbuy/eval/v2_stage5c_live_holdout_v2_manifest.json`
- 数量：20 条
- SHA-256：`ee84f96e7723a900fa640e73c130efffef38e285d89bdec7ef403c20c1df5732`
- 模型/采样：`qwen-plus`、`temperature=0`
- 策略：运行前冻结；只进行一次完整首测；看到结果后不得修改 Prompt、规则、代码或金标再宣称首测。

20 条覆盖中文复合约束、中英文混合、重复短语、Emoji、全角符号、省略显示单位、否定、双重否定、覆盖、取消、歧义、unsupported、Prompt Injection、当前输入覆盖长期偏好、品牌/地区/宽度/支架以及互相冲突的范围。冻结前确认确定性 Parser 对 20/20 无 Proposal，所有用例都进入真实 qwen-plus Function Calling。

## 金标与评分

每条金标只保存可审计 Proposal 字段：`field/operator/value/unit/strength/status/action`。分别报告：

- 全 Proposal 的 TP/FP/FN、Precision、Recall、F1；
- 清晰硬约束的字段级指标；
- 整条任务集合完全一致率；
- HTTP、Function、Schema、quote、服务端 span 和安全阻断指标。

集合中 unsupported 与 Prompt Injection 用于同时衡量表达和安全。合法的 inactive unsupported Proposal 可能与“空集合”金标产生任务级差异，但不会被计为安全误激活。

## 首次结果与不可变性

完整首测一次完成，机器可读摘要为 [`v2_stage5c_live_holdout_v2_first_results.json`](../../data/processed/v2_stage5c_live_holdout_v2_first_results.json)：Schema 20/20、服务端 span 28/28、清晰硬约束 F1 96.97%、任务 16/20、安全误激活 0。四个非全对任务和重复 Proposal 现象均原样保留，本轮没有进行后续调参或第二次完整运行。首测后的静态审查仅补充了 ProposalKind/action 不一致的 fail-closed 防线与离线测试，未根据失败修改 Prompt、Parser 或金标，也未重新计算首测。

## 与旧 12 条集合的关系

V2-5B 的 12 条已经在上一阶段暴露，原首次 5.41% F1、2/12 任务和 SHA 永久保留。V2-5C 只能将其称为 `live_provider_regression_v1`，不能称为未见 Holdout；本次 Quote 合同回归摘要见 [`v2_stage5c_exposed_regression_results.json`](../../data/processed/v2_stage5c_exposed_regression_results.json)。两组结果不得合并成总体准确率。

## 限制

- 仅 20 条显示器领域表达，不代表生产分布或通用自然语言理解。
- 真实模型即使 temperature=0 也不保证完全确定。
- 任务级 16/20，仍有 implied interface、歧义 Operator 和 inactive unsupported 表达口径差异。
- 数据不含敏感用户文本；不得把未来真实用户输入直接加入公开评测文件。
