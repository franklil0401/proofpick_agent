# ProofPick V2-1A 实现级设计

最后更新：2026-08-30

状态：**设计完成，待用户评审；未编写 V2 生产代码**

基线：`v1.0.0-portfolio` / `d51b6668a6a45c1b01ef4e64da3c4b9ac84ed10c`

当前分支：`feature/proofpick-v2`

## 1. 范围、证据与结论

本文是 V2-1A 的实现契约，不代表所述目录或能力已经存在。设计依据按优先级来自当前任务、[V2 开发流程](V2_DEVELOPMENT_PROCESS.md)、[V2 目标与路径](ProofPick_V2_目标与实现路径.md)、V1 代码/测试/数据和历史文档。V1 的 Agent、RAG、Checker、Memory、数据、评测与历史结果在本轮均未修改。

结论：V1 的安全边界是可复用的，但“字段定义”同时散落在需求解析、SQL、Evidence、Checker、Memory、报告、数据派生与评测中。V2 应先建立“通用内核只识别契约，品类差异全部由 Domain Pack 提供”的边界；不能只把常量搬到一个大配置文件，也不能让 LLM 成为字段、证据、资格或版本的事实来源。

### 1.1 仓库事实与文档冲突

| 项目 | 仓库证据 | 处理决定 |
|---|---|---|
| V1 冻结 | `main`、`origin/main`、V2 分支起点和 Tag 均指向 `d51b666...`，GitHub Release 已存在 | 以 Git 事实为准；V1 历史不改 |
| V2 分支 | `feature/proofpick-v2` 已创建并跟踪同名远端 | 修正 V2 文档中“尚未建立分支”的过期状态 |
| V2 开发状态 | 分支相对 V1 起点无业务差异；本轮仅 V2-1A 文档 | “尚未开始生产代码”仍成立；不得写成 Domain Pack/LangGraph 已实现 |
| V1 文档链接 | 原流程文档的 `../v1/README.md` 在仓库中不存在 | 改为已存在的 V1 发布报告链接，不创建虚假归档 |
| V1 Runtime Manifest | 记录的是 V1 `main` 和阶段 7 运行事实 | 保持原样；V2 分支状态由本目录记录，避免改写 V1 证据 |

## 2. 显示器硬编码清单

下面的“迁移”都是后续 V2-1C 的建议，不是本轮代码变更。行号基于 V1 冻结 Commit；后续代码变化时以 Git blame 为准。

| 类别与位置 | 当前行为 | 迁移目标 | 风险 |
|---|---|---|---|
| 商品字段、单位、别名：[constraints/normalize.py](../../constraints/normalize.py) 18–67、70–72、250–410 | 固定 12 个可复核字段；写死分辨率/品牌别名、CNY/inch/Hz/W/mm、否定和取消表达 | `Monitor Domain Pack/fields + aliases + constraints`；通用 Normalizer 只做 span、类型、单位和 Pack 调度 | 多处词表不一致会让同一句话在 SQL、Checker、报告中含义不同 |
| Agent 二次解析：[agent/react.py](../../agent/react.py) 601–690 | `_infer_task_type` 出现显示器无关词、动态价格词；`_augment_requirements` 再解析尺寸、OLED、分辨率、刷新率、USB-C、预算、宽度 | 删除重复解析前先做调用覆盖；任务分类放通用 Router，字段解析只调用 Pack Normalizer | 直接删除可能改变 V1 16/16 回归；目前与 provenance normalizer 有重叠 |
| SQL 表、列和白名单：[tools/text2sql.py](../../tools/text2sql.py) 18–38、91–116、151–236；[db/schema_v1.sql](../../db/schema_v1.sql) 8–79 | 固定四表、显示器列、操作符、最新价格 JOIN 和结果列；模板直接拼接 `products`/`price_observations` | Domain Pack 声明逻辑字段与 storage binding；Schema Registry 生成只读白名单和参数化查询模板 | 配置生成不能降低 SQLite authorizer、单 SELECT、超时和行数上限 |
| Prompt 中的显示器规则：[agent/react.py](../../agent/react.py) 45–59、443–547 | Prompt 写死“显示器”、四表名、SQL→KB→Evidence 路径、稳定规格字段集合和动态价格条件 | 通用 Runtime Prompt + Pack 注入的能力摘要；依赖守卫仍由代码执行 | 只改 Prompt 不能消除硬编码；LLM 不得控制安全门或白名单 |
| Evidence 字段规则：[tools/evidence_check.py](../../tools/evidence_check.py) 16–26、44–70、155–256 | 三组字段集合、分辨率比较、30 天价格策略、型号/地区对齐和四态规则硬编码 | 通用 Evidence Engine 读取 FieldDefinition、freshness、comparator 和 source policy | Evidence Check 与 Checker 现有比较逻辑重复，迁移时容易产生状态差异 |
| KB 元数据与索引：[retrieval/knowledge_base.py](../../retrieval/knowledge_base.py) 16–39、72–113 | 固定事实卡目录、collection、1024 维、chunk 版本、显示器文档模板及必需元数据 | Data Version 指向 Product Pack、索引 Manifest 与 Pack 版本；通用 chunk 元数据保留 `domain_id/product_id/source_id` | 索引契约变化会要求重建；不得复用 1024 维索引冒充新版本 |
| Constraint Checker：[constraints/verifier.py](../../constraints/verifier.py) 28–45、73–129、133–160、195–402 | 固定显示器字段、价格字段、30 天 TTL、分辨率像素比较、稳定型号正则、四表 SQL、同地区证据和 fail-closed | 通用 verifier 只负责执行和聚合；Pack 提供 comparator/read binding/evidence/freshness 规则 | Checker 是最终安全门；任何动态加载失败必须 fail closed，不能回落到 LLM 判断 |
| Ranking 字段与权重：[agent/ranking.py](../../agent/ranking.py) 35–126 | LLM 只接收合规候选的已核验字段和软偏好；代码阻止增删候选；**V1 没有显式数值权重** | Pack 提供版本化 Ranking Profile、适用场景、可解释维度和默认权重；仍先 Checker 后 Ranker | 不能把拟议权重描述成 V1 已实现；缺证据字段不得获得精确分数 |
| Memory 字段范围：[memory/store.py](../../memory/store.py) 15–26、43–60、94–141；[constraints/normalize.py](../../constraints/normalize.py) 59–67 | 固定 8 个长期偏好键，映射到显示器约束；本地 JSON 路径带阶段名 | 通用偏好 + `domain_id` 命名空间的 Pack 白名单；动态事实继续禁止写入 | 字段改名需迁移/回滚；旧 JSON 必须继续可读且不能误当新 Pack 偏好 |
| 报告字段：[domain/models.py](../../domain/models.py) 58–116、127–251；[agent/reporting.py](../../agent/reporting.py) 19–45、71–300 | Candidate 顶层写死品牌/型号/地区/价格；查询词到字段的映射、显示器标题与字段渲染写死 | 通用报告使用 `attributes`/`field_results`，Pack 提供标签与 formatter；V1 adapter 保留原字段和 Markdown | 报告兼容不能改变推荐集合；unknown/conflict 与证据绑定必须保留 |
| 数据与数据库路径：[data/loader.py](../../data/loader.py) 10–47、[db/build_database.py](../../db/build_database.py) 18–24、[retrieval/knowledge_base.py](../../retrieval/knowledge_base.py) 16–25 | `monitors_v1.json`、`C:/ai/smartbuy-stage3/...`、固定事实卡/processed 路径和 collection 名 | Data Version/Pack Manifest 解析逻辑路径；Runtime Resolver 决定仓库外物理路径 | 不能把运行数据库/索引写进 Git；V1 默认路径必须由兼容层保留 |
| 数据派生中的型号特例：[data/derive.py](../../data/derive.py) 12–29、43–155 | 固定字段、单位和事实卡章节；对 3 个具体型号写死 USB-C 陷阱/冲突说明，数据版本写入模板 | 产品特例变成证据记录或 Product Pack 声明；事实卡模板由 Monitor Pack 负责 | 迁移后若丢失这些陷阱，会破坏冲突和相似型号评测 |
| 数据质量规则：[data/quality.py](../../data/quality.py) 13–31、76–189 | 固定布尔/数值/关键字段、地区后缀正则、USB-C 蕴含关系和数据计数 | 通用完整性/许可/FK 门 + Pack 字段类型和 cross-field invariants | Pack 不能绕过通用安全与许可门；自定义表达式必须是声明式白名单 |
| 评测品类假设：[eval/cases.jsonl](../../eval/cases.jsonl)、[eval/stage4_cases.jsonl](../../eval/stage4_cases.jsonl)、[eval/stage5_natural_cases.jsonl](../../eval/stage5_natural_cases.jsonl)、[eval/stage6_natural_cases.jsonl](../../eval/stage6_natural_cases.jsonl) | 题目、型号、字段、金标和版本均为显示器；Runner 写死 `monitor-cn-2026-08-26-v1`、外部阶段路径及事实查询 | 原文件冻结；新 Pack 的 eval fixtures 通过 adapter 引用 V1 金标，跨品类另建数据集 | 不能移动/重写 V1 金标或用新指标覆盖历史首次结果 |
| 未进入主链/重复实现 | `run_retrieval_eval.py` 的 0.20 阈值仅属阶段 3 评测；`ConstraintSpec` 与 `NormalizedConstraint`、两套 Operator/四态、Evidence `_matches` 与 Verifier `_matches`、`_augment_requirements` 与 Normalizer 重复；Web 工具仅 unavailable | 先用调用图和 characterization tests 确认，再逐项收敛到通用契约；历史 Runner 保留旧 adapter | “看起来重复”不等于可立即删除；历史回放和序列化格式可能依赖旧类型 |

### 2.1 当前 V1 字段的迁移归属

| V1 字段 | V2 所有者 | 说明 |
|---|---|---|
| `model_id/model_name/brand/region` | 通用 Product 身份 + Pack identity policy | V2 通用名建议 `product_id/canonical_name/brand/market`；V1 adapter 保留旧名 |
| `display_size_inch/resolution/refresh_rate_hz/panel_type/is_oled` | Monitor Field Schema | 不进入通用 Product 的固定属性 |
| `has_usb_c/usb_c_video/usb_c_power_delivery_w` | Monitor Field Schema + cross-field invariants | 端口存在、视频与供电是三个独立事实 |
| `stand_adjustment/width_mm/weight_kg/warranty/release_date` | Monitor Field Schema | 动态性和证据要求逐字段声明 |
| `price_cny/stock_status/observed_at` | 通用 Observation + Monitor 可筛选映射 | 追加式、带地区和时间，不进入稳定 Product 真值 |
| `source_id/evidence_id/conflict_group` | 通用 Source/Evidence | 不允许由 LLM 分配或覆盖 |

## 3. 通用契约与数据所有权

### 3.1 共同规则

- 所有可持久化对象均带显式 `contract_version`；Domain Pack、Product Pack、Data Version 另带自己的 SemVer。
- ID、版本、哈希、候选池、工具状态、证据、约束激活、Checker 结果和推荐资格由确定性代码维护。
- LLM 只可生成“提案”：品类/任务候选、带原句 span 的约束提案、工具参数、软排序顺序和自然语言解释；每项必须经过 Schema/Pack/权限门。
- 未知值统一为 `null`/`unknown`，禁止用 `0`、空串或模型猜测替代。
- 所有运行对象必须可安全序列化；Provider client、连接、锁、Key、Authorization、Cookie 和隐藏 Prompt 不进入 AgentState/Checkpoint/账本。
- `product_id + market + variant_key` 唯一标识一个可比较版本；不同地区或硬件版本禁止静默合并。

### 3.2 `Product`

| 字段 | 类型 | 所有者/校验 |
|---|---|---|
| `contract_version` | `str` | 内核固定支持范围 |
| `product_id` | `str` | Product Pack 分配；稳定、唯一、符合 Pack identity pattern |
| `domain_id` | `str` | Domain Registry 校验，必须与加载 Pack 一致 |
| `canonical_name` / `brand` | `str` | Product Pack；非空、规范化 |
| `market` / `variant_key` | `str` | Product Pack；不得由 LLM 改写 |
| `aliases` | `list[str]` | Product Pack；只用于实体解析，不改变身份 |
| `attributes` | `dict[field_id, typed value|null]` | 值必须通过对应 FieldDefinition；不含动态价格/库存 |
| `official_source_ids` | `list[str]` | 必须指向 SourceRecord |
| `data_version` / `product_pack_version` | `str` | 发布器写入，运行时只读 |
| `status` | `active/retired/unknown` | 发布流程维护 |

V1 映射：`model_id→product_id`、`model_name→canonical_name`、`region→market`，其余显示器字段进入 `attributes`。

### 3.3 `FieldDefinition`

字段：`field_id`、`label`、`data_type`（string/decimal/integer/boolean/enum/date/datetime/list/object）、`nullable`、`unit`、`accepted_units`、`aliases`、`enum_values`、`dynamicity`（stable/observed/derived）、`constraint_enabled`、`allowed_operators`、`evidence_required`、`freshness_policy`、`source_policy_ref`、`storage_binding`、`formatter`、`sensitivity`、`definition_version`。

校验：字段 ID 在单个 Pack 内唯一；单位换算必须可逆或明确精度；枚举值封闭；`observed` 字段必须带时间/地区；可硬约束字段必须存在确定性 comparator 和读取绑定。LLM 可以提出别名命中和待规范值，但不能创建 FieldDefinition、修改单位或声明字段已支持。

### 3.4 `Constraint`

字段：`constraint_id`、`domain_id`、`field_id`、`operator`、`normalized_value`、`unit`、`strength`（hard/soft）、`provenance`（current_input/session_confirmed/long_term_preference/system_default）、`source_text`、`source_span`、`source_turn`、`confidence`、`supported`、`ambiguous`、`active`、`cancelled_by`、`domain_pack_version`。

规则：优先级继续为当前输入 > 会话确认 > 长期偏好 > 系统默认；影响资格的歧义必须 interrupt/澄清；LLM 提案只有在 span、Pack 字段、类型、operator 和 provenance gate 全部通过后才能激活。V1 `NormalizedConstraint` 直接映射；旧 `ConstraintSpec` 由兼容 adapter 派生，不再作为真源。

### 3.5 `SourceRecord`

字段：`source_id`、`uri`、`title`、`source_type`、`publisher`、`is_official`、`market`、`language`、`published_at`、`accessed_at`、`content_hash`、`redistribution_status`、`access_policy`、`priority_tier`、`data_version`、`metadata`。

SourceRecord 由 Product Pack/受控 Connector 创建，LLM 只能建议 URI 或来源类型；哈希、访问时间、许可和优先级由确定性采集/治理流程维护。V1 字段可无损映射；`notes` 进入 `metadata.v1_notes`。

### 3.6 `EvidenceRecord`

字段：`evidence_id`、`source_id`、`product_id`、`field_id`、`raw_value`、`normalized_value`、`value_type`、`unit`、`evidence_location`、`market`、`effective_at`、`observed_at`、`confidence`、`conflict_group`、`content_hash`、`trust_state`（governed/temporary/rejected）、`normalizer_version`、`data_version`。

规则：每个关键事实必须能追溯 Source；临时网络证据不能直接进入 Trusted Checker；冲突不覆盖，按组并存；unknown 不生成伪证据。LLM 可从文本提出 `raw_value + location`，但 ID、规范值、单位、冲突组、信任状态和晋升由确定性流水线/人工门维护。

### 3.7 `Candidate`

字段：`product_id`、`identity_status`、`origin_tool_calls`、`attribute_snapshot`、`evidence_by_field`、`requested_field_statuses`、`overall_status`、`eligible`、`violated_fields`、`unknown_fields`、`conflict_fields`、`unsupported_constraints`、`rank_score`、`rank_explanation`、`data_version`、`checker_version`。

生命周期：工具发现 → 合并进完整候选池 → 实体/版本去重 → Evidence Check → Constraint Checker → 仅合规集合进入 Ranker → 报告。LLM 不得直接创建治理候选、删除完整池成员、修改 `eligible` 或把集合外产品加入推荐。

### 3.8 `AgentState`

| 分组 | 字段 |
|---|---|
| 身份 | `run_id/session_id/user_ref/turn/revision`（公开 Demo 的 user_ref 必须脱敏） |
| 请求 | `query_summary/request_ref/task_type/domain_candidates/selected_domain_id/mode` |
| 版本 | `contract_version/domain_pack_version/product_pack_version/data_version/config_hash` |
| 需求 | `constraint_set/soft_preferences/pending_clarifications/memory_refs` |
| 预算 | `max_steps/max_tool_calls/max_latency_ms/max_cost_cny/used_*` |
| 工具 | `tool_results/tool_call_index/retry_state/degraded_states` |
| 决策 | `complete_candidate_pool/evidence_ledger/verification_batch/ranked_eligible_ids` |
| 流程 | `current_node/next_actions/checkpoint_id/stop_reason/finished` |
| 输出 | `report_ref/public_events/usage_summary` |

AgentState 由 Runtime 拥有；Node 只能更新声明的字段。状态不得包含完整 Prompt、隐藏思维链、凭据、连接对象或未经治理的网页全文。V1 `AgentState` 由 adapter 映射：`candidate_pool_rows→complete_candidate_pool`、`kb_hits/assessments→evidence_ledger`、`constraint_verification→verification_batch`。

### 3.9 `ToolResult`

字段：`contract_version`、`tool_call_id`、`tool_name`、`tool_version`、`status`（success/failed/degraded/unavailable）、`summary`、`payload`、`artifacts`、`error_code`、`retryable`、`retry_after_ms`、`attempt`、`continuable`、`degraded`、`parent_call_ids`、`started_at/ended_at/duration_ms`、`usage`、`domain_id/data_version`。

规则：payload 必须由每个工具的输出 Schema 校验；同一 `tool_call_id` 幂等；401/403 不重试，429/超时/5xx 有界重试；公开 summary 不含敏感正文。V1 `ToolResult.data` 映射为 `payload`，其余旧字段保持兼容视图。

### 3.10 Trusted/Open Mode

| 字段/能力 | Trusted Decision | Open Research |
|---|---|---|
| 进入条件 | 已安装 Domain Pack + 可用 Data Version + 治理证据 | 品类/商品不在治理库或需要外部动态研究 |
| 可用证据 | governed；临时证据需先晋升 | governed + temporary，必须显式标注 |
| Checker | 必须执行；异常 fail closed | 可检查已支持字段，但不得把未治理结果标成完全合规 |
| 最终输出 | 可在 Checker 合规集合中推荐 | 研究摘要、候选线索和待核验项；默认不输出“完全满足”购买推荐 |
| 必需字段 | `mode/reason/trust_gaps/promotion_required` | 同左，并记录外部来源、时间和降级 |

模式由确定性 capability gate 最终决定；LLM 只能提出 mode 建议。

### 3.11 `DataVersion`

字段：`data_version`、`domain_id`、`schema_version`、`domain_pack_version`、`product_pack_version`、`source_manifest_hash`、`logical_data_hash`、`sqlite_hash`、`index_manifest_hash`、`embedding_model/dimensions`、`created_at`、`status`（staging/validated/published/rolled_back）、`previous_version`、`compatibility_range`。

版本由 staging→validate→publish 原子切换；失败保持上一 published 指针。输入、切分、Embedding 或维度变化必须产生新索引版本，禁止就地冒充。

### 3.12 `Domain Pack`

Domain Pack 是**品类规则包**，不含具体商品：Manifest、Field Schema、Aliases、Constraint Rules、Source Policy、Checker Rules、Ranking Profiles、Memory Policy、Report Labels 和 Eval Fixtures。Pack 必须签入 Git、SemVer、可离线校验、声明内核兼容范围；Loader 只加载白名单文件，不执行任意 Python/SQL 表达式。

### 3.13 `Product Pack`

Product Pack 是**某品类的一批治理商品数据**：Manifest、products、source records、evidence、observations、fact cards、许可/哈希和构建参数。它引用 Domain Pack 版本，经历 staging→validate→publish，可幂等生成 SQLite/事实卡/索引清单。新增商品不应修改通用业务代码；V1 `monitors_v1.json + demo/fact_cards + manifest` 可由 adapter 视为 `monitor-cn-v1` Product Pack，但原文件不移动。

### 3.14 权限矩阵

| 对象/动作 | LLM | 确定性代码/治理流程 |
|---|---|---|
| 品类、模式、约束 | 可提出候选和原句 span | 校验、激活、覆盖、取消、澄清 |
| 工具 | 可从白名单选择并给出参数提案 | Schema、权限、依赖、预算、重试和实际执行 |
| Product/Source/Evidence ID | 禁止生成可信 ID | 分配、去重、哈希、版本与持久化 |
| 候选池 | 可建议查找方向 | 合并完整池、实体对齐、去重 |
| Evidence 状态 | 可概述 | 四态、冲突、时效和来源归属 |
| Checker/eligible | 无权修改 | 唯一权威；异常 fail closed |
| 排序 | 仅合规集合内提出顺序和解释 | 过滤集合外、补回遗漏、校验 Profile |
| Memory | 可建议待确认偏好 | 仅显式确认后白名单写入，可查删关 |
| 报告 | 可生成受约束文案 | 推荐集合、字段状态、证据引用和降级最终组装 |

## 4. Monitor Domain Pack 设计

### 4.1 计划目录（尚未创建）

```text
smartbuy/domain_packs/monitor/
├─ manifest.yaml
├─ fields.yaml
├─ aliases.yaml
├─ constraints.yaml
├─ source_policy.yaml
├─ checker_rules.yaml
├─ ranking_profiles.yaml
├─ memory_policy.yaml
├─ report_labels.yaml
└─ eval/
   ├─ regression_v1.jsonl
   ├─ boundary.jsonl
   └─ conflicts.jsonl
```

Manifest 计划字段：`domain_id=monitor`、`pack_version`、`contract_version_range`、`default_market=CN`、`schema_version`、`supported_modes`、各配置文件 SHA-256、V1 adapter 名、兼容的数据版本范围、维护者和许可证。Loader 需先校验 Manifest/哈希/Schema，再一次性发布不可变 Pack 快照。

### 4.2 字段、单位、枚举和操作符

| field_id | 类型/规范单位 | 主要别名 | 约束操作符 | 动态性/证据 |
|---|---|---|---|---|
| `display_size_inch` | decimal / inch | 尺寸、英寸、寸 | eq/range | stable，必须有证据 |
| `resolution` | string / `WxH` | 4K/UHD/3840×2160；2K/QHD/WQHD/2560×1440；5K/8K | eq/gte | stable；gte 使用像素比较器 |
| `refresh_rate_hz` | decimal / Hz | 刷新率、Hz、赫兹 | eq/gte/range | stable |
| `panel_type` | enum | 面板、IPS/VA/TN/WOLED | eq/in/not_in | stable |
| `is_oled` | boolean | OLED、非 OLED、不要 OLED | eq | stable；三态 |
| `has_usb_c` | boolean | USB-C/Type-C 接口 | eq | stable；不能由线材推断 |
| `usb_c_video` | boolean | Type-C 视频、一线通视频、DP Alt Mode | eq | stable；需要 `has_usb_c=true` |
| `usb_c_power_delivery_w` | decimal / W | PD、供电、充电功率 | eq/gte/range | stable；上行/下行语义必须核验 |
| `stand_adjustment` | list[enum] | 支架、升降、俯仰、左右/垂直旋转 | contains_all | stable |
| `width_mm` | decimal / mm | 机身宽、桌面空间；cm 可换算 | eq/lte/range | stable |
| `weight_kg` | decimal / kg | 重量、多重 | eq/lte/range | stable |
| `warranty` | string | 保修、质保 | eq/contains | stable but market-specific |
| `release_date` | date | 发布日期、上市时间 | eq/gte/lte | stable but often unknown |
| `price_cny` | decimal / CNY | 价格、预算、元以内 | eq/lte/gte/range | observed；必须有 market/observed_at/TTL |
| `stock_status` | enum | 库存、有货、缺货、停售 | eq/in | observed；不进入长期事实 |

通用身份字段 `product_id/brand/market/canonical_name` 不在 Monitor 专属属性中，但 Pack 声明其别名、可筛选性和地区规则。边界比较包含等号。布尔值只能 true/false/null；null 永不等于 false 或 0。

### 4.3 来源优先级与时效

默认优先级：官方说明书 > 官方支持文档 > 官方规格页 > 官方产品页 > 公开零售页 > 专业测评。优先级用于解释和冲突分类，**不能静默删除低优先级证据**。同优先级/同市场值不一致，或任何记录显式带 `conflict_group`，结果为 conflict。跨地区来源只可作为补充，不得覆盖目标市场字段。

- 稳定规格：没有统一 TTL，但必须保留 effective/accessed 时间；型号修订时新建 variant/data version。
- 价格/库存：追加式观察；V1 adapter 保持 30 天策略。过期、未来时间或地区不符分别为 unknown/conflict。
- 许可：未确认再分发的原文仅本地保存；Pack 只含元数据、哈希、自制摘要和结构化事实。

### 4.4 Evidence 与 Checker 规则

1. Checker 只读取当前 published Data Version 的只读存储和 governed Evidence。
2. 字段为 null、没有正确 `product_id + market + field_id` 证据时为 unknown。
3. 规范化产品字段与任一同地区证据不等价，或存在 conflict group 时为 conflict。
4. 任一硬约束 failed 淘汰；关键硬约束 unknown/conflict 不合规；unsupported/ambiguous 要求澄清。
5. 错误/未知/重复 product_id、Pack 加载失败、数据库不可用或 Checker 异常均 fail closed。
6. `usb_c_video=true` 或正供电值要求 `has_usb_c=true`；但有 USB-C 不反推视频或供电。
7. 分辨率别名先规范化为 `WxH`；gte 采用 Pack 声明的像素比较器，不使用字符串排序。
8. 价格取不晚于 `as_of` 的最新同地区观察，并把 `observed_at` 写入结果。

### 4.5 Ranking Profile（计划值，未实现）

Ranker 只对 Checker 合规集合工作。默认 Profile 仅用于 V2 评审基线，权重可由用户调整且每版总和为 1；字段 unknown 不得被赋予“看似精确”的正分。

| Profile | 维度及计划默认权重 |
|---|---|
| `general_office_v1` | 价格余量 0.20、文本/分辨率 0.25、接口与供电 0.25、支架 0.15、桌面适配 0.15 |
| `gaming_v1` | 刷新率 0.35、分辨率 0.20、面板 0.20、接口 0.10、价格余量 0.15 |
| `color_work_v1` | 可核验色彩证据 0.35、分辨率 0.20、接口 0.15、支架 0.10、价格余量 0.20 |

V1 没有这些数值权重。`color_work_v1` 在 Monitor Pack 没有新增色彩字段/证据前必须标记 unsupported，不得使用面板类型替代色准事实。

### 4.6 Memory 白名单

- 通用：预算区间、排除品牌、主要用途、默认市场（用户显式确认）。
- Monitor：尺寸、分辨率、最低刷新率、是否排除 OLED、接口/供电偏好、支架偏好。
- 禁止：商品事实、型号推测、价格、库存、Evidence、排名、未确认条件。
- 存储键必须包含 `user_id + domain_id + policy_version`；旧 V1 键通过只读 adapter 映射，写入新格式前需显式迁移。

### 4.7 Eval Fixtures 与 V1 映射

- `regression_v1` 只引用并适配现有 16 条 Agent 回归和 40 条冻结任务，不修改原 JSONL/哈希。
- `boundary` 覆盖单位、等号边界、别名、取消、unsupported、null、错误/重复 ID。
- `conflicts` 覆盖 60W/65W、跨地区、官方/零售、价格过期和诱导文本。
- Characterization gate：V1 API/报告兼容、完整候选池、Checker 合规集合和四个 Demo 必须无非预期变化。

### 4.8 完整示例

用户输入：

> 中国大陆市场，预算不超过 4000 元；要 27 英寸、至少 4K、至少 60Hz、非 OLED、USB-C 视频且供电不少于 65W，机身宽度最多 615mm，支架必须能升降。

规范约束（节选）：

```json
{
  "domain_id": "monitor",
  "mode": "trusted_decision",
  "constraints": [
    {"field_id":"market","operator":"eq","normalized_value":"CN","strength":"hard","provenance":"current_input"},
    {"field_id":"price_cny","operator":"lte","normalized_value":4000,"unit":"CNY","strength":"hard","provenance":"current_input"},
    {"field_id":"display_size_inch","operator":"eq","normalized_value":27,"unit":"inch","strength":"hard","provenance":"current_input"},
    {"field_id":"resolution","operator":"gte","normalized_value":"3840x2160","strength":"hard","provenance":"current_input"},
    {"field_id":"refresh_rate_hz","operator":"gte","normalized_value":60,"unit":"Hz","strength":"hard","provenance":"current_input"},
    {"field_id":"is_oled","operator":"eq","normalized_value":false,"strength":"hard","provenance":"current_input"},
    {"field_id":"usb_c_video","operator":"eq","normalized_value":true,"strength":"hard","provenance":"current_input"},
    {"field_id":"usb_c_power_delivery_w","operator":"gte","normalized_value":65,"unit":"W","strength":"hard","provenance":"current_input"},
    {"field_id":"width_mm","operator":"lte","normalized_value":615,"unit":"mm","strength":"hard","provenance":"current_input"},
    {"field_id":"stand_adjustment","operator":"contains_all","normalized_value":["height"],"strength":"hard","provenance":"current_input"}
  ]
}
```

预期完整池审计（使用 V1 数据说明规则，不是新实验）：

| 候选 | 关键结果 | 资格 |
|---|---|---|
| `dell-u2723qe-cn` | 27/4K/60Hz/非 OLED/USB-C 视频/90W/611.4mm/升降均有同地区证据；价格 3608.99 且带观察时间 | 约束均 passed 时 eligible |
| `asus-pa279crv-cn` | 稳定规格满足，但没有价格观察 | `price_cny=unknown`，不可标记完全满足 |
| `lg-27up850k-w-cn` | 稳定规格满足，但价格未知 | `price_cny=unknown` |
| `benq-pd2705u-us` | 市场为 US；USB-C PD 同地区官方来源出现 60W/65W conflict | region failed、PD conflict；淘汰并保留双方来源 |
| `dell-u2724d-cn` | 分辨率仅 QHD、USB-C 无视频、15W；width 为 null | 多字段 failed + `width_mm=unknown`，淘汰；null 不转 0 |

这一个例子同时验证预算时效、尺寸、分辨率别名与最低值、刷新率、接口三分法、供电边界、来源冲突和缺失字段。报告必须展示 `observed_at`、冲突双方、unknown 和实际淘汰字段；LLM 只能解释，不能改变资格。

### 4.9 V1 数据映射与版本回滚

- Adapter 名：计划 `monitor_v1_adapter`，输入仍为原 `monitors_v1.json`、四类 processed JSONL、事实卡和 SQLite v1。
- 逻辑 Data Version 继续是 `monitor-cn-2026-08-26-v1`；不得重写原 Manifest/hash。
- V2 构建先产出 staging 版本，比较 12/4/16/180、SQLite 逻辑哈希、60 chunks、V1 Checker 合规集合和四个 Demo。
- 仅全部门禁通过后切换 V2 published 指针；回滚只切回 V1 adapter/旧 Data Version，不删除失败 staging。

## 5. V1 兼容与回滚方案

### 5.1 API、WebUI 与 Demo

- 保持 `POST /api/smartbuy/chat`、`GET /api/smartbuy/monitor`、`/api/smartbuy/memory/{user_id}` 的路径和 V1 请求字段。
- V2 可新增可选 `domain_id/mode`；缺省时 adapter 固定 `monitor/trusted_decision`，不得改变旧调用。
- V1 响应继续保留 `report`、`markdown`、现有 `DecisionReport v3` 字段和 SSE 事件名。V2 新字段只能追加到版本化扩展区，旧前端忽略后仍可渲染。
- 四个固定 Demo 继续使用 V1 数据和旧端点；V2 功能未通过前 README 不改“已实现能力”。

### 5.2 冻结资产

以下历史事实禁止修改、重排、重生成或覆盖：

- Tag/Release `v1.0.0-portfolio` 与 `main` 的 V1 Commit。
- `smartbuy/data/catalog/monitors_v1.json`、`smartbuy/data/demo/`、`smartbuy/data/processed/stage3_*` 至 `stage7_*`。
- `smartbuy/eval/cases.jsonl`、`stage4_cases.jsonl`、`stage5_*.jsonl`、`stage6_*.jsonl`、`stage6_config.json`。
- 阶段 3～7 报告、`portfolio_metrics.md`、`release_report.md` 与 V1 Release Notes。
- V1 SQLite Schema、事实卡、索引 Manifest 和历史结果哈希。新版本必须新路径/新版本号。
- 原始 FINAL 交接文档与百炼接入说明的历史内容。

### 5.3 Pack/Data 回退

Loader 采用两阶段加载：校验候选 Pack/Data → 原子发布不可变快照。Manifest/Schema/哈希/内核兼容/构建/回归任何一项失败时：记录脱敏错误、保持上一 published 指针、启动 V1 adapter，报告 `degraded=true`；不得让 LLM 绕过缺失 Pack。旧版迁移只新增映射，不就地改数据。

### 5.4 编排回退

LangGraph PoC 不接入 V1 主链。若 PoC 未达决策门，删除隔离实验代码，保留 [PoC 计划](v2_1_langgraph_poc_plan.md)和后续 ADR，继续使用自研 ReAct；只把通用 AgentState、ToolResult、节点边界和测试思想应用到后续重构。即使采用 LangGraph，也必须保留运行时开关和 V1 ReAct adapter，直到 V1 全量回归、四 Demo 和 Checker 等价门通过。

## 6. 迁移顺序、风险与 V2-1B 前置条件

建议顺序：冻结 characterization tests → 定义纯数据 Schema/Loader → Monitor Pack 离线校验 → V1 adapter 双读比较 → 生成 SQL/Evidence/Checker 配置 → 完整候选池等价 → 报告/API 兼容 → 最后移除确认无调用的重复逻辑。

主要风险：配置变成可执行代码、Pack 版本漂移、两套状态长期并存、字段比较器行为变化、索引误复用、Memory 字段迁移污染、旧响应断裂，以及将 Open Mode 临时证据误晋升为可信事实。缓解方式分别是声明式白名单、哈希/兼容范围、单一真源+adapter、golden comparator、Data Version 门、显式用户迁移、contract tests 和 fail closed。

V2-1B 前置条件：

1. 用户评审并确认本文与 [LangGraph PoC 计划](v2_1_langgraph_poc_plan.md)。
2. 确认通用契约中没有显示器专属固定字段。
3. 选定 PoC 隔离目录与依赖固定方式；届时再核对 LangGraph 官方 API，不在本轮安装依赖。
4. Fake Provider、只读 SQLite/KB fixtures、V1 代表用例和 Checker golden 输出可离线使用。
5. V1 测试、冻结哈希、四 Demo 与业务文件基线保持不变。
6. 获得用户明确授权后才能开始 PoC；PoC 通过仍不等于批准 V2-1C 生产迁移。
