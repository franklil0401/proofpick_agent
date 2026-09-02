# V2-5C 服务端 Quote-to-Span 技术报告

最后更新：2026-09-02

分支：`feature/proofpick-v2`

范围：修复真实 qwen-plus 字符下标合同，运行 12 条已暴露回归与新的 20 条一次性 Live Holdout；未进入 V2-6。

## 1. 不可覆盖的历史基线

V2-5B 首次真实结果继续永久保留：Schema 10/12、raw span 1/20、字段 Precision/Recall/F1 5.26%/5.56%/5.41%、任务 2/12、安全误接受 0。问题不是 HTTP 或 Function 名，而是让概率模型维护 Python 字符下标无法形成稳定 grounding。

原 12 条从本阶段起正式归类为 `live_provider_regression_v1`。它们已经暴露，不能再称为 Holdout；原文件、SHA、首次结果和金标均未改动。

## 2. 实现合同

- 新 Tool Schema 保留 Function 名 `submit_constraint_proposals`，移除可信 `span_start/span_end`，增加精确 `quote`、可选一基 `occurrence` 和严格 `proposal_kind`。
- `QuoteSpanResolver` 只在原始字符串上完全匹配；唯一命中计算真实 Python start/end，零命中 `quote_not_found`，重复无 occurrence 则拒绝静默选首项。
- 新 Proposal 使用 `span_source=server_exact_quote`；最终验证原文切片与 quote 字节对应的 Python 字符串完全一致。
- `unsupported_request` 使用合法 `field_name=unsupported` 分支；枚举外字段、错误 Function 名、自由文本和虚构 quote 继续 fail closed。
- ambiguous Proposal 允许 Operator/Value 为空但保持 inactive；当前输入覆盖既有条件由服务端确定性适配，不依赖模型知道 Memory。
- ReAct 与 LangGraph 共享同一 Resolver/Validator；旧 Fake Provider 通过兼容 Adapter 迁移。

不采用 Levenshtein、Embedding、LLM 二次定位、自动补字或规范化字符串下标直接映射原文。

## 3. 12 条已暴露回归

该组在 Quote 合同落地后运行一次，属于已暴露回归而非新 Holdout：

| 指标 | 结果 |
|---|---:|
| HTTP / Function / Schema | 12/12 / 12/12 / 12/12 |
| quote 可解析 / 服务端 span | 19/20 / 19/20 |
| 全 Proposal TP/FP/FN | 11/9/7 |
| 全 Proposal P/R/F1 | 55.00% / 61.11% / 57.89% |
| 清晰硬约束 P/R/F1 | 75.00% / 75.00% / 75.00% |
| 任务级全对 | 5/12 |
| 平均 / P95 延迟 | 4,935.469 / 8,150.772 ms |
| Token / 成本 | 8,448 input + 2,522 output / ¥0.0118024 |

它把 span 从历史 1/20 提高到 19/20，并暴露了 nullable ambiguity、服务端覆盖动作、unsupported 表达和支架规范值等兼容问题。本轮在冻结新 Holdout 前完成了最小通用修正；受 32 次调用上限约束，没有再次重跑该暴露集合。机器摘要明确保留这一时序。

## 4. 新 Live Holdout V2 首测

新 20 条在运行前冻结，SHA-256 为 `ee84f96e7723a900fa640e73c130efffef38e285d89bdec7ef403c20c1df5732`。确定性 Parser 20/20 返回空；完整首测只运行一次，结果出现后没有修改 Prompt、Parser 或金标，也没有重跑。首测后的静态审查只补充 ProposalKind/action 不一致的 fail-closed 校验和离线测试，不用于覆盖或重新计分首测。

| 指标 | 首次结果 |
|---|---:|
| HTTP / Function 名 | 20/20 / 20/20 |
| Tool Schema | 20/20（100%） |
| quote 唯一命中 | 26/28 |
| quote 可解析 / 服务端 span | 28/28 / 28/28（100%） |
| 全 Proposal TP/FP/FN | 23/3/2 |
| 全 Proposal P/R/F1 | 88.46% / 92.00% / 90.20% |
| 清晰硬约束 TP/FP/FN | 16/0/1 |
| 清晰硬约束 P/R/F1 | 100% / 94.12% / 96.97% |
| 任务级全对 | 16/20 |
| 平均 / P95 延迟 | 4,039.681 / 7,080.144 ms |
| Token / 成本 | 17,852 input + 3,434 output / ¥0.0211496 |

四个非全对任务原样保留：一线通任务漏提 `has_usb_c`；未知 PD 门槛输出 inactive `gte` 而金标 Operator 为空；两条 Prompt Injection 被表达为 inactive unsupported Proposal 而金标为空。重复短语任务正确定位三个 quote，但产生三个相同软约束 Proposal，集合评分折叠后任务通过；这是仍需独立治理的去重限制。

## 5. 安全门

两组真实运行中以下指标均为 0：虚构 quote 被接受、非 Domain Pack 字段激活、ambiguous 未确认进入 Checker、unsupported 静默激活、Prompt Injection 权限/Checker 改写。新 Holdout 的自由文本绕过与错误 Function 名接受也为 0。

服务端 span 没有降低后续校验：quote 通过后仍必须经过 Proposal Kind、字段、Operator、类型、单位、值域、Domain Pack 和 Resolver；pending/unsupported/invalid 不写长期 Memory。现有澄清回归确认恢复后已完成收费工具重复执行为 0。

## 6. 调用、成本与边界

V2-5C 共 32 次 qwen-plus 调用：26,300 input tokens、5,956 output tokens、估算 ¥0.032952，低于 ¥1 上限。没有输出或提交 Key、Authorization 或 Workspace 值；没有启动需要释放的 FastAPI/MinIO 进程。

这不是生产准确率：新 Holdout 只有 20 条且任务级为 16/20；真实模型不保证确定。V2-5B 历史、暴露回归和新 Holdout 必须分别报告，不得合并成“总体 100%”。

## 7. 质量门与结论

进入 V2-6 的本阶段数值门已满足：Schema 100% ≥95%，服务端 span 100% ≥95%，清晰硬约束 F1 96.97% ≥90%，全部安全误接受为 0。V2-6 仍需用户另行授权；本提交不进入下一阶段，也不切换默认编排器。

最终门禁：V2-5/5B/5C 与澄清定向 48/48，Checker/Memory/澄清代表回归 68/68，`smartbuy/tests` 276/276，加入上游配置安全 node 的 CI 等价范围 277/277，V1 原始 94/94。Ruff、Compileall、JavaScript 12/12、PowerShell AST 5/5、Markdown 相对链接 330/330 均通过；敏感凭据、禁止运行产物和遗留监听端口为 0。
