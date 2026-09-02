# ADR-0015：服务端精确 Quote-to-Span 合同

- 状态：Accepted
- 日期：2026-09-02
- 范围：ProofPick V2-5C

## 背景

V2-5B 要求 qwen-plus 返回字符下标。真实首测虽有 12/12 HTTP 和 12/12 Function 名，但 Tool Schema 仅 10/12、原文 span 仅 1/20、字段 F1 仅 5.41%、任务 2/12。模型下标与 Python 原文字符位置不稳定，继续修补下标规则会把 grounding 安全建立在不可验证的概率输出上。

## 决策

1. LLM 只逐字复制 `quote`，不再提供可信下标；新 Tool Schema 移除 `span_start/span_end`。
2. `QuoteSpanResolver` 在原始字符串中做完全匹配并由服务端计算 Python 字符位置。最终强制满足 `original_text[start:end] == quote`。
3. 唯一命中直接解析；零命中为 `quote_not_found`；多次命中必须带一基 `occurrence`，否则不静默选第一个。禁止模糊匹配、Embedding、二次 LLM 猜测和自动补字。
4. `unsupported_request` 通过 `field_name=unsupported` 和 `unsupported_field_text` 合法表达，但永不激活；枚举外字段继续 fail closed。
5. Span 只是 grounding 的第一道门。字段、Operator、类型、单位、值域、Domain Pack、澄清状态和 Checker 边界仍由确定性代码校验。
6. ReAct 与 LangGraph 共用同一 Resolver；旧 Fake Provider 通过 Adapter 兼容。V1 默认路由不变。

## 结果

新 20 条一次性 Live Holdout V2 首测为：Schema 20/20、服务端 span 28/28、清晰硬约束 Precision/Recall/F1 为 100%/94.12%/96.97%、任务 16/20；虚构 quote、非领域字段、未确认歧义、unsupported 和 Prompt Injection 的错误激活均为 0。完整结果与失败样本见 [V2-5C 报告](../v2/v2_5c_quote_span_report.md)。

原 V2-5B 的 5.41% F1、2/12 任务和 1/20 span 永久保留。原 12 条已暴露，只能作为 `live_provider_regression_v1`；不能再称为未见 Holdout。

## 代价与限制

- 精确 quote 要求模型复制原文；无法精确复制时会安全拒绝，可能降低召回。
- 重复短语需要 occurrence；V2 不做模糊消歧。
- 新 Holdout 仍有 4 个非全对任务，且重复软约束出现了重复 Proposal；本阶段不针对首测调参。
- SQLite、Checkpoint、编排器默认值和 Checker 均未因本 ADR 改变。

## 拒绝的方案

- 信任 LLM 下标：真实首测已证明不稳定。
- 对错误 quote 做模糊匹配：可能把模型虚构文本错误绑定到用户原文。
- 用第二次 LLM 调用猜位置：增加成本且不能形成确定性证据。
- 对新 Holdout 失败立即调 Prompt 并重跑：破坏首次评测口径。
