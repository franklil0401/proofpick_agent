# ProofPick V2-4C：地区证据可比性收尾报告

最后更新：2026-09-02

分支：`feature/proofpick-v2`

基线：`fd97b7fd19a2ba35905152583d401565f3a7b371`

结论：地区不匹配与跨地区冲突语义已修复；V2 功能仍默认关闭，未进入 V2-5

## 1. 原测试为何是假通过

V2-4 的四类冲突参数化测试首次为 4/4 passed，但第二类夹具只有一条 `CA` 证据、目标地区为 `US`。旧实现只要发现 `source_region != product_region` 就返回 `conflict`，因此测试虽然通过，却没有提供冲突所需的 US/CA 双边证据；语义审计实际只有 3/4 类冲突完整。

本报告保留上述历史结果，不修改 V2-4 报告、冻结评测或首次结果。第二类夹具现已改为同型号、同字段、US 90W 与 CA 65W 两条完整证据，并断言双方 Evidence ID、地区、值、单位和来源均被保留。

## 2. 修复后的两层语义

目标地区核验与跨地区比较现在是两个独立层次：

- `target_region_status` 只使用目标地区正文证据，供 Open Evidence Check 判断目标地区字段是否 matched/unknown/conflict；
- `cross_region_conflict` 只说明其他地区版本是否存在不同值，不能把其他地区值当作目标地区事实；
- `target_region_evidence_ids` 与 `non_target_region_evidence_ids` 分开保存；
- `non_comparable_evidence` 保留错误地区或跨地区参考记录，但不参与目标地区 matched；
- `conflict_evidence_ids` 在跨地区异值时必须同时包含目标地区和非目标地区证据；
- Open Report 仍固定 `trusted_eligible=false`，Open Evidence 仍不能转换为 Trusted Checker 输入。

状态变化如下：

| 场景 | 修复前 | 修复后 |
|---|---|---|
| 目标 US，只有 CA 证据 | `conflict` | `unknown`，`reason=region_mismatch_only` |
| US 90W，CA 65W | `conflict`，但地区层次未分离 | `target_region_status=matched`、`cross_region_conflict=true`、总体 `conflict` |
| US 90W，CA 90W | 可能因地区不同误报 `conflict` | 目标地区 `matched`，`cross_region_conflict=false` |
| 目标 US，只有 CA 90W | `conflict` | 即使数值看似相同仍为 `unknown` |

单边错误地区证据不是一组可比较的矛盾命题，因此不能叫 conflict；它只能证明“尚未取得目标地区证据”。跨地区异值会被保留为差异，但不能覆盖目标地区事实。

## 3. 专项测试与冲突覆盖

六组地区专项测试全部通过：

1. `single_wrong_region_evidence_is_unknown`：只有 CA、目标 US，返回 unknown、`region_mismatch_only`、非 conflict。
2. `two_regions_with_different_values_preserve_conflict`：US/CA 异值，双方证据元数据完整保留。
3. `two_regions_with_same_value_are_not_conflict`：同值跨地区误报 conflict 为 0。
4. `same_value_wrong_region_only_is_still_unknown`：只有错误地区时不以数值相同推断目标地区。
5. `target_region_evidence_not_overridden_by_other_region`：CA 值不能覆盖 US 值。
6. `cross_region_conflict_cannot_grant_trusted_eligibility`：冲突无法获得 Trusted 资格。

四类双边冲突覆盖为 4/4：治理证据与网页证据、同型号不同地区异值、旧值与新值、同一页面多个正文值。每类均保留双方证据；跨地区冲突 Schema 还要求 conflict IDs 同时覆盖目标与非目标地区，否则校验失败。

V2-4 Open Research 定向测试为 27/27；`smartbuy/tests` 为 228/228，加入上游配置脱敏 node 的 CI 等价套件为 229/229；既有 3 条上游依赖弃用警告不影响结果。V1 的 94 个原始 `smartbuy/tests` node id 独立执行为 94/94，冻结数据、历史评测和 V1 Checker 文件无变更。Ruff、Compileall、JavaScript 12/12、PowerShell AST 5/5、Markdown 相对链接 300/300 均通过。

## 4. PD3226G 回放与兼容边界

使用仓库外保存的 21 条脱敏临时证据离线重放 `BenQ PD3226G/US`，未访问网络或模型：6 个目标字段仍为 matched，unknown 0、conflict 0、跨地区 conflict 0、`trusted_eligible=false`。因此 V2-4 已发布的真实案例结论没有变化。

兼容性结论：

- 新字段均为带默认值的向后兼容 Open Research Schema 字段；V1 公共四态定义没有修改；
- 默认关闭 V2 开关时行为差异为 0；
- Product Pack、SQLite、Chroma、正式 Evidence Ledger、长期 Memory、冻结任务和历史指标均未修改；
- Governed Evidence 仍不会被 Open Evidence 覆盖；只有目标地区证据可支持目标地区 matched；
- 本轮 API 调用 0，费用 ¥0。

## 5. 限制与下一阶段门

- 跨地区同值只表示“本次两条证据没有发现差异”，不证明所有地区配置永久相同。
- `region_mismatch_only` 仍需要目标地区正文或后续人工治理才能变成 matched。
- Open Evidence 只在请求级临时范围内有效，不能自动晋升到正式 Ledger。

V2-5 的语义前置条件已经满足，但仍须用户另行授权；在此之前不得开始自然约束理解、主动澄清或其他 V2-5 代码。

决策依据见 [ADR-0013](../adr/0013-regional-evidence-comparability.md)，运行边界见 [V2-4 运行说明](v2_4_runtime.md)。
