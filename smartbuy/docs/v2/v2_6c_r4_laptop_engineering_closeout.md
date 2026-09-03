# V2-6C-R4 Laptop E2E 工程收尾报告

## 结论

V2-6C-R4 已完成 Laptop E2E 的工程收尾，但**没有执行新的独立发布评测**。最终 122 条已暴露回归为 `116/122`（95.08%），清晰硬约束 F1 为 96.60%，推荐事实证据覆盖为 `436/445`（97.98%）；Scope、Checker、Report、错配置、错地区、unknown 误报、澄清绕过和充分证据下错误空推荐均为 0。该结果不是 Holdout 或泛化指标。

三轮冻结验证的首次结果继续按原结论保留：轮 1 `17/24`、轮 2 `16/24`、轮 3 `21/24`。第三轮仍因 Scope 越界 1 和错误空推荐 `1/8` 未通过联合门槛，不能被 R4 回归结果追溯改写。

## 第三轮三条失败链路

| case | 冻结预期 | 冻结实际与首错 | 通用修复 |
|---|---|---|---|
| `laptop-r3-v3-001` | `H7606WI` 为 include，`H7606WX` 为不可比较的 exclude；`exact_fact_verification`；Scope/KB/Evidence/最终报告仅 WI；无 SQL/Checker | 两个 ProductReference 都为 include，Intent 为 `recommendation_filter`，Scope/KB/Evidence 同时含 WI/WX，最终空；首错 `product_scope_resolution` | 增加品类无关的事实查询动词和“某型号参数不得作为另一型号证据”的引用极性；没有型号、品牌或 case 分支 |
| `laptop-r3-v3-002` | H7606 Family + RTX 5080 + 16GB 唯一收敛到 `H7606WW`；SQL、KB、Evidence、Checker 和最终候选均为 WW | Scope、SQL、KB、Evidence、Checker eligible 已为 WW，但残留整句 unsupported fallback 令报告拒答；首错 `result_classification` | Pack 的确定性字段已解释整句时，只失活整句级通用 fallback；窄范围 unsupported 保留；结果状态改由确定性分类器计算 |
| `laptop-r3-v3-011` | `xps13-9350-oled-ca` 是精确身份；Intent 为事实核验；requested fields 为配置号、分辨率、系统；无购买约束 | Scope 为正确 CA 配置，但别名中的 OLED 被激活为 `panel_type=OLED` 购买约束并触发 Checker，最终空；首错 `constraint_resolution` | 将身份 token/请求字段与购买约束分离；事实查询不会把别名片段反向变成硬约束 |

三条冻结现场中的 ProductReference、QueryIntent、Scope、ConstraintSet、工具候选、Evidence、Checker 与最终报告仍保存在不可覆盖的 `v2_6c_r3_validation_round3_first.json`；本轮没有修改该文件。

## 确定性安全门

新增 Checker 前、Checker 后和 Reporting 前三次通用集合断言。`final recommendations ⊆ checker eligible ⊆ checker pool ⊆ candidate scope ⊆ domain catalog`；空 Scope 不恢复全库，排除项、错误配置和错误地区不能重新进入，Checker 返回池与输入池不一致时 fail closed。`DecisionReport` 的 Schema 还会拒绝 Checker 未授权的 eligible/recommended 候选。

结果分类器把推荐、无候选、证据不足、待澄清、不支持、工具失败和安全阻断分开。工具失败不再伪装成业务无候选；澄清未完成不能推荐；有证据的事实回答不再被“推荐候选为空”误判为失败。

变形测试执行 1134 组确定性断言，覆盖 include/exclude、Family/配置/地区交集、空 Scope、Checkpoint 变宽、结果分类、int/float、TB/GB、覆盖/取消、requested fields 隔离、Evidence 完整性和 eligible/report 子集，所有断言通过。

## 122 条已暴露回归

| 迭代 | 任务 | F1 | 证据覆盖 | Scope/Checker/Report 越界 | 充分证据下空推荐 |
|---|---:|---:|---:|---:|---:|
| iteration01 | 109/122 | 96.60% | 420/429 | 0/0/0 | 7/44 |
| iteration02 | 113/122 | 96.60% | 420/429 | 0/0/0 | 3/44 |
| iteration03 | 113/122 | 96.60% | 420/429 | 0/0/0 | 3/44 |
| iteration04 | 116/122 | 96.60% | 436/445 | 0/0/0 | 0/44 |
| iteration05（最终复核） | 116/122 | 96.60% | 436/445 | 0/0/0 | 0/44 |

最终 TP/FP/FN 为 `128/3/6`，Precision 97.71%，Recall 95.52%。错误配置、错误地区、unknown 误写、澄清绕过和非 Domain Pack 字段激活均为 0。各次结果使用独立文件保存；未覆盖冻结任务、首次结果、SHA-256、run_id 或 RC。

## Open Research

在本地 12 个配置之外，对 ASUS Zenbook S 14 UX5406 / US 执行真实链路：智谱 Source Search 动态发现官方 URL，随后完成 URL/地区/型号校验、静态抽取、字段规范化、请求级 Temporary Evidence、Evidence Check 与 Open Report。没有把目标 URL 写死在脚本中。

- 6 个字段 matched：`resolution=2880x1800`、`panel_type=OLED`、`memory_gb=32`、`storage_gb=1024`、`battery_wh=77`、`usb_c=true`。
- `weight_kg` 保留同页不同配置值导致的 conflict；显示尺寸、刷新率和 Thunderbolt 为 unknown，没有猜测补全。
- 18 条临时证据全部为 `evidence_scope=open`、`trusted_eligible=false`、`usable_for_trusted_checker=false`；进入 Trusted SQLite/Chroma/Checker 的数量为 0。
- 来源 URL、US 地区、observed_at 和 content hash 的完整率均为 100%；正文哈希为 `2ace066180ef9a94b639bcef380425752e14be9eb358335fbdde28b843b7466a`。
- 诊断与最终验证合计 9 次智谱搜索，估算费用 ¥0.31；无 qwen-plus、Embedding 或 Reranker 调用。早期 Dell 搜索无官方来源、Dell 页面抽取失败和首次 ASUS 规范化问题均未伪装成成功。

运行结果和临时证据位于仓库外；仓库只保存脱敏摘要和可复现脚本。

## Memory、故障矩阵与双编排器

- Memory：Monitor/Laptop 隔离、当前输入覆盖长期偏好、预算覆盖/取消/删除、pending/unsupported 不写入、关闭后不召回、Checkpoint 按 domain/thread 隔离均通过；跨品类污染 0。
- V1 控制故障矩阵 13/13：Reranker、LLM 401/403/429、Embedding、非法 SQL、SQLite、Chroma、Memory、Web unavailable、Checker、步骤上限和缓存损坏均按既定策略处理，敏感泄漏 0。
- V2 扩展路径覆盖 Source Search 认证/重试/空结果、Extractor 失败、Pack/Data/Index 版本不匹配、SQLite/Identity/Evidence 冲突、Checker 异常、Checkpoint 版本拒绝和 SSE 事件兼容；Checker 异常 fail closed，恢复后已完成收费工具重复调用 0。
- 10 条 Laptop 代表任务在 ReAct/LangGraph 下的 QueryIntent、CandidateScope、激活约束、Checker eligible、最终候选、拒答/澄清与安全边界一致。默认编排器仍为 ReAct，LangGraph 没有静默切换。

## 回归与成本

- `smartbuy/tests`：383/383。
- V1 原始测试文件：94/94。
- R4 定向安全、Open Research、工具链、Checkpoint/SSE、Memory 与双编排器组合：92/92。
- 本轮收费调用：智谱 Source Search 9 次，估算 ¥0.31；Token 计量不适用；Provider 重试 0。其余回归均离线，未重建索引。

完整静态、链接、安全、禁止产物、端口与 Git 结果见提交时的最终报告和 [R4 运行说明](v2_6c_r4_runtime.md)。

## 边界与下一步

- 暴露回归只能说明已知任务和不变量已稳定，不能证明新输入泛化；不写成 Holdout、盲测或生产 SLA。
- Open Research 只验证单个数据库外 Laptop 官方页面；网页结构、地区覆盖和动态页面仍可能导致安全降级。
- SQLite Checkpoint 与当前本地运行方式不是生产级多租户方案。
- V2-9 必须安排新的独立 Release Candidate 评测，优先由未参与开发的 Agent 生成和复核；在此之前不得发布新的泛化指标。
- 本轮完成后停止，不进入 V2-7。
