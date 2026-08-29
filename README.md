# ProofPick — 基于 Agentic RAG 的多源消费决策 Agent

ProofPick 把自然语言消费需求转成可追溯约束，动态编排结构化查询与证据检索，
再用确定性安全门阻止 LLM 推荐违反硬条件的商品。
`SmartBuy` 是当前的显示器选购演示场景与 Python 模块。

[![CI](https://github.com/franklil0401/proofpick_agent/actions/workflows/ci.yml/badge.svg)](https://github.com/franklil0401/proofpick_agent/actions/workflows/ci.yml) [![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/) [![License: MIT](https://img.shields.io/badge/License-MIT-2ea44f.svg)](LICENSE) [![Portfolio MVP](https://img.shields.io/badge/Status-Portfolio%20MVP-8A2BE2)](smartbuy/docs/release_report.md)

[![ProofPick Constraint Checker 脱敏结果回放](smartbuy/docs/assets/constraint-checker.png)](https://franklil0401.github.io/proofpick_agent/)

> 主图来自已保存的本地 API 验证结果，是**脱敏结果回放，不是实时模型调用**；
> 不包含 Prompt、Key、Workspace ID 或私人路径。

| 先看这里 | 入口 | 能看到什么 |
|---|---|---|
| 在线体验 | [GitHub Pages 脱敏回放](https://franklil0401.github.io/proofpick_agent/) | Agent 工具轨迹、证据、候选与 Constraint Checker 结果 |
| 五分钟 Demo | [固定案例与备用步骤](smartbuy/docs/demo_guide.md) | 单文档核验、组合多跳、Memory、冲突拒答 |
| 核心实现 | [核心代码入口](#核心代码入口) | ReAct、Text2SQL、KB、证据、约束复核与 Memory |

当前状态是**可复现的作品集 / MVP 原型**：中国大陆显示器单一场景，
12 个治理型号、40 条冻结自然任务。
它不是生产级系统、实时电商平台或全品类购物助手。

| 核心结果 | 精确结果 | 口径 |
|---|---:|---|
| Agent 对照 | Fixed RAG **51/120（42.50%）** → 增强组 **92/120（76.67%）** | 40 条冻结任务 × 3 次，同数据与配置 |
| 二阶段检索 | Recall@5 **89.12% → 98.38%** | 36 条人工核验、含多正确候选的检索用例 |
| 约束安全 | 阶段 6 增强组违规候选推荐 **0/43** | 首次自然任务；仅当前数据和支持字段 |
| 自动化质量门 | **95 tests passed** | 阶段 7 发布检查记录，另有 Ruff/编译/脚本检查 |

指标保留原始分母，只用于说明本仓库实验结果；
`34/40`、`92/120` 和 `0/43` 均不是生产准确率或 SLA。
完整口径见[作品集指标文档](smartbuy/docs/portfolio_metrics.md)。

## 为什么它是 Agent，而不是普通 RAG

- **会规划和改道：** 有界 ReAct 根据问题与工具观察选择 Text2SQL、KB Search、Evidence Check，并按缺失字段继续依赖式多跳，而非固定“检索一次 → 拼接 Prompt”。
- **有状态且可审计：** 会话约束、明确确认的长期偏好、父子步骤、工具状态和 `matched/not_matched/unknown/conflict` 四态结果进入结构化轨迹；隐藏思维链不展示。
- **模型不能越过安全门：** Constraint Checker 从完整工具候选池独立读取只读 SQLite 与证据记录；LLM 只能解释合规候选，Checker 异常时 fail closed。

## 系统架构

![ProofPick Agent 从需求到确定性复核的系统架构](smartbuy/docs/assets/proofpick-architecture.png)

`qwen-plus` 负责需求理解、规划和解释，
`text-embedding-v4` 与 `qwen3-rerank` 负责二阶段检索。
SQLite、证据记录和 Checker 负责可复核事实与最终硬约束资格。
Web Search 当前仅提供 `unavailable/degraded` 接口，KB + SQL 是稳定主链路。

## 核心代码入口

- [`smartbuy/agent/react.py`](smartbuy/agent/react.py)：实现有最大步骤、工具白名单、预算和停止条件的 ReAct 执行循环。
- [`smartbuy/tools/text2sql.py`](smartbuy/tools/text2sql.py)：校验只读单条 `SELECT`，限制表列、超时和返回行数，并支持受控模板降级。
- [`smartbuy/tools/kb_search.py`](smartbuy/tools/kb_search.py)：封装向量召回、qwen3-rerank 二阶段排序与失败回退。
- [`smartbuy/tools/evidence_check.py`](smartbuy/tools/evidence_check.py)：按型号、地区和字段输出 matched/not_matched/unknown/conflict 四态证据。
- [`smartbuy/constraints/verifier.py`](smartbuy/constraints/verifier.py)：从完整候选池执行不可被 LLM 覆盖的确定性硬约束复核。
- [`smartbuy/memory/store.py`](smartbuy/memory/store.py)：管理会话约束和用户明确确认、可查看/关闭/删除的长期偏好。
- [`smartbuy/eval/`](smartbuy/eval/)：包含冻结数据、四组 Runner、确定性 Scorer、统一账本、缓存与故障注入评测入口。

## 精简实验结果

40 条自然任务由 16 条 regression 与 24 条首次完整运行前冻结的 holdout 组成。
四组使用相同数据、模型、温度、`as_of` 和评分规则，每组重复 3 次；
主实验不使用热缓存。

| 实验组 | 三次聚合 E2E | 能力边界 |
|---|---:|---|
| Direct LLM | 46/120（38.33%） | 仅 qwen-plus，无数据或工具 |
| Fixed RAG | 51/120（42.50%） | 固定向量召回 + Reranker + LLM |
| Agentic RAG | 81/120（67.50%） | ReAct + SQL + KB + Evidence，无最终 Checker |
| Agentic RAG + Checker | **92/120（76.67%）** | 完整增强链路 |

增强组相对 Fixed RAG 高 **34.17 个百分点**，
相对 Agentic RAG 高 **9.17 个百分点**；阶段 7 当前代码的独立发布候选为 **34/40**。
这些结果没有覆盖首次失败，也没有为了展示重新运行收费评测。
实验配置、失败样本、成本、缓存与 13/13 故障注入见[阶段 6 报告](smartbuy/docs/stage6_evaluation_and_resilience_report.md)和[发布报告](smartbuy/docs/release_report.md)。

## Windows 四行启动

```powershell
git clone https://github.com/franklil0401/proofpick_agent.git C:\ai\proofpick
Set-Location C:\ai\proofpick
.\smartbuy\scripts\preflight.ps1; .\smartbuy\scripts\bootstrap.ps1
.\smartbuy\scripts\start.ps1
```

前置条件是 Windows 11、Python 3.12、Git、`uv` 与仓库外 MinIO，
以及已配置但绝不写入仓库的 `Qianwen_api_key` / `Qianwen_workspace_id`。
首次知识库构建会调用 Embedding；完整配置、仓库外运行目录、停止命令和复现证据见
[Runtime Manifest](smartbuy/docs/runtime_manifest.md)。

启动后访问 `http://127.0.0.1:8000/`，在 WebUI 中启用 **SmartBuy**；`/health` 与 `/monitor` 用于健康和脱敏轨迹检查。

## Youtu-RAG 上游与本人新增能力

| Youtu-RAG 上游提供 | ProofPick 在本仓库新增 |
|---|---|
| FastAPI / WebUI | 阿里云百炼 LLM、Embedding、Reranker Provider |
| 文件与知识库基础设施 | 治理后的显示器数据、统一证据模型与可重建 SQLite |
| 基础 Agent / RAG 组件 | 有界 ReAct、安全 Text2SQL、四态 Evidence Check、分层 Memory |
| 通用服务与监控框架 | 确定性 Constraint Checker、四组评测、缓存、故障注入、统一账本与 Windows 脚本 |

上游通过固定 Commit 的 Git subtree 保留在 `vendor/youtu-rag/`。
归属、许可证与少量展示接线差异见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)。
本仓库不把上游能力描述为个人从零实现。

## 三个主要限制

- **范围有限：** 当前只有显示器一个场景、12 个治理型号；GraphRAG、Neo4j、第二品类、自动下单和公网多租户均未实现。
- **动态信息有限：** Web Search 尚未接入真实凭据，价格仅有 4 条带 `observed_at` 的离线观察，不保证实时价格或库存。
- **仍是实验性 MVP：** 增强组三次聚合为 92/120，发布候选为 34/40；LLM 路由与延迟不构成生产准确率、可用性或性能 SLA。

## 详细文档与 License

- [五分钟 Demo 指南](smartbuy/docs/demo_guide.md)：固定输入、预期轨迹、耗时、截图和失败备用步骤。
- [Runtime Manifest](smartbuy/docs/runtime_manifest.md) 与 [Data Card](smartbuy/docs/data_card.md)：Windows 配置、版本、运行路径、数据构建及许可边界。
- [作品集指标](smartbuy/docs/portfolio_metrics.md) 与 [发布报告](smartbuy/docs/release_report.md)：每个数字的分母、Commit、允许表述、历史失败和发布复现。
- [开发指南](smartbuy/docs/development/DEVELOPMENT_GUIDE.md)：架构决策、阶段 DoD、测试命令与风险；当前真实结构见[项目结构](smartbuy/docs/development/PROJECT_STRUCTURE.md)。

本项目自行开发代码采用 [MIT License](LICENSE)。数据许可独立记录；感谢 TencentCloudADP 的 [Youtu-RAG](https://github.com/TencentCloudADP/youtu-rag)。
