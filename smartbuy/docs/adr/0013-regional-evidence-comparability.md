# ADR-0013：目标地区证据与跨地区比较分层

- 状态：Accepted
- 日期：2026-09-02
- 决策范围：V2-4C Open Evidence 地区语义修复

## 背景

V2-4 的初始实现把“证据来自错误地区”直接视为 conflict。该规则不能区分“目标地区证据缺失”与“两个地区存在不同字段值”：目标 US、只有 CA 证据时并不存在可比较的 US 命题，应为 unknown，而不是 conflict。初始四类冲突测试因此出现测试 4/4 passed、语义覆盖仅 3/4 的假通过。

## 决策

1. 目标地区核验与跨地区比较独立建模。`target_region_status` 只由目标地区证据决定，`cross_region_conflict` 只报告不同地区版本的差异。
2. 只有非目标地区证据时返回 `unknown` 和 `reason=region_mismatch_only`；证据保留在 `non_comparable_evidence`，不能进入目标地区 matched。
3. 目标与非目标地区均有完整证据且值不同，整体返回 conflict，同时保留双方 Evidence ID、地区、值、单位和来源。跨地区 conflict 必须有双方证据，否则 Schema fail closed。
4. 两个地区值相同不自动构成 conflict。存在目标地区完整证据时按目标地区正常判断；只有非目标地区证据时仍为 unknown。
5. 其他地区证据不能覆盖目标地区值。Open/Trusted 隔离、`trusted_eligible=false` 和 Open Evidence 禁止进入 Trusted Checker 的规则不变。
6. 通过向后兼容字段扩展 Open Research Schema，不修改 V1 Evidence 四态、V1 API、Checker、治理数据或历史结果。

本 ADR 对 [ADR-0012](0012-governed-web-extraction-and-open-evidence.md) 中“地区不一致即 conflict”的宽泛描述作精确补充，不改写其历史结论。

## 证据

- 六组地区专项测试覆盖错误地区单边证据、异值/同值跨地区、目标值不被覆盖和 Trusted 资格隔离。
- 四类真正的双边冲突为 4/4，第二类现使用 US 90W 与 CA 65W 两条证据。
- V2-4 Open Research 定向测试 27/27，`smartbuy/tests` 228/228。
- 仓库外 PD3226G 脱敏证据离线回放仍为 6/6 matched，unknown/conflict 均为 0。
- 在线 API 调用 0，费用 ¥0。

## 影响与边界

- 优点：单边缺失不再伪装成冲突，跨地区异值仍能 fail closed，且目标地区事实不会被其他地区覆盖。
- 代价：Open Report 增加地区比较元数据；调用方若需要展示跨地区参考，应读取新字段，旧调用方仍可只读取原有四态和 evidence。
- 同值跨地区不是全局一致性证明；目标地区证据缺失时仍需网页恢复、人工治理或明确 unknown。
