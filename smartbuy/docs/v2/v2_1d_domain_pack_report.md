# ProofPick V2-1D 通用契约与 Monitor Domain Pack 报告

最后更新：2026-08-31

状态：**兼容落地与离线验收完成；Domain Pack 路径仍默认关闭**

基线：V1 `d51b6668a6a45c1b01ef4e64da3c4b9ac84ed10c`；V2-1C `59e506640abeff4e11c8dc4264e930a0c63cfdae`

## 1. 结论与范围

V2-1D 以 Adapter 为边界落地通用契约和第一套 Monitor Domain Pack。V1 ReAct、LangGraph 兼容封装、工具、Checker、Memory、数据、索引和冻结评测均未重写；关闭开关时请求仍走原 V1 对外路径。Pack 显式开启后只对 V1 输入/输出做确定性校验，不能改变 Checker 资格或报告推荐集合。

本阶段没有第二品类、Product Pack 导入、Evidence Ledger、Web Search、图原生节点、在线模型调用或历史评测重跑。

## 2. 通用契约与所有权

`smartbuy/contracts/` 新增不可变、拒绝额外字段的版本化对象：

| 契约 | 边界与所有者 |
|---|---|
| Product / FieldDefinition | 确定性数据层维护稳定 ID、属性、类型、单位、别名、枚举与存储绑定 |
| Constraint | LLM/用户可提出候选约束；supported、active、字段与 Operator 由确定性校验器决定 |
| SourceRecord / EvidenceRecord | 治理数据层拥有 source/evidence ID、来源时间、值和 matched/not_matched/unknown/conflict |
| Candidate | Checker 拥有资格、四态、违规/未知/冲突字段与证据；unknown/conflict 不能 eligible |
| ToolResult | 工具状态、候选/证据 ID、降级和错误类别的跨工具边界 |
| DataVersion / DomainPack | 确定性版本、计数、哈希、字段和策略配置 |
| ProductPack | 本轮仅元数据和只读 Reader Protocol；没有导入或发布实现 |

LLM 只能提出约束、工具参数和解释；不能写 Product/Evidence/DataVersion，不能把 unknown/conflict 变成 matched，也不能修改 Checker。Pydantic frozen contract 阻止常规赋值，V1 adapter 在返回前还会将候选集合、状态、eligible 和推荐集合与原 Checker 逐项对照。

## 3. Monitor Domain Pack

`smartbuy/domain_packs/monitor/` 由 `manifest.json`、`fields.json` 和 `policies.json` 构成：

- 版本：Manifest Schema `1.0.0`、Pack `1.0.0`、契约 `proofpick-domain-contract-v1`。
- 23 个字段：覆盖 V1 商品、价格观察和 `primary_use` 偏好；12 个字段保持现有 Checker 支持范围。
- 单位：inch、Hz、W、mm、kg、CNY；仅声明式换算，未知单位拒绝。
- 别名：显示器字段、分辨率（4K/UHD、2K/QHD/WQHD）、品牌与地区映射保持 V1 语义。
- 来源优先级：official_manual 100、official_support 95、official_product 90、public_retail 50、professional_review 40。
- 策略边界：Checker/Ranking/Memory/Reporting 只引用现有实现；Memory 精确保留 8 个 V1 key；报告仍为 `smartbuy-decision-v3`。
- Product Pack 参考：只引用原 `monitors_v1.json`、数据版本、SHA-256 和 12/4/16/180 计数，不携带或修改商品数据。
- Eval Fixtures：记录 16 条阶段 4 与 40 条阶段 6 冻结文件的路径、数量和 SHA-256。

Loader 只接受固定三文件，并验证重复键、额外文件、路径逃逸、大小、UTF-8/JSON、Manifest/契约/Loader 版本、字段/别名唯一性、Operator、策略章节、Checker 字段、Memory 白名单、报告版本和数据兼容性。Pack 不能动态导入 Python。缺失、损坏、不兼容或 Catalog 哈希变化均在 Agent 执行前 fail closed。

## 4. V1 兼容和回滚

- `V1CompatibilityAdapter` 把旧请求映射为带 domain/data version 的快照，把 12 个 V1 商品映射为通用 Product，并把 `NormalizedConstraint`、`VerificationBatch` 映射为通用 Constraint/Candidate。
- 通用结果返回旧响应前，必须与 V1 Checker 的完整候选池、字段总状态、eligible 和推荐集合一致；不一致会清空推荐并记录 `domain_pack_failed`。
- `PROOFPICK_DOMAIN_PACK_ENABLED` 默认 `false`。关闭时 Router 不实例化 Loader/Adapter，既不迁移数据，也不改变 Orchestrator。
- 显式开启时产生 `domain_pack_selected/completed/failed` 脱敏 SSE/Monitor 事件；不会静默回退。
- LangGraph 默认值仍是 `react`，V2-1D 没有拆分或迁移生产节点。

## 5. 测试与冻结证据

所有新增用例只使用本地 JSON、临时 SQLite、Fake/Stub Agent；在线 API 调用、Token 与成本均为 **0**。

| 验证项 | 结果 |
|---|---:|
| V2-1D 新增测试 | 35/35 |
| 当前 `smartbuy/tests` 全集 | 154/154，3 条上游弃用警告 |
| CI 等价套件（含上游配置安全测试） | 155/155，3 条上游弃用警告 |
| V2-1D 前既有当前分支测试 | 119/119 |
| V2-1C 定向套件 | 25/25 |
| V1 Tag 所含 `smartbuy/tests` 文件当前复跑 | 94/94 |
| Monitor Pack 字段/策略加载 | 23/23 字段、12/12 Checker 字段 |
| 12 个现有型号通用映射 | 12/12 |
| 真实完整目录 V1 Checker 新旧映射 | 12/12 候选状态与资格一致 |
| 阶段 4 冻结回归响应往返 | 16/16 |
| Pack 缺失/损坏/额外代码/不兼容 | 4/4 关闭失败 |
| 默认关闭与无迁移回滚 | 1/1 |
| 冻结 Catalog/评测哈希 | 5/5 与基线一致 |

历史 V1 文档写有“95 passed”，V2-1C 报告写有“120/120”；当前同一环境实际收集分别为 94 和 119。测试文件和既有断言本阶段没有修改，94/94 与 119/119 全部通过，因此这是历史计数口径/记录与当前收集数的 1 条差异，不是测试失败。本报告不改写历史文档数字，也不伪造为 95/120。

Ruff 与 Compileall 通过，JavaScript 语法检查 12/12、PowerShell AST 5/5、Markdown 相对链接 244/244；敏感信息扫描不安全命中 0（另识别 4 处显式离线假凭据夹具），`git diff --check` 通过。本轮新增禁止产物为 0；全仓库规则命中的 2 个 `.env.example` 和 1 个上游测试 `.db` 均已存在于 V1 冻结提交且本轮未修改。冻结文件哈希为：Catalog `b50fd4…210a`、stage4 `a25c88…77a0`、stage5 natural `27f647…7400`、stage6 natural `6082ac…e0ef`。

## 6. 行为差异、风险与限制

默认开关关闭时，对外业务行为差异为 **0**。显式开启的新增行为只有 Pack/版本/冻结哈希校验和审计事件；成功响应保持 V1 Schema 与值一致。失败会明确关闭推荐，这属于安全边界，不是静默兼容。

限制与风险：

1. V1/V2 模型暂时并存，重复是“适配优先”的有意代价；本轮没有统一两套 Operator 或比较器。
2. Monitor Pack 仍引用显示器 V1 实现，尚未证明第二品类可仅靠配置接入。
3. ProductPack 只有接口边界，没有 staging/import/publish、许可门或 Evidence Ledger。
4. 23 个 FieldDefinition 只覆盖现有数据与 Memory；不是任意消费品通用字段全集。
5. Pack JSON 的真实性依赖 Git 审阅和已记录哈希；未来外部 Pack 需要签名/信任策略，不能直接当作可信输入。

## 7. V2-2 前置条件

当前**有条件具备**进入 V2-2 Product Pack 与 Evidence Ledger 设计/隔离实现的基础：通用对象、严格 Loader、Monitor 映射、V1 adapter、默认关闭和冻结回滚证据已存在。开始前仍需用户单独授权，并冻结 Product Pack staging→validate→publish 生命周期、来源许可状态、Ledger 追加/冲突语义、Pack 信任/签名方案和失败回滚矩阵。不得用 V2-2 删除旧模型、修改 V1 数据或把新路径直接设为默认。

## 8. 可复现命令

```powershell
uv run --project vendor/youtu-rag --group dev python -m pytest `
  smartbuy/tests/unit/test_v2_domain_pack.py `
  smartbuy/tests/integration/test_v2_domain_pack_compat.py -q
uv run --project vendor/youtu-rag --group dev python -m pytest smartbuy/tests -q
```

运行开关见 [V2-1D 运行说明](v2_1d_runtime.md)，决策见 [ADR-0009](../adr/0009-domain-contracts-and-monitor-pack.md)。
