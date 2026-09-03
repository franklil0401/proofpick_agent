# ADR-0016：确定性商品身份与不可扩大的 Candidate Scope

- 状态：Accepted for V2-6C-R1
- 日期：2026-09-03
- 范围：通用 Domain Agent 的商品身份、候选范围和证据闭包

## 背景

V2-6C 首次 Laptop Holdout 为 `3/10`。共享前缀、family 多配置、地区否定和各工具独立重建候选，使未点名配置进入 Evidence、Checker 或报告。Prompt 调整不能保证下游节点不扩展候选，也无法形成数据/索引版本闭包。

## 决策

在约束解析和工具执行前，由确定性 `ProductIdentityResolver` 根据 Product Pack Registry 生成不可变 `ResolvedProductScope`：

1. 只承认完整 token 的 configuration、Part Number、product ID、唯一型号/别名和 family 匹配。
2. LLM 可以提出 mention，但不能授予商品身份或生成候选集合。
3. 精确配置只允许一个 product；显式比较只允许被点名项；无型号筛选才允许全 Catalog。
4. family 多配置默认澄清；未知本地型号进入 `open_unknown_product`，不得以相似商品替代。
5. Scope 携带 domain、产品/配置/地区、Data/Index Version 和指纹，并贯穿 State、工具、Checkpoint、事件和 Report。
6. Product Query、KB、Evidence、Checker 或 Report 出现范围扩展、版本错配、配置/地区错绑时 fail closed。
7. Checker 的候选集合必须与 Scope 完全相等；LLM 和工具节点不能绕过或改写该结果。

## 备选方案

- 继续优化 Prompt：拒绝。无法约束 SQL、KB、Checker 和报告之间的集合扩张。
- 模糊匹配或 startswith：拒绝。共享前缀会把不同 SKU 授权成同一可信身份。
- 每个工具独立解析身份：拒绝。会产生多个事实来源和不可审计的范围漂移。
- 将型号规则写进通用代码：拒绝。破坏 Domain Pack 可扩展性并形成测试专属分支。

## 后果

收益是候选集合、证据和 Checker 输入可由同一指纹审计，错误配置和地区默认关闭。代价是 family 单选和未知型号更容易要求澄清或显式 Open Mode，且所有 Provider/索引适配器必须返回完整身份 metadata。旧 V1 API 通过可选字段保持兼容；V1 默认路径和冻结结果不变。

## 验证

40 条身份/Scope 专项测试通过；已暴露的 20 条离线回归为 `20/20`，推荐事实证据覆盖 `75/75`，Scope/Checker 越界为 0。原始失败结果保持不变。详细证据见 [失败审计](../v2/v2_6c_identity_scope_failure_audit.md)和[修复报告](../v2/v2_6c_identity_scope_repair_report.md)。
