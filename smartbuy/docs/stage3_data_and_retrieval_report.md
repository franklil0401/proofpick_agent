# 阶段 3：显示器数据质量与检索基线报告

- 日期：2026-08-26
- 受众：技术维护者
- 范围：受治理数据、可重建 SQLite、Youtu-RAG/Chroma 知识库、Vector/Reranker 检索
- 不在范围：ReAct、多工具 Agent、Memory、完整推荐、确定性硬约束执行

## 技术结论

阶段 3 的数据与检索主链路已达到进入阶段 4 的条件：12 个型号全部有自制事实卡和字段级来源，SQLite 可幂等重建，正式索引的 60 个文档与 60 个 Chroma chunks 一致；在 36 条有金标的检索任务上，Reranker Recall@5 为 98.38%，nDCG@5 为 95.41%，均超过开发指南的建议门槛。

最终自动化结果为 23 passed，3 条警告均来自上游依赖弃用；`smartbuy/` 与阶段 2 核心供应商 Provider 文件 Ruff 检查通过。

结果也揭示一个必须保留的负面结论：固定 `0.20` Reranker 分数阈值在 4 个无答案/无关问题上拒答 0 次。阶段 3 只能证明“相关证据更容易排到前面”，不能证明“系统知道何时没有证据”。这不阻断数据和检索基线，但会约束阶段 4 的输出策略。

## Reranker 显著改善排序，但组合召回仍有缺口

| 指标 | Vector-only | Vector + qwen3-rerank | 建议目标 |
|---|---:|---:|---:|
| Recall@5 | 0.8912 | **0.9838** | ≥0.90 |
| nDCG@5 | 0.8170 | **0.9541** | ≥0.85 |
| 相似型号 Top-1 错误率 | 0.5000 | **0.0000** | 越低越好 |

分母为 36 条 `expected_model_ids` 非空的固定 JSONL 用例；先对 chunks 做向量检索，再按 `model_id` 去重得到最多 10 个候选，Reranker 输出前 5 个型号。Recall@5 是每条用例前五命中金标型号集合的比例再取平均；nDCG@5 使用二元相关度并按每条用例的理想排序归一化。

Vector-only 的主要失败来自多条件和多型号查询，例如宽度阈值与“至少 4K + 90W”组合。Reranker 修复了大部分排序，但 `c020` 未在前五覆盖全部三个窄机身型号，`c021` 未覆盖全部四个至少 4K/90W 候选。该结果支持阶段 4 使用 SQLite 做确定性筛选，而不是继续把自然语言向量排序当作 SQL 条件执行器。

## 无依据拒答是当前最明确的质量缺口

4 条 `should_abstain=true` 用例覆盖“不存在的 USB-C 能力”、内置摄像头、人脸识别、十年烧屏保证和完全无关的浇水器问题。固定阈值 `0.20` 的拒答准确率为 **0/4**。其中不存在的 USB-C 组合仍得到 0.8973 的最高 Reranker 分数，说明“查询与文档措辞相似”不等于“文档满足组合命题”。

这是一项描述性检索测试，不是完整回答质量测试。阶段 4 应在候选返回后查询 SQLite 并逐字段验证；阶段 6 再评估“字段证据完整 + 约束满足 + 最低相关度”的联合拒答规则。禁止通过在本批 40 条结果上调阈值并宣称成功来过拟合。

## 数据和 SQLite 已具备可审计的重建链路

| 检查 | 结果 |
|---|---:|
| 型号 / 品牌 / 来源 | 12 / 4 / 16 |
| 价格观察 / 字段级证据 / 事实卡 | 4 / 180 / 12 |
| 核心字段缺失率 | 0% |
| 来源/证据外键错误 | 0 |
| 重复 URL 或治理内容 | 0 |
| 跨地区补充来源 | 1，已显式标注边界 |
| SQLite 行数 | products 12；prices 4；sources 16；evidence 180 |
| SQLite 外键 / integrity | 0 个违规 / `ok` |
| 连续重建逻辑 SHA-256 | 两次均为 `3d37a2c3d89326d04f2e1fdf49f96e250fc4d109a64627359bad935e5c16bb13` |
| 人工抽查 | 3/12 型号（25%） |

核心字段为尺寸、分辨率、刷新率、面板、OLED、USB-C 存在性和 USB-C 视频能力。`release_date` 等非核心字段仍有缺失，详细分布和许可边界见[数据卡](data_card.md)。质量检查结果支持当前 Demo 范围，不支持“市场数据完整”或“实时价格准确”的结论。

## 索引契约和真实运行结果

正式知识库使用 `text-embedding-v4`、显式 1024 维、cosine、切分版本 `monitor-fact-card-h2-v1`。每张事实卡按 5 个 H2 章节形成文档，共 60 文档/60 chunks；构建状态 `completed`、错误 0，构建器与 Chroma 计数相等。实际 Chroma 复核显示 12 个唯一型号、地区标签 `CN/US/CA`，每个 chunk 均包含完整的 12 项要求元数据。

3 型号小样本首次在构建后更新集合元数据时失败：Chroma 不允许在 `modify` 中再次提交不可变的 `hnsw:space`。最小修复是只在创建集合时固定 cosine，后续仅写数据、模型、维度和切分版本；复跑得到 15/15 chunks，随后全量一次成功。该过程没有改变 Youtu-RAG 业务逻辑。

Reranker 降级用例 `c039` 强制绕过远端重排，前五结果与向量顺序一致并标记 `degraded=true`，证明服务失败时 KB 检索仍可返回向量结果。

## 方法、调用和成本

正式评测共 40 条：36 条有金标检索任务、4 条拒答任务。查询 Embedding 的 40 条单批请求被接口以 HTTP 400 拒绝且没有重试；改为固定每批最多 10 条后成功。该限制进入脚本契约。

最终可审计评测运行：

| 操作 | 调用数 | Input tokens | 平均延迟 | P95 延迟 | 估算成本（元） |
|---|---:|---:|---:|---:|---:|
| `text-embedding-v4` 查询批次 | 4 | 892 | 254.8 ms | 324.9 ms | 0.000446 |
| `qwen3-rerank` | 39 | 44,374 | 191.6 ms | 372.2 ms | 0.022187 |
| **最终评测合计** | **43** | **45,266** | — | — | **0.022633** |

最终 40 条端到端平均延迟为 219.9ms，P95 为 344.8ms；查询 Embedding 批处理总耗时 1,019.3ms，按 40 条均摊后计入每条延迟。`c039` 是离线强制降级，不调用 Reranker。

建库全量使用 60 次 Youtu 小请求、5,225 tokens、估算 0.0026125 元。成功小样本另有 15 次、1,371 tokens、约 0.0006855 元；第一次小样本在向量化完成后才遇到 Chroma 元数据错误，因此按相同输入估算另有最多 1,371 tokens/0.0006855 元。为补齐按模型用量审计，40 条最终评测在首次同指标运行后重跑一次，追加 0.022633 元。加上两次被 HTTP 400 拒绝且无成功 usage 的请求，阶段 3 可观测估算总成本不超过 **0.0493 元**，远低于 10 元上限。费用按项目当前估算费率计算，不等同账单结算值。

## 限制、稳健性和已知失败

- 12 个型号是验证性样本，不是全市场抽样；指标只对固定数据版本和 40 条任务有效。
- Reranker 改善相关性排序，但不能执行数值逻辑、库存时效或“所有条件同时满足”的确定性判断。
- 拒答 0/4 是非阻断但高优先级风险；阶段 4 不得把 Top-1 直接写成推荐结论。
- 价格只有 4 条一次性观察，必须显示 `observed_at` 和库存状态。
- 正式评测前没有先运行独立的 3～5 条评测 dry run；实际先出现 40 条 Embedding 批量 HTTP 400，之后才改为 10 条有界批次。这是流程偏差，已保留而不粉饰；后续批量评测必须先跑小样本。
- Youtu 当前按章节逐文档调用 Embedding，60 chunks 产生 60 次小请求；成本低但调用效率可优化。
- 本阶段没有生成自然语言答案，因此不评估证据引用正确率、硬约束满足率或完整任务完成率。

## 建议下一步

1. 阶段 4 优先接入 SQLite/Text2SQL，把预算、尺寸、OLED、分辨率和 USB-C 视频/供电作为确定性条件，而不是继续调检索阈值。
2. 输出层必须区分“匹配”“不匹配”“未知”，显示价格时间、地区版本、冲突来源和 Reranker 降级状态。
3. 为无答案判断设计字段覆盖检查；先用 4 个现有拒答样本和新增困难负例做小样本，再运行全量。
4. 保留当前 Vector-only 结果作为基线，后续任何 Agentic RAG 指标都使用同一数据版本和评测集比较。

## 待后续回答的问题

- Text2SQL 与向量召回的候选融合顺序怎样减少 `c020/c021` 这类多目标漏召回？
- 哪种不依赖全量结果过拟合的证据充足性规则能识别“不存在的组合条件”？
- 价格数据扩充后，过期阈值应按来源类型还是商品类别配置？

## 可复现命令

```powershell
python -m smartbuy.scripts.build_stage3_data
python -m smartbuy.scripts.validate_stage3_data
python -m smartbuy.db.build_database --output C:\ai\smartbuy-stage3\smartbuy_monitors_v1.sqlite

$env:PYTHONPATH="$PWD;$PWD\vendor\youtu-rag"
vendor\youtu-rag\.venv\Scripts\python.exe -m smartbuy.scripts.build_stage3_index --mode pilot
vendor\youtu-rag\.venv\Scripts\python.exe -m smartbuy.scripts.build_stage3_index --mode full
vendor\youtu-rag\.venv\Scripts\python.exe -m smartbuy.scripts.verify_stage3_index
vendor\youtu-rag\.venv\Scripts\python.exe -m smartbuy.eval.run_retrieval_eval
```

真实建库与评测命令会产生少量费用，不应在 CI 默认执行。离线结果分别保存在 `index_manifest.json` 和 `stage3_retrieval_results.json`；运行数据库和 Chroma 索引不进入 Git。
