# V2-5C Quote-to-Span 运行说明

## 默认与边界

V1 默认路径不变。自然约束和 qwen-plus 回退仍需同时显式开启；程序只从现有百炼环境变量读取配置，不打印值。V2-5C 不改变 Checker、Evidence、Product Pack、Open Research 或默认编排器。

LLM Tool Call 只提交 `quote` 和结构化 Proposal。`span_start/span_end` 不在新 Tool Schema 中；`ConstraintProposal.source_span` 由服务端 `QuoteSpanResolver` 计算，并标记 `span_source=server_exact_quote`。

## 精确解析规则

1. `quote` 必须是用户原文的连续、逐字切片。
2. 唯一命中由服务端直接计算 start/end。
3. 未命中返回 `invalid / quote_not_found`，不模糊补救。
4. 重复命中必须提供从 1 开始的 `occurrence`；缺失或越界均不激活。
5. 最终强制验证 `original_text[start:end] == quote`。
6. `unsupported_request` 可合法返回，但永远不进入有效约束、长期 Memory 或 Checker。

## 显式启用

```powershell
$env:PROOFPICK_NATURAL_CONSTRAINTS_ENABLED = "true"
$env:PROOFPICK_CONSTRAINT_LLM_FALLBACK_ENABLED = "true"
$env:PROOFPICK_CLARIFICATION_ROOT = "C:\ai\proofpick-v2\clarifications"
```

请求仍需显式设置 `use_natural_constraints=true`。关闭两个功能开关即可无数据迁移恢复 V1；ReAct 与 LangGraph 共用同一 Validator 和 Resolver。

## 离线验证

```powershell
uv run --project vendor/youtu-rag --group dev python -m pytest smartbuy/tests/unit/test_v2_quote_span_contract.py smartbuy/tests/unit/test_v2_constraint_proposals.py -q
uv run --project vendor/youtu-rag ruff check smartbuy/constraint_proposals smartbuy/eval/run_v2_quote_span_live_eval.py
```

在线评测 Runner 会先校验冻结 SHA、确认确定性 Parser 对集合无输出，并拒绝把原始结果写进仓库。历史首测不得覆盖；真实调用只能在获得阶段授权和预算后执行。数据与命令口径见 [Live Holdout V2 数据卡](v2_5c_live_holdout_v2_data_card.md)和[V2-5C 报告](v2_5c_quote_span_report.md)。

## 安全说明

- 401/403 不重试；429、5xx、超时使用现有有限重试。
- 不记录 Key、Authorization、Workspace 值、隐藏 Prompt 或思维链。
- Tool Call 缺失、Function 名错误、自由文本返回、Schema 错误、quote 错误均 fail closed。
- pending/unsupported/invalid Proposal 不写长期 Memory；未确认歧义不进入 Checker。
