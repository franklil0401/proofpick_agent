# V2-7 可解释 Decision Ranker 技术报告

## 1. 结论

V2-7 已在 V2 Domain Agent 路径落地纯确定性的、Domain Pack 驱动的 Decision Ranker。Ranker 的输入和输出都被约束为 Checker `eligible_model_ids`，只能改变顺序与解释，不能新增候选、恢复淘汰项、改变 `eligible` 或覆盖硬约束。Monitor 与 Laptop 共声明 10 个场景，12 条离线 What-if 用例全部通过；本阶段 Ranker 与 Checker 的模型调用均为 0。

这是一组功能、回归和不变量验证，不是新的 Holdout，也不是泛化或生产 SLA。V2-6C 三轮冻结首测及 122 条 exposed regression 均未改写。

## 2. 实现边界

- 通用契约位于 [`smartbuy/ranking/models.py`](../../ranking/models.py)，包括 `RankingRequest`、`RankingCandidateInput`、`RankingEvidence`、`DimensionScore`、`RankedCandidate` 和 `RankingExplanation`。
- [`profile.py`](../../ranking/profile.py) 校验场景、维度、字段、来源权限、固定范围、枚举映射、权重和版本兼容性。
- [`ranker.py`](../../ranking/ranker.py) 只读取已治理字段和目标地区允许来源的 Evidence；源码中不包含显示器或笔记本业务字段常量。
- V2 [`DomainDecisionAgent`](../../agent/domain_agent.py) 在 Checker 之后调用 Ranker；V1 [`agent/ranking.py`](../../agent/ranking.py) 原样保留。
- `OrchestratorRequest`、ReAct 和 LangGraph 共享同一组排序参数与结果 Schema；默认编排器仍是 ReAct。
- `DecisionReport` 与 SSE 公开 `ranking_started/ranking_completed`、场景、候选数、得分贡献、Evidence、unknown、Memory 和降级状态，不公开 Prompt 或隐藏推理。

## 3. 安全不变量

运行时同时验证：

```text
ranker_input == checker_eligible
ranker_output == checker_eligible
recommended_model_ids == ranked_product_ids
```

`RankingRequest` 拒绝 Scope 外输入；Ranker 在返回前再次比较集合；`DecisionReport` 还会验证排名顺序和 Checker 资格。Profile、Ranker 或 Memory 异常时，使用 `product_id` 升序的稳定回退顺序，保留完整 Checker 合规集合，并显式输出 `ranking_degraded=true`。Checker 淘汰原因仍保留在候选审计数据中。

## 4. 评分方法

每个场景由 Domain Pack 提供维度集合。对候选 `c`：

```text
score(c) = Σ weight(d) × normalized(c, d)
```

- 数值维度使用 Profile 固定上下界并截断到 `[0,1]`，不按本次候选池动态缩放。
- 枚举分值完全来自 Domain Pack；布尔维度只接受真实布尔值。
- 值必须具有同一商品、同一目标地区、相同字段值且 `source_type` 在白名单内的 Evidence，才参与评分。
- unknown 或无合格 Evidence 的维度贡献为 0，但理由明确为“未知”，不描述成商品缺点。
- 分数保留 8 位小数；同分按 `product_id` 升序；相同输入可序列化为相同字节。
- 局部权重覆盖会显式重新分配未覆盖维度的剩余权重，并输出完整 `effective_weights`；非法维度、负数、超过 1 或无法形成总和 1 的输入会拒绝并进入显式回退，不静默修正。

报告固定声明：“该分数用于当前用途和偏好下的相对排序，不代表商品的绝对质量。”

## 5. Domain Pack Profiles

| Domain | 场景 | 由 Pack 声明的维度 |
|---|---|---|
| Monitor | `office_text` | 分辨率、USB-C、USB-C 视频 |
| Monitor | `gaming` | 刷新率、分辨率、OLED |
| Monitor | `creative_color` | 分辨率、面板类型、尺寸；不推断未治理色域/色准 |
| Monitor | `laptop_docking` | USB-C 供电、视频、接口 |
| Monitor | `desk_fit` | 宽度、重量 |
| Laptop | `office` | 内存、存储、电池容量、重量 |
| Laptop | `software_development` | 内存、存储、电池容量、重量 |
| Laptop | `creative_work` | 内存、存储、治理显存、分辨率 |
| Laptop | `gaming` | 治理显存、刷新率、内存、存储 |
| Laptop | `portability` | 重量、电池容量、厚度 |

Laptop Profile 不含价格：当前价格观察为 0。CPU/GPU 型号不会被映射为臆测性能分数；显存只是已治理的容量事实。电池容量不表述为实测续航；续航、温度和噪声只有在允许的专业测评来源存在时才可进入未来 Profile。

## 6. What-if 结果

12 条确定性夹具使用同一 Checker 合规集合；每条都与默认 Profile 结果进行字节比较，并保留排序、分数或解释变化。

| Domain | What-if | 结果 |
|---|---|---|
| Monitor | 办公 → 游戏 | 通过，集合不变，排序/贡献变化 |
| Monitor | 办公 → 创作 | 通过，集合不变，贡献变化 |
| Monitor | 办公 → 笔记本扩展 | 通过，集合不变，排序/贡献变化 |
| Monitor | 办公 → 桌面空间 | 通过，集合不变，排序/贡献变化 |
| Monitor | 提高文字分辨率权重 | 通过，显示有效权重与贡献变化 |
| Monitor | 开启 Memory 召回游戏场景 | 通过；关闭后恢复默认 Profile |
| Laptop | 办公 → 软件开发 | 通过，集合不变，排序/贡献变化 |
| Laptop | 办公 → 创作 | 通过，集合不变，排序/贡献变化 |
| Laptop | 办公 → 游戏 | 通过，集合不变，贡献变化 |
| Laptop | 办公 → 便携 | 通过，集合不变，排序/贡献变化 |
| Laptop | 提高办公内存权重 | 通过，显示有效权重与贡献变化 |
| Laptop | 开启 Memory 召回便携场景 | 通过；显式场景仍优先于 Memory |

合计 `12/12`。夹具共检查 120 个候选维度，其中 117 个具有可比较 Evidence，维度可用率 `117/120`（97.50%）；所有实际计分事实均绑定 Evidence，追溯率 `117/117`（100%）。其余 3 个维度保持 unknown、贡献 0。

## 7. 回归与成本

- V2-7 Ranker/Memory/API 与 Laptop 双编排器定向验证：`53/53`。
- V2-6C-R4 回归 `40/40`，V2-5C/澄清回归 `48/48`，Laptop 工具链 `24/24`，Monitor V2 回归 `27/27`。
- V1 原始 18 个测试文件保持 `94/94`；没有改写 V1 历史文档中的既有测试口径。
- `smartbuy/tests`：`418/418`；CI 等价命令另含 1 项上游配置脱敏安全测试，共 `419/419`，仅保留既有 3 条上游弃用警告。
- ReAct/LangGraph 对代表 Laptop 请求输出相同 Checker 集合、排序和完整 `RankingExplanation`。
- Ranker 越权候选、软偏好恢复淘汰候选、候选集合变化：均为 0。
- 排名异常回退后 Checker 集合丢失：0。
- Ranker API 调用 0，Checker 新增 API 调用 0，Token 0，新增费用 ¥0。

Ruff、Compileall、全仓库 JavaScript `12/12`、PowerShell AST `5/5`、Markdown 相对链接 `380/380`、敏感凭据与新增禁止产物扫描均通过。8000/9000/9001 端口无监听。

## 8. 已知限制

- Profile 权重是透明的工程偏好，不是学习到的效用函数或客观质量分。
- 当前 What-if 是确定性功能测试，不是独立用户研究。
- V2 Domain Agent 已接入 Ranker；公开默认 V1 路径和默认 ReAct 没有切换。
- 没有合格 Evidence 的维度不会参与评分，因此某些候选可能稳定同分并按 ID 排序。
- V2-8 是否引入新 Domain Pack，必须在本阶段验收后另行授权。
