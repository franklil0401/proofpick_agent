# ADR-0009：通用契约与 Monitor Domain Pack 采用适配优先

- 状态：Accepted for opt-in compatibility validation
- 日期：2026-08-31
- 阶段：V2-1D
- 关联：[V2-1D 报告](../v2/v2_1d_domain_pack_report.md)、[运行说明](../v2/v2_1d_runtime.md)

## 背景

V1 将显示器字段、单位、约束、来源、Memory 和报告规则分散在数据、工具、Checker 与 Agent 中。直接把这些旧模型替换为“通用模型”会同时改变已冻结的比较器、Evidence 四态、SQLite、Chroma 和评测语义，无法证明 V1 行为不变。V2-1D 的目标只是建立可校验的领域边界，不开发第二品类或 Product Pack 导入流程。

## 决策

1. 新增不可变、`extra=forbid` 的 `proofpick-domain-contract-v1`，定义 Product、FieldDefinition、Constraint、EvidenceRecord、SourceRecord、Candidate、ToolResult、DataVersion、DomainPack 和 ProductPack 元数据边界。
2. 保留 V1 `ConstraintSpec`、`NormalizedConstraint`、Operator、Evidence 四态、比较器与报告 Schema；V2 只通过 `V1CompatibilityAdapter` 映射，不复制或替换业务判断。
3. Domain Pack 是仅含 JSON 的数据包。Loader 只接受固定三文件，拒绝重复键、额外文件、路径逃逸、超限内容、Schema/契约/Loader 版本不兼容、别名冲突和策略引用不一致；Pack 不能指定或加载任意 Python。
4. Monitor Pack `1.0.0` 映射 V1 的 23 个数据/偏好字段、12 个 Checker 字段、单位/别名、来源优先级、Memory 白名单、Ranking/Reporting 实现引用和冻结数据/评测哈希。它不携带新商品，也不修改 V1 数据。
5. `PROOFPICK_DOMAIN_PACK_ENABLED` 默认 `false`。关闭时不加载 Pack、不包装 Orchestrator、不迁移数据；显式开启后缺失、损坏、版本不兼容或哈希不一致均 fail closed，不允许静默回退。
6. LLM 只能提出约束、工具参数和解释。字段合法性、约束激活、Evidence 四态、候选资格、Checker 与 Data Version 由确定性代码拥有。Candidate 不可变，且 adapter 会拒绝任何与 V1 Checker 不一致的资格或推荐集合。
7. ProductPack 当前只有只读描述符与 Reader Protocol。导入、staging、发布、Evidence Ledger 和多品类数据均留到后续独立阶段。

## 后果

收益：V1 对外响应可逐字段往返验证；领域配置有明确版本与关闭失败边界；关闭开关即可无迁移回滚。代价：V1 与 V2 模型暂时并存，存在有意保留的重复；Monitor Pack 仍引用 V1 Checker/Ranking/Memory/Reporting 实现，不能据此宣称业务逻辑已完全通用化。

## 否决方案

- 直接删除旧模型并改写 Checker：无法隔离 V1 行为变化。
- 允许 Pack 引用动态 Python 插件：扩大供应链与反序列化攻击面。
- Pack 失败时自动走 V1：会把配置错误伪装成正常结果，违反审计与 fail-closed 原则。

## 回滚

将 `PROOFPICK_DOMAIN_PACK_ENABLED=false` 或移除该进程变量并重启。V1 数据、SQLite、Chroma、Memory 和请求/响应均无需迁移。不要删除旧模型或修改冻结文件来完成回滚。
