# ProofPick V2 Portfolio Release Notes（草案）

> 仅供 V2-9B 独立评测与后续人工审核；尚未创建 Tag 或 GitHub Release。

## Highlights

- 三个 Domain Pack：Monitor、Laptop、Headphone，共用约束、Scope、工具、Evidence、Checker、Ranker 与 Memory 契约。
- 统一 ProofPick Web UI：Trusted/Open、候选资格、淘汰原因、排序贡献、来源与脱敏工具轨迹。
- 数据驱动扩展：版本化 Product Pack、字段级 Evidence Ledger、仓库外 SQLite/Chroma 与原子版本指针。
- 有界 Agent：默认 ReAct，LangGraph 可显式开启；主动澄清、Checkpoint 和安全降级共享同一 Checker。
- Open Research：受控官方来源搜索、静态网页抽取和请求级临时 Evidence，与 Trusted 路径强隔离。
- 五个脱敏 Demo 和 Windows 干净克隆/离线回放。

## Selected evidence

- Headphone 30 条冻结检索任务 Recall@5：Vector 86.39% → Reranker 97.78%。
- 三品类交叉污染 0；错误 Domain/Data/Index 组合 fail closed。
- V2-5C 新 20 条 Live Holdout 首测：清晰硬约束 F1 96.97%，任务 16/20，安全误激活 0。
- Ranker What-if 12/12 不改变 Checker 集合；计分事实 Evidence 追溯 117/117。

这些是不同阶段、不同分母的工程证据，不是生产 SLA。V2 最终独立发布指标必须等待 V2-9B，不能在发布前补写。

## Known limitations

- 每个品类当前仅 12 个 UI 可查询治理配置。
- Open Research 受搜索索引、地区和静态页面可访问性影响。
- 当前价格/库存不保证实时；过期或无法核验时为 unknown。
- 默认 ReAct 未切换为图原生 LangGraph；本地 SQLite Checkpoint 非生产多租户存储。
- 本版本为可复现作品集/MVP Release Candidate，不构成购买建议。

## Attribution

FastAPI、经典 WebUI、文件/知识库基础设施与基础 Agent/RAG 组件来自固定版本 Youtu-RAG；ProofPick 自研边界和 MIT 归属见 `THIRD_PARTY_NOTICES.md`。数据许可单独记录。
