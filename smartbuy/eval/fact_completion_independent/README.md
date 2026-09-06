# Fact Completion 修复独立真实回归

仅复测原四条已暴露任务001、005、007、011，不是新Holdout、RC冻结或发布评测。本轮无论通过与否均不执行剩余79条Trusted或15条Online。

固定生产Commit：`02e97a2c793ba75dfad5ece15e5df665652808bf`；Tree：`7e6b036bc3255714cd378e887ae8b9779a5ef98a`。与旧RC4结果分目录保存，旧生产身份和3/4成绩保持不变。

先逐一核对固定Commit所有Git成员与工作区执行字节，再验证原有三品类运行索引。生产冻结对象使用原始Git blob哈希，工作区只允许换行转换差异。独立分支仅增加评测材料，不修改固定生产文件。

沿用v2_9i_independent原题、金标、原score.py及获授权的score_v2引用格式兼容。输入、评分与四条顺序不变。新Runner只允许exposed阶段，固定新生产身份、新Run ID、独立会话及输出目录；不允许切入unseen阶段。

默认入口仍为HTTP POST `/api/smartbuy/portfolio/run`，通过HTTPX ASGITransport挂载实际FastAPI Router执行。真实云端Provider不替换，不额外启用自然约束、Domain Pack或LangGraph。Memory关闭、不恢复Checkpoint、不使用热缓存包装。

本轮最多¥1，包含在此前用户允许的有界评测预算内。每题开始前保留¥0.25，单题180秒超时；Provider按现有配置有限重试，评测器不重跑任务。首次结果排他创建，任何安全命中先停止并只读核查。

验收：四条任务全对、所需字段及引用完整、硬约束未丢失、无违规推荐或Scope/Checker越界。补查完成矩阵、无重复字段核验、报告终态一致性另做只读审计，不修改冻结评分或把诊断输出填回真实答案。

报告沿用用户要求的Markdown；四例精确结果使用文字说明，不制作容易误导为泛化趋势的图表。可复现脚本与机器结果代替临时Notebook。

```powershell
uv run --project vendor/youtu-rag --frozen python -m smartbuy.eval.fact_completion_independent.preflight
uv run --project vendor/youtu-rag --frozen python -m smartbuy.eval.fact_completion_independent.run exposed
```

必须先冻结并提交评测器、先通过生产离线门禁，再执行真实调用。结束后保留完整结果并等待是否继续未运行题的授权。
