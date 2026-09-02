# V2-5 新表达评测集说明

## 冻结契约

- 文件：`smartbuy/eval/v2_stage5_expression_cases.jsonl`
- 数量：50（Regression 30、Holdout 20）
- SHA-256：`9c03937ba7897b9e390f2e73099d394f331bfd696ea763cfc1c3b4b27741eb75`
- 冻结时间：2026-09-02T13:20:00+08:00
- 政策：先冻结再运行；看到结果后只能修代码，不得修改 query、split 或 gold。

每条用例包含 case_id、split、query、可选 previous 和 expected Proposal。评分对 field/operator/value/unit/strength/status/action 做精确集合比较，额外 Proposal 计 FP，遗漏计 FN；任务全对要求无 FP/FN。歧义和 unsupported 另行检查是否错误激活。

## 覆盖范围

中文/阿拉伯数字、金额上下限与范围、英寸/Hz/W/cm、4K/QHD 别名、OLED 否定与双重否定、USB-C 视频/供电、品牌包含/排除、支架、地区、软偏好、覆盖、取消、模糊阈值和不支持字段。

## 结果文件

- `v2_stage5_first_results.json`：旧解析器实现前基线，F1 43.33%。
- `v2_stage5_initial_implementation_results.json`：V2-5 首次实现，F1 94.64%、任务 46/50，失败未覆盖。
- `v2_stage5_postfix_results.json`：修复后 55/55 字段、50/50 任务。

三份结果用途不同，不能用最终结果覆盖历史失败。完整解释见 [V2-5 报告](v2_5_constraint_clarification_report.md)。
