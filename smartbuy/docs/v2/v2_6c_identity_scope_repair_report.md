# V2-6C-R1 通用商品身份与 Candidate Scope 修复报告

## 1. 结论

本轮建立了领域无关、由确定性代码拥有的 `ResolvedProductScope`，并将它贯穿 Product Query、KB Search、Evidence Check、Constraint Checker、报告、LangGraph Checkpoint 和脱敏事件。只重放已经暴露的 20 条任务：Regression `10/10`，`exposed_holdout_regression_v1` `10/10`，合计 `20/20`。这不是新 Holdout 结果，也不代表 V2-6C 已完成。

原始失败永久保留：Regression `4/10 → 5/10 → 10/10`、原 Holdout 首次 `3/10`、原推荐证据覆盖 `3/9`。修复结果写入新的 [机器可读结果](../../eval/results/v2_6c_r1_exposed_regression.json)，没有覆盖任何历史文件。

## 2. 新契约

实现位于 `smartbuy/identity/`：

- `ProductScopeType`：`exact_configuration`、`product_family`、`explicit_comparison`、`catalog_filter`、`open_unknown_product`、`ambiguous_product_scope`。
- `ProductMention`：保留用户原文 quote、服务端字符 span、身份类型、注册值和命中的 product IDs。
- `ResolvedProductScope`：包含 domain、family/product/configuration/region、比较/澄清状态、Data/Index Version、解析原因和稳定指纹。
- `ProductIdentityResolver`：按配置号、Part Number、product ID、唯一型号/别名、family 的顺序，只做注册表精确匹配和完整 token 边界判断。
- `ProductIdentityMismatch` 与证据闭包检查：任何工具企图扩大 Scope、混用版本、地区、配置或字段时 fail closed。

别名、family、配置和字段值都来自 Product Pack/Registry。通用实现没有 H7606、XPS、品牌或测试 case ID 分支；这些字面量只存在于治理数据、测试和审计文档。

## 3. 任务语义

| 输入语义 | 确定性行为 |
|---|---|
| 精确 configuration / SKU / product ID / 唯一别名 | Scope 只含唯一配置 |
| family 且有多配置/地区 | 默认暂停澄清 |
| 明确比较多个配置 | Scope 只含用户点名的配置；不得补入同 family 兄弟配置 |
| 没有型号的结构化筛选 | 才允许 Catalog Scope；Checker 检查这个完整范围 |
| 本地不存在的显式型号 | `open_unknown_product`；Trusted Mode 停止，不用相似本地商品替代 |
| 多义 identity | `ambiguous_product_scope`；暂停并澄清 |

精确注册身份优先于 LLM/规则产生的 identity 约束。冲突的 identity Proposal 和约束保留审计记录，但会失活，不能改变 Scope。

## 4. 工具链不变量

- Product Query 只读取 Scope 内产品，并返回完整身份 envelope。
- KB Search 把 Scope 写入过滤条件，再对每个 hit 的 domain/product/configuration/region/data/index 做后验验证。
- Evidence Check 拒绝 Scope 外 product ID；报告前再次检查 product、field、region、variant、Evidence ID 和 source ID。
- Checker 输入必须与 `scope.product_ids` 完全相等；子集、超集、未知配置和未解析 Scope 都 fail closed。
- Report 候选和证据只能来自 Scope；每项带 `domain_id`、`family_id`、`product_id`、`configuration_id`、`region`、`data_version`、`index_version`。
- LangGraph State 保存序列化 Scope；恢复后 Scope 指纹不变。事件只输出类型、数量、状态和指纹，不输出 Prompt 或隐藏推理。

## 5. 证据闭包

每条已知事实必须满足候选与 Evidence 的 product、configuration、region、field 和数据版本闭包，且 source ID 可追溯。字段/配置错绑转为 `unknown/identity_mismatch`；只有错误地区证据转为 `unknown/region_mismatch_only`；无证据不写成 matched；同一可比配置的异值仍由既有冲突规则保留双方。LLM 不能生成 Evidence ID，也不能覆盖 Checker。

## 6. 离线回归结果

运行命令：

```powershell
uv run --project vendor/youtu-rag python -m smartbuy.eval.v2_6c_r1_identity_scope_replay `
  --output <新的结果文件.json>
```

该 Runner 只复用已保存、已暴露的 Constraint Resolution 和治理 SQLite；KB 适配器只生成离线工具轨迹，事实证据仍来自治理账本。它不会读取模型密钥或调用 LLM、Embedding、Reranker、Web Search。

| 指标 | 修复后结果 |
|---|---:|
| 原 Regression | 10/10 |
| 已暴露 Holdout 回归 | 10/10 |
| 合计任务 | 20/20 |
| 清晰硬约束字段 Precision / Recall / F1 | 45/45 / 45/45 / 100% |
| 推荐事实证据覆盖 | 75/75（100%） |
| 充分证据筛选任务错误空推荐 | 0/10 |
| 错误配置进入报告 | 0 |
| 错误地区进入报告 | 0 |
| Scope 外候选进入报告 / Checker | 0 / 0 |
| Evidence 身份 envelope 不完整 | 0/20 |
| unknown 误写为满足 | 0 |
| API 调用 / 费用 | 0 / ¥0 |

以上是暴露回归，不是泛化指标。离线 Fake KB 的耗时也不是在线检索性能。

## 7. 专项与兼容验证

- 新增身份/Scope 测试：40 条，覆盖精确 configuration、Part Number、唯一别名、共享前缀、family 多配置、多地区、显式比较、Catalog、未知/拼写错误、地区过滤、数据/索引版本、工具越界、证据错绑、Checkpoint 和 Monitor/Laptop 隔离。
- 明确证明 WI 不会因共享前缀匹配 WW/WX；XPS family 的无限定单选会澄清；Checker 和报告不能扩大范围。
- V1 默认编排器、Monitor 数据、Laptop Product Pack、冻结 30 条任务、评分规则和所有历史结果未修改。
- `laptop-020` 继续拒绝把 CN 字段用作 US 事实。
- 全量门禁首次发现基线 `b6ae43d` 已存在的两条 Monitor Proposal 失败：`contains_all` 被一律按 `string_list` 归一化，导致 Monitor 合法的字符串字段列表操作失效。独立基线快照复现同样失败后，本轮恢复领域无关兼容语义：`string_list` 维持整列表归一化，字符串字段逐项归一化。未修改 Domain Pack、表达金标或历史结果；对应测试由 2 failed 恢复为通过。

最终门禁：身份/Agent `45/45`、Laptop 工具链 `8/8`、Quote/Span/澄清 `48/48`、Monitor V2 `35/35`、V1 Tag 原始测试文件 `94/94`、CI 等价全量 `346/346`。Ruff、Compileall、JavaScript `12/12`、PowerShell `5/5` 和 Markdown 链接检查均通过。

## 8. 限制与下一步门槛

- 当前只完成身份与 Scope 根因修复；没有运行剩余 10 条 specialist，没有运行 Open Research、Memory 专项或完整故障矩阵。
- LangGraph 仍是兼容封装且默认关闭；本轮没有切换默认编排器。
- `open_unknown_product` 只建立安全边界；何时进入 Open Research 仍由上层显式模式和后续阶段决定。
- V2-6C 仍为阻断状态，不能宣称完成。

创建新 Holdout 前必须先冻结新的、未被开发者或规则调试查看的任务与金标，记录 SHA-256 和评分规则；再完成当前实现、V1/V2 回归、工具/Checkpoint/事件兼容及安全门审查。未经新授权不得创建或运行该 Holdout。
