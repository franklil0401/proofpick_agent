# V2-5B 评测口径审计与真实 qwen-plus 验证报告

最后更新：2026-09-02

分支：`feature/proofpick-v2`

范围：只审计 V2-5 口径、冻结并首测 12 条 Live Holdout、验证真实 qwen-plus Function Calling；未进入 V2-6。

## 1. 原 46/50 的四条失败

首次实现结果的 `TP/FP/FN=53/4/2`、失败摘要和冻结金标可以唯一还原下表的计分字段；完整机器可读记录见 `v2_stage5b_initial_failure_audit.json`。

| case | 分组 | 原句 | 金标 | 首次实际 | 原因与修复 |
|---|---|---|---|---|---|
| `v2c-reg-016` | Regression | Type-C 可以给笔记本充电 | PD 功率 `needs_confirmation` | 金标 + `has_usb_c=true` | 不再从该自然语言充电表达额外推导接口字段 |
| `v2c-reg-017` | Regression | USB-C 至少 90 瓦供电 | PD `>=90W` | 金标 + `has_usb_c=true` | 该表达只形成用户明确提出的 PD 字段 |
| `v2c-reg-022` | Regression | 只看国行版本 | `region=CN, action=add` | 值相同但 `action=override` | 系统默认替换只写入 diff，不篡改用户动作 |
| `v2c-reg-023` | Regression | 我要美国版 | `region=US, action=add` | 值相同但 `action=override` | 同上 |

四条全部属于 Regression。原 20 条 Holdout 在首次 50 条完整运行中为 20/20，之后没有根据 Holdout 修改规则，仍可称为原 Holdout 首次结果。它只运行了一次；后续 `50/50` 是修复 Regression 后的全套回归，不能冒充第二次未见 Holdout。

## 2. 新 Live Holdout 冻结

- 文件：`smartbuy/eval/v2_stage5b_live_holdout.jsonl`
- 数量：12 条，覆盖复合约束、中英混合、上下文单位、一线通功率不明、互相冲突、歧义、unsupported、双重否定、覆盖/取消与两类 Prompt Injection。
- SHA-256：`3043c7c3f13d4f45f23f64c7ba1416bbda4162e10b9f5ca5b757ba828fd2a889`
- 冻结后预检：确定性 Parser 对 12/12 均返回空，确保每条真实进入 qwen-plus 回退。
- 文件和金标在查看在线输出后没有改动；完整首测只运行一次，结果永久保存在 `v2_stage5b_live_holdout_first_results.json`。

## 3. 真实 qwen-plus 首测

调用链为 qwen-plus → 强制 `submit_constraint_proposals` → JSON Schema 检查 → 精确原文 span → Monitor Pack 字段/类型/单位/Operator/值域 → Resolver。模型为 `qwen-plus`、`temperature=0`；密钥与 Workspace 值未进入输出、日志或仓库。

| 指标 | 首次结果 |
|---|---:|
| HTTP 成功 | 12/12 |
| Function 名正确 | 12/12 |
| JSON 参数通过 Tool Schema | 10/12 |
| raw span 精确定位 | 1/20 |
| Proposal TP/FP/FN | 1/18/17 |
| 字段 Precision / Recall / F1 | 5.26% / 5.56% / 5.41% |
| 任务级全对 | 2/12 |
| 平均 / P95 延迟 | 3,525.803 / 6,081.975 ms |
| Token | 6,864 input + 1,736 output |
| 估算成本 | ¥0.0089632 |

两条 Schema 失败是模型在 unsupported/Prompt Injection 用例中输出了枚举外字段；验证器将其标记 invalid 且不激活。主要兼容问题是模型输出的 span 下标无法对应 Python 原文字符位置，19/20 条被 fail closed。首测只保留脱敏 Proposal 结果，没有保存完整 Prompt、模型自由文本或原始响应正文。

当前要求覆盖旧偏好的 Live 用例因 span 无效被安全拒绝，旧偏好继续有效；因此不能宣称“真实回退的当前输入优先级已通过”。离线确定性专项仍通过，但不能替代本次在线结论。

## 4. 安全结果与最小兼容修复

- 虚构/错误 span 被接受：0。
- 非 Domain Pack 字段被激活：0。
- ambiguous/needs_confirmation 未确认进入 Checker：0。
- unsupported 静默激活：0。
- Prompt Injection 修改权限、Evidence 或 Checker：0。
- 自由文本、缺失 Tool Call、错误 Function 名均通过离线测试返回空 Proposal，不从文本猜硬约束。

真实首测后没有修改 Prompt、span 规则、金标或确定性 Parser，也没有重跑 Live Holdout。唯一生产兼容修复是适配器现在显式校验 Function 名必须为 `submit_constraint_proposals`；这属于独立 fail-closed 加固，不改善或覆盖首测分数。

## 5. 四类指标不得合并

1. V2-5 前的旧 Normalizer 冻结基线：F1 43.33%，不是 qwen 指标。
2. 原 50 条 V2-5 首次实现：46/50；原 Holdout 首次 20/20，四个失败均为 Regression。
3. Regression 修复后的原 50 条离线规则回归：55/55 Proposal、50/50 任务；这是开发回归，不是独立 Live Holdout。
4. 新 qwen-plus Live Holdout 首次：2/12、F1 5.41%、Schema 10/12、span 1/20；必须单独展示。

可用于简历的表述：在 50 条先冻结中文表达上，确定性解析与安全门回归为 50/50，并建立了真实 qwen-plus 首测和 fail-closed 审计。不得表述为“qwen 约束理解准确率 100%”“自然语言约束生产可用”或把四类数据合并成总体 100%。

## 6. 结论与限制

HTTP、强制 Function 名和安全阻断通过，但真实 qwen-plus 的 Schema 遵循与 span 稳定性没有通过功能门槛。V2-5 的确定性路径可继续默认关闭地保留；LLM 回退仍是实验能力，不具备进入 V2-6 或对外宣称稳定支持任意口语约束的条件。

后续若获授权，应新建独立修复阶段，先设计不依赖模型字符下标、仍能拒绝虚构文本的 span 合同，再用新的定向集验证；不得覆盖本次首测，也不得在本提交中调整 12 条 Live Holdout。

## 7. 回归与质量门禁

- V2-5/V2-5B 定向：28/28。
- `smartbuy/tests`：256/256；加入上游配置脱敏测试的 CI 等价范围：257/257。
- V1 Tag 中 18 个原始测试文件：94/94。
- Checker、Memory、阶段 4 与澄清代表集：61/61。
- 原 50 条规则评测重新计算：55/55 Proposal、50/50 任务，冻结哈希不变。
- Ruff、Compileall、JavaScript 12/12、PowerShell AST 5/5、Markdown 相对链接 314/314 通过。
- 敏感凭据、禁止运行产物命中 0；V1 冻结数据、原 50 条金标、46/50 首次结果和默认编排器均未修改。

## 8. V2-5C 后续口径（追加，不改写首测）

V2-5C 已获授权修复 Quote 合同。由于本页 12 条及其输出已经暴露，它们从 V2-5C 起统一称为 `live_provider_regression_v1`，不能再作为新的未见 Holdout；本页的首次 SHA、5.41% F1、2/12 任务、10/12 Schema 和 1/20 span 均永久保留。新的独立首测口径见 [V2-5C 报告](v2_5c_quote_span_report.md)与 [Live Holdout V2 数据卡](v2_5c_live_holdout_v2_data_card.md)。
