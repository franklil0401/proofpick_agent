# V2-1B LangGraph PoC

这是一个可整体删除的隔离实验，用于判断 LangGraph 是否适合 ProofPick V2 编排层。它不被
`smartbuy` 生产包、API、WebUI、SSE 主链或正式 Demo 导入。

## 安全边界

- 复用 `vendor/youtu-rag/uv.lock` 中已冻结的 `langgraph==1.0.5`，不修改依赖或锁文件。
- 需求解析和工具均使用确定性 Fake Provider/Fixture；外部 API 调用、Token 和费用均为 0。
- 只读复用 V1 `ConstraintNormalizer` 与 `CandidateConstraintVerifier`，SQLite 在 pytest 临时目录重建。
- 文件 Checkpoint 只写 pytest 临时目录；不写仓库运行数据，不接受不可信 checkpoint 文件。
- 不接入生产 ReAct、FastAPI、WebUI、SSE、Monitor 或四个正式 Demo。

## 运行

```powershell
uv run --project vendor/youtu-rag --frozen python -m pytest experiments/langgraph_poc/tests -q
uv run --project vendor/youtu-rag --frozen ruff check experiments/langgraph_poc
```

测试覆盖 StateGraph、条件边、SQL/KB 并行、确定性合并、执行预算、重试、降级、
Checkpoint、Interrupt、事件映射、Checker 不可绕过和 fail-closed。结果与采用建议见
[V2-1B 报告](../../smartbuy/docs/v2/v2_1_langgraph_poc_report.md)及
[ADR-0007](../../smartbuy/docs/adr/0007-langgraph-orchestration-decision.md)；机器可读摘要见
[`results/poc_summary.json`](results/poc_summary.json)。
