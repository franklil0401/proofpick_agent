# V2-6A Laptop Domain Pack 与治理数据报告

最后更新：2026-09-02

分支：`feature/proofpick-v2`

范围：第二品类的数据契约、治理数据、离线派生产物与冻结评测；未进入 V2-6B/6C。

## 1. 前置通用化审计

审计覆盖 Domain/Product Pack、Constraint Proposal、Text2SQL、Evidence、Checker、Memory、KB、编排器、报告、数据版本和回滚。

| 位置 | 审计结论 | V2-6A 处理 |
|---|---|---|
| `domain_packs/loader.py` | 原有策略完整性检查依赖 Monitor 实现名，缺少多 Pack Registry 和通用值域校验 | 改为配置驱动策略校验，新增 fail-closed Registry 和通用确定性 evaluator |
| `product_packs/models.py`、`loader.py`、JSON Schema | 原模型只允许 monitor 与 CN/US/CA/GLOBAL，并默认读取 V1 Catalog | 扩展为任意合法 domain/两字母地区，增加 standalone base、配置驱动字段及来源权限；Monitor 默认保持原样 |
| `product_packs/builder.py` | V1 表结构与字段面向显示器 | 保留不改；新增通用 EAV 派生器，避免在旧 Builder 中加入 CPU/GPU 常量 |
| `agent/react.py`、`agent/reporting.py`、`constraints/verifier.py` | 生产主链仍含显示器字段、SQL 表和报告结构 | 本轮不接 Laptop；通用工具适配与完整闭环留到 V2-6B |
| `tools/evidence_check.py`、`retrieval/knowledge_base.py` | 仍依赖 Monitor 表、字段和索引语义 | 本轮只生成待索引文档；真实 KB/Evidence 闭环留到 V2-6B |
| `memory/store.py` | 持久层行为可复用，但公开字段键仍由现有主链约束 | Laptop Memory 白名单仅写入 Pack；主链接线留到 V2-6B |
| ReAct/LangGraph | 编排兼容层可复用，但正式工具仍是 V1 Monitor 工具 | 不复制 Laptop Agent；V2-6A 不改变默认编排器 |

结论：接入治理数据不需要在通用内核加入笔记本业务字段。新增通用模块 `DomainPackRegistry`、`DomainConstraintEvaluator` 和 `DomainProductPackManager` 均不包含 CPU、GPU、内存等字段常量；所有 Laptop 字段与规则位于 Pack JSON。生产工具闭环尚未通用化，不能把本阶段描述为已完成笔记本购买推荐。

## 2. Laptop Domain Pack

`smartbuy/domain_packs/laptop/` 包含 Manifest、49 个字段定义和策略。字段覆盖身份、CPU、GPU、内存/存储、便携/电池、屏幕、接口/扩展、系统/服务以及受限实测字段。

- Checker 支持字段：42；其中明确允许作为硬约束的字段 33 个，软偏好专属字段 3 个。其余字段按各自 `constraint_enabled`、操作符和证据规则处理。
- 单位和别名由 Pack 定义，例如 TB→GB、g→kg、2.5K→2560x1600；数值超出 Pack 值域时拒绝。
- `unknown` 是字段值缺失或缺少对应证据；`unsupported` 是字段/操作符不在 Pack；二者均不能获得 eligible。
- `price_cny` 已定义但本数据版本没有价格观察，因此预算条件确定性返回 unknown，不能声称预算内。
- Memory 仅允许预算、CPU 系列、GPU 类别、内存、存储、重量、充电/雷电、品牌排除和主要用途等明确偏好。
- 报告白名单与 Monitor 分离；Monitor 的 USB-C PD 字段不会进入 Laptop 报告，Laptop 内存字段不会进入 Monitor Memory/报告。

来源权限由 Pack 强制：官方产品/支持/手册可证明稳定硬件规格；专业评测只能证明续航实测、性能分数、表面温度和噪声；零售来源本阶段不能写稳定规格；搜索摘要不能进入 Product Pack Evidence。

## 3. 治理数据

数据版本为 `laptop-governed-2026-09-02-v1`，包含 12 个精确配置、4 个品牌、7 种地区标识和 12 条官方来源：

| 品牌 | 精确配置 | 地区 |
|---|---|---|
| Dell | XPS 13 9350：`usexchcto9350lnl06`、`caexchcto9350lnl02`、`usexcpcto9350lnl04` | US、CA |
| ASUS | ProArt P16：`H7606WX`、`H7606WW`、`H7606WI` | CN |
| HP | EliteBook 840 G11 `9G0C0ET`、ZBook Firefly 14 G11 `98N14ET`、ZBook Power G9 `6B8C1EA` | IL、GLOBAL |
| Lenovo | ThinkPad T14 G5 `21ML000FGR`、X1 Carbon G13 `21NX00K4PH`、T14s G7 `21YW0042US` | DE、PH、US |

同系列不同配置组有 2 组（Dell XPS 13、ASUS ProArt P16），相似型号专项至少有 2 组（HP ZBook、Lenovo T14/T14s），同系列跨地区组有 1 组（Dell XPS 13 US/CA）。每个配置使用不同 `product_id`/`configuration_id`，没有按系列合并。

治理统计：

- 45 个可派生属性 × 12 个配置 = 540 个字段位；已知 358，明确 null/unknown 182，字段缺失率 `182/540 = 33.70%`。
- Source Record 12 条，均指向品牌官方页面、官方配置页或官方产品规格 PDF；不提交原网页/PDF 全文，只提交 URL、访问时间、自制摘要和结构化事实。
- Evidence Record 406 条；所有非空 Checker 字段均有字段级证据。
- 关键事实口径为商品、品牌、型号、地区、配置、料号、CPU 型号、GPU 类型/型号、内存和存储，共 `132/132 = 100%` 有对应 Evidence ID，高于 95% 门槛。
- 无动态价格；续航、性能、温度、噪声等实测字段当前均为 null，没有伪装为官方规格。

## 4. Product Pack 与离线派生产物

`build_laptop_product_pack.py` 从紧凑治理源生成 Product Pack；`DomainProductPackManager` 在仓库外完成 staging、validate、publish、versions、current 和 rollback。派生产物包括 EAV SQLite、Source/Evidence JSONL、Evidence Ledger、自制事实卡、12 份待索引文档和 Manifest。

两次独立构建结果：

| 项目 | Build A | Build B |
|---|---|---|
| Manifest SHA-256 | `d44373c8214cb996776445e5a5c1da60c233ce5d4b770c261399d913211ac1ad` | 相同 |
| Logical Data SHA-256 | `34f584a65947f89163ae7953d3b40f841dee9443a4180872bef1d686511a13d0` | 相同 |
| SQLite integrity / FK | `ok` / 0 | `ok` / 0 |

Manifest 记录 12 products、540 attributes、12 sources、406 evidence、0 prices。向量阶段固定 `text-embedding-v4`/1024 维，但状态仅为 `documents_ready`、12 documents、`paid_index_build_performed=false`。本轮没有构建 Chroma；`require_completed_index` 对误启用未完成索引 fail closed。

重复 Pack、错误地区后缀、字段缺证据、越权零售规格和损坏 Pack 均被拒绝；失败 staging 不改变已发布 current 指针。rollback 只切换完整版本快照，不产生混合数据版本。

## 5. 自然约束与冻结评测

10 条指定 Laptop 表达通过现有 `ConstraintProposalValidator` 与服务端精确 Quote/Span 合同进行离线验证；明确约束激活，模糊“不要游戏本那么重”保持 `needs_confirmation` 且 inactive。没有重新引入 LLM 字符下标，也没有真实 qwen-plus 调用。

冻结评测为 `smartbuy/eval/v2_6a_laptop_cases.jsonl`，共 30 条：结构化筛选 10、相似配置 5、地区/配置 5、unknown/unsupported 5、自然约束 5；split 明确区分 regression、holdout、hard_negative、clarification。冻结 SHA-256：`3dfcc0f442bda2b6b4d2e96814a8973b415b3d8c8b9b33235924982fa1758d34`。本轮只校验设计和金标结构，不运行收费 E2E。

## 6. 回归与质量门

- Laptop V2-6A 定向：16/16。
- Monitor Domain/Product Pack 兼容：55/55。
- V2-5/5C QuoteSpan、Proposal 与澄清：48/48。
- V1 Tag 中 18 个原始测试文件：94/94。
- `smartbuy/tests`：292/292；加入上游配置脱敏安全 node 的 CI 等价范围：293/293。
- Ruff、Compileall、JavaScript 12/12、PowerShell AST 5/5、Markdown 相对链接与 `git diff --check` 通过。
- 当前变更敏感凭据形状命中 0、禁止运行产物 0、冻结/保护业务路径变化 0；既有依赖告警 3 条，没有新增依赖或锁文件改动。
- 收费 API 调用 0，估算成本 ¥0；没有启动 FastAPI、MinIO 或外部服务。

V1 Tag、`main` 和 `origin/main` 仍共同指向 `d51b6668a6a45c1b01ef4e64da3c4b9ac84ed10c`。V1 Catalog、阶段 4/6 冻结任务、V2-5B/5C 数据与历史结果均未修改。

## 7. 结论与边界

V2-6A 证明第二品类的数据描述、验证、Evidence 权限、派生构建和确定性字段比较可以由 Pack 驱动，且不污染 Monitor 配置。本阶段没有真实 Embedding/Chroma、Reranker、Laptop Text2SQL/KB/Evidence/Checker 工具闭环、Agent E2E、Open Research、UI 或购买推荐。

V2-6B 的前置条件是用户单独授权，并接受以下任务：让现有查询、Evidence 和 Checker 主链按 Domain Pack 生成白名单/映射；建立独立 Laptop SQLite 与 Chroma 版本；用冻结 30 条中的代表任务验证工具闭环。不得直接在现有显示器模块中添加 Laptop 字段分支。
