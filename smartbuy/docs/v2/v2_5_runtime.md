# V2-5 运行说明

## 默认状态

自然约束入口默认关闭，V1 行为不变；默认编排器仍是 `react`。启用前需正常配置现有百炼变量，但规则可以在不调用模型的情况下处理已覆盖表达。程序只检查配置，不应打印变量值。

```powershell
$env:PROOFPICK_NATURAL_CONSTRAINTS_ENABLED = "true"
$env:PROOFPICK_CONSTRAINT_LLM_FALLBACK_ENABLED = "true"
$env:PROOFPICK_CLARIFICATION_ROOT = "C:\ai\proofpick-v2\clarifications"
```

调用 `/api/smartbuy/chat` 时还必须显式发送：

```json
{
  "query": "27 寸左右，预算两三千吧",
  "stream": true,
  "session_id": "demo-session",
  "thread_id": "demo-thread",
  "use_natural_constraints": true
}
```

收到 `status=interrupted` 后，用相同 user/session/thread 再请求并传入 `resume_value`。可传布尔确认/拒绝，也可传规则可识别的具体补值，如 `32 英寸以下`。恢复前不会调用正式 Agent 工具，完成后 pending 文件被清除。

## 本地状态与安全

- 默认澄清目录：`C:\ai\proofpick-v2\clarifications`，必须位于仓库外。
- 文件按 user/session/thread 的 SHA-256 键隔离；严格 Pydantic JSON，禁止 Pickle。
- pending Proposal 不写长期 Memory；只有现有长期偏好接口的用户显式确认仍可写入。
- Monitor 不保存原文、值、身份或 Checkpoint key；SSE 不展示隐藏系统 Prompt/思维链。
- qwen-plus 回退每轮最多 1 次；401/403 不重试，429/5xx/超时沿用已有百炼有限重试。

## LangGraph 与回滚

若显式设置 `PROOFPICK_ORCHESTRATOR=langgraph`，澄清使用现有 interrupt/checkpoint；ReAct 使用等价的仓库外 pending 状态。两者都把同一 `ConstraintResolution` 交给现有 Agent，并继续执行现有强制 Checker 终态。

关闭 `PROOFPICK_NATURAL_CONSTRAINTS_ENABLED` 并在请求中去掉 `use_natural_constraints`，即可无数据迁移恢复 V1。不要删除 V1 数据、索引或 Memory；清理未完成澄清只需删除明确的仓库外 clarification 文件，不能对宽泛目录递归删除。

## 离线验证

```powershell
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_v2_constraint_eval
uv run --project vendor/youtu-rag python -m pytest smartbuy/tests/unit/test_v2_constraint_proposals.py smartbuy/tests/integration/test_v2_clarification_orchestration.py -q
```

冻结集、结果与限制见 [阶段报告](v2_5_constraint_clarification_report.md)。真实 LLM 的字符定位已在 V2-5C 改为服务端精确 Quote-to-Span；新合同、离线验证和不可覆盖首测口径见 [V2-5C 运行说明](v2_5c_quote_span_runtime.md)与[V2-5C 报告](v2_5c_quote_span_report.md)。
