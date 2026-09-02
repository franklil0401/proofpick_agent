# V2-6B Laptop SQLite、真实索引与工具闭环报告

最后更新：2026-09-02
阶段边界：仅工具级闭环；未运行 Laptop Agent E2E、V2-6A 冻结 Holdout、V2-6C、V2-7 或第三品类。

## 1. 结论

V2-6B 已用同一套配置驱动内核打通 Laptop Product Query → KB Search → qwen3-rerank → Evidence Check → Constraint Checker。Laptop SQLite 与 Chroma 均位于仓库外；Monitor 的 V1/V2 数据、索引、主 Agent 和历史实验未修改。

独立检索集在在线运行前冻结为 30 条，SHA-256 为 `7c70e4da196c17d3d09f6ee5c42162d16995963c2ee18c0c4254af55d6903e8c`。首次在线结果：Vector-only Recall@5 `30/30`、nDCG@5 `0.9766`；Reranker Recall@5 `30/30`、nDCG@5 `0.9973`。18 条要求精确 Top-1 的相似配置/地区任务错误 `0/18`，错误地区精确绑定 `0`，跨品类召回 `0`。这些是 12 个治理配置上的工具检索结果，不是完整 Agent 推荐准确率。

## 2. V2-6A 前置审计

### 2.1 42 个 Checker 支持字段的真实分类

用户给出的“33 个硬字段 + 3 个软偏好专属字段 + 6 个其余字段”不是当前 Pack 的互斥分区。只读审计得到：

- `hard_fields`：33 个。
- `soft_only_fields`：3 个，但其中只有 `primary_use` 同时出现在 42 个 `supported_fields`；`color_gamut`、`warranty` 的 `constraint_enabled=false`，不在 supported 集合。
- supported 但既不在 hard、也不在 soft-only 的字段实际为 8 个：`charger_w`、`depth_mm`、`height_mm`、`memory_type`、`operating_system`、`panel_type`、`storage_type`、`width_mm`。

因此 42 的真实集合关系是 `33 hard + 1 supported soft-only + 8 supported-but-unclassified`。V2-6B 没有篡改 V2-6A Pack 或历史报告去凑成 33+3+6。Checker 只允许 Pack 明确列入 `hard_fields` 的约束授予资格；其余 supported 字段可用于受控查询或证据展示，但作为硬淘汰条件时 fail closed。后续若要改变强度分类，必须独立版本化 Domain Pack 并重新冻结评测。

### 2.2 182/540 缺失属性

45 个派生属性 × 12 个配置仍为 540 个字段位；已知 358，null 182，完整率 `358/540 = 66.30%`。其中：

- 33 个硬字段 × 12（含 4 个始终存在的核心身份字段）共 396 位；已知 322、unknown 74，硬字段完整率 `322/396 = 81.31%`。
- 其余属性位中 unknown 108。
- 当前 Product Pack 没有显式 `not_applicable` 标记，因此这 182 个 null 全部按 `unknown` 处理，不能根据型号常识改成 N/A。
- `unsupported` 表示字段/操作符未被 Pack 声明；`unknown` 表示声明过但该配置没有治理值；`not_applicable` 只有未来数据显式声明后才能使用。
- 价格观察为 0，预算查询对 12/12 配置都返回 unknown，Checker 全部 fail closed；没有用 0、默认值或 LLM 推测补齐。

缺失最多的字段包括价格 12、四类专业测评字段各 12、保修 9、显存/刷新率/色域各 8、机身三维各 7、电池/适配器各 6。统计分母未改变。

### 2.3 132/132 与工具事实证据分母

V2-6A 的 132 个关键事实是运行前固定的 11 字段 × 12 配置：`product_id`、`brand`、`model_name`、`region`、`configuration_id`、`part_number`、`cpu_model`、`gpu_type`、`gpu_model`、`memory_gb`、`storage_gb`。它是“固定核心身份/配置字段的证据覆盖”，不是所有硬字段完整率；确实没有把缺失的其他硬字段放入 132 分母。

分别报告：

| 口径 | 结果 |
|---|---:|
| 全部属性位完整率 | 358/540（66.30%） |
| Checker 硬字段完整率 | 322/396（81.31%） |
| supported 字段的已声明事实证据覆盖 | 387/387（100%） |
| 全部实际治理事实证据覆盖 | 406/406（100%） |
| V2-6B 10 条组合任务中非 unknown 字段判断的证据覆盖 | 166/166（100%） |

### 2.4 冻结 30 条 Agent 任务

文件 `smartbuy/eval/v2_6a_laptop_cases.jsonl` 的 SHA-256 仍为 `3dfcc0f442bda2b6b4d2e96814a8973b415b3d8c8b9b33235924982fa1758d34`。split 在 V2-6B 开发前已经固定：Regression 10、Holdout 10、hard_negative 5、clarification 5。本阶段没有运行其中的 Holdout，也没有修改该文件。

## 3. SQLite 与 Product Query

`DomainReadonlyRepository` 使用 `mode=ro&immutable=1`、SQLite Authorizer、250 ms 进度超时和一条固定 SELECT，仅读取通用 EAV 表。字段、别名、单位、操作符和值域来自当前 Domain Pack；通用模块没有 CPU、GPU、内存等 Laptop 字段常量。

运行快照为 12 products、540 attributes、12 sources、406 evidence、0 prices；`integrity_check=ok`，外键违规 0。Product Query 返回完整 12 配置候选池，并携带 `domain_id/product_id/configuration_id/region/data_version/source_ids/evidence_ids`。最低内存/存储、最大重量、CPU/GPU、屏幕、接口、充电、升级性、地区/配置、多条件与 unknown 均通过定向测试。

## 4. 真实 Laptop 索引与检索

| 项目 | 值 |
|---|---|
| Domain Pack | `laptop/1.0.0` |
| Data Version | `laptop-governed-2026-09-02-v1` |
| Data Manifest | `d44373c8214cb996776445e5a5c1da60c233ce5d4b770c261399d913211ac1ad` |
| Index Version | `laptop-governed-2026-09-02-v1-embedding1024-v1` |
| Collection | `proofpick_laptop_v2_4e6d332c11bf8f7c` |
| Index Manifest Hash | `74a2c4467d53bd4ab265c61fd0cce42b0656bbb9a841c0f37bea5c5d86d8330f` |
| Documents / Chunks | 12 / 12（每个配置一份非重复治理事实文档） |
| Embedding | `text-embedding-v4`, 1024 维，批次 10+2 |

每个 Chunk 绑定 domain、product、configuration、region、source IDs、evidence IDs、data/index/pack version。构建完成并校验 Manifest/维度/数量/逻辑哈希后才原子切换 Laptop 指针；未完成、跨域、版本不一致或损坏指针均拒绝查询。Monitor collection 未被覆盖。

首次 30 条结果保存在 `smartbuy/eval/results/v2_6b_laptop_retrieval_first.json`，文件 SHA-256 为 `beb3a2c3801d8bdedf319d98374fc020513653175888a0476c0189b495788c39`；没有在看到结果后调金标或覆盖首测。

| 指标 | Vector-only | Vector + qwen3-rerank |
|---|---:|---:|
| Recall@5 | 30/30（100%） | 30/30（100%） |
| nDCG@5 | 0.9766 | 0.9973 |
| 精确 Top-1 错误 | 0/18 | 0/18 |
| 平均延迟 | 346.15 ms | 额外 256.63 ms |
| P95 延迟 | 621.85 ms | 额外 416.37 ms |

受控 Reranker 故障时保留向量顺序、`degraded=true`，精确 product filter 仍正确；该降级不改变 Checker 候选资格。

## 5. Evidence、Checker 与组合闭环

- Evidence Check 使用 Pack 驱动比较，保留 matched/not_matched/unknown/conflict；不存在数据时 unknown，非目标地区不能覆盖目标地区，同配置异值保留冲突证据。
- Checker 只接收完整结构化候选池。检索 Top-K 不是候选池上界，KB/Reranker/LLM 无恢复资格的权限。
- 10 条工具级组合任务全部通过：120 次候选检查、216 个字段判断，其中 166 个已知判断均有治理证据，50 个 unknown 均未变成 matched；产生 26 个合规候选，明确违规进入 eligible 为 0。
- 字段缺失、错误候选身份、跨域 Pack/Data、Evidence 冲突、数据库/索引异常均 fail closed；Checker fail-open 为 0。
- 这些是工具组合测试，不是完整 Agent 推荐能力。

## 6. 跨品类隔离

Laptop 与 Monitor 使用不同 Domain Pack、Data Version、Index Version 和 Collection。错误 Pack/Data 组合被拒绝；索引 metadata 的 domain filter 和校验使跨品类召回为 0。新增的 `DomainExecutionScope` 将 domain 纳入 Memory/Checkpoint key 并在恢复时验证 envelope；同一 user/session/thread 的 Monitor 与 Laptop key 不相同，跨域恢复被拒绝。默认 V1 Memory、Checkpoint 和编排入口未更改。

## 7. API、回归与边界

在线调用共 63 次：建库 Embedding 2、检索 Embedding 30、Reranker 30、降级验证 Embedding 1；成功 63、失败 0。input tokens 513,070，估算成本 `¥0.256535`。qwen-plus 调用 0。费用口径使用项目现有估算费率，不替代百炼账单。

- V2-6B 定向：8/8。
- `smartbuy/tests`：300/300；加入上游配置脱敏 node 的 CI 等价范围为 301/301。
- V1 Tag 的 18 个原始测试文件：94/94。
- Monitor Domain Pack、V2-5C/澄清/Checker/Memory 代表回归：92/92。

已知限制：仅 12 个治理配置；每配置一个综合事实 Chunk，尚未证明更大数据规模的切分策略；无 Laptop 价格观察；没有运行完整 Agent E2E、冻结 Holdout、真实 Open Research 或 Ranker。进入 V2-6C 前必须再次授权，并预先固定 Agent E2E 的配置、评分和费用。
