# 作品集与简历指标口径

最后更新：2026-08-27

用途：集中记录可复核数字、分母、来源和禁止表述。所有数字只适用于当前显示器数据版本与评测配置，不能外推为生产 SLA。

## 可使用指标

| 指标原文 | 分子 / 分母 | 实验组与数据 | 证据 Commit | 报告 | 建议表述 | 禁止表述 |
|---|---:|---|---|---|---|---|
| Top-5 平均召回率由 89.12% 提升到 98.38% | 36 条含检索金标任务上的宏平均 | Vector-only vs Vector + `qwen3-rerank`；`monitor-cn-2026-08-26-v1` | `068224003fd99e41c3020423cdca7faa6a16af1d` | [阶段 3](stage3_data_and_retrieval_report.md) | “在 36 条含多正确候选的检索用例上，二阶段重排将 Top-5 平均召回率从 89.12% 提升至 98.38%。” | “检索准确率 98.38%”“适用于所有商品” |
| 增强组完成 92/120，Fixed RAG 完成 51/120 | 40 条冻结任务 × 3 次 | A/B/C/D 公平对照；D vs B | `5fcb05fa5e9fda7a2b9d7b1c4c9df507301081af` | [阶段 6](stage6_evaluation_and_resilience_report.md) | “40 条冻结任务、每组重复 3 次，Agentic RAG + Checker 完成 92/120，较 Fixed RAG 的 51/120 高 34.17 个百分点。” | “准确率提升 34.17%”“系统准确率 76.67%” |
| 增强组相对 Agentic RAG 提高 9.17 个百分点 | 92/120 vs 81/120 | D vs C，同一冻结集 | `5fcb05fa5e9fda7a2b9d7b1c4c9df507301081af` | [阶段 6](stage6_evaluation_and_resilience_report.md) | “加入确定性安全门后，三次聚合 E2E 从 81/120 提升到 92/120。” | “Checker 让模型准确率达到 100%” |
| 违规候选推荐从 10/38 降为 0/43 | 首次自然任务 C vs D | 阶段 6 首次 40 条，不同组分母不同 | `5fcb05fa5e9fda7a2b9d7b1c4c9df507301081af` | [阶段 6](stage6_evaluation_and_resilience_report.md) | “当前数据版本和已支持字段上，首次评测中违规推荐由 Agentic RAG 的 10/38 降至增强组 0/43。” | “生产环境零违规”“所有约束 100% 安全” |
| Checker 三次字节一致 40/40，模型调用为 0 | 40 / 40 | 固定输入、候选池、SQLite、证据和 as_of | `5fcb05fa5e9fda7a2b9d7b1c4c9df507301081af` | [阶段 6](stage6_evaluation_and_resilience_report.md) | “确定性 Checker 在 40 个固定输入上三次字节一致 40/40，不产生额外模型调用。” | “整个 Agent 完全确定” |
| 故障注入 13/13 | 13 / 13 | 模拟 401/403/429、Provider、SQL、存储、Memory、Web、Checker、缓存等 | `5fcb05fa5e9fda7a2b9d7b1c4c9df507301081af` | [阶段 6](stage6_evaluation_and_resilience_report.md) | “13 类受控故障注入均进入预期重试、降级或 fail-closed 路径。” | “生产高可用”“零故障” |
| 公共 KB 热缓存 5/5 输出一致 | 5 / 5 | 5 条公共、稳定 KB 查询；不含主实验与动态价格 | `5fcb05fa5e9fda7a2b9d7b1c4c9df507301081af` | [阶段 6](stage6_evaluation_and_resilience_report.md) | “5 条公共 KB 查询的热缓存平均延迟由 1441.682ms 降至 10.436ms，输出 5/5 一致。” | “系统整体提速 138 倍”“生产 P95 为 10ms” |

## 发布候选结果（作品集说明，不替换阶段 6）

- Stage 7 发布代码与干净 Windows 复现 Commit：`79e5575198919d323d22b6cb23719540610ea966`；最终文档/推送状态以后续交付 Commit 为准。
- 当前最终增强组在相同冻结 40 条上单次发布候选为 **34/40**，其中 regression **16/16**、holdout **18/24**。
- 字段级硬约束为 **183/183**；违规候选推荐 **0/56**；工具选择 **36/40**；依赖式多跳 **23/23**。
- 首次发布候选的 unknown/conflict 为 **2/5**。之后仅做输出层定向修复：`s4-011`、`h6-015`、`h6-018` 各 1/1，以及两个展示收敛案例 2/2；没有重跑并覆盖首次 34/40。
- 发布候选单次 34/40 不能与阶段 6 三次 92/120 合并，也不能写成生产级 85% SLA。

## 不可使用的宣传语

- 系统准确率 100%。
- 生产环境零违规或生产级 SLA。
- 支持实时全网价格/库存或真实 Web Search。
- 支持所有商品类别。
- GraphRAG/Neo4j 已实现。
- 缓存让整个系统提速 138 倍。
