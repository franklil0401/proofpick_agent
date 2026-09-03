# ADR-0019：Headphone 来源权限与通用内核复用

- 状态：Accepted
- 日期：2026-09-03
- 阶段：V2-8

## 背景

耳机同时包含官方规格、专业测量和主观体验。若三类来源共享同一权限，主观评价可能被错误转换为硬事实，也会促使共享 Agent、Checker 或 Ranker 出现耳机专用分支。

## 决策

1. Headphone Domain Pack 独占字段、单位、别名、操作符、来源权限、Ranking Profile、Memory 白名单和声明式 Open Research 规则；共享生产模块不保存耳机型号、品牌或评测 case 特判。
2. `official_spec` 可支持官方连接、功能、续航和重量等事实；`professional_measurement` 只支持 Pack 明确授权的实测字段；`subjective_review` 只支持佩戴、声音倾向和通话主观观察。
3. 主观字段为 soft-only，不进入 Checker。Ranker 只有在 Profile 维度同时允许该字段及来源类型时才能使用，且只能改变 Checker 合规集合内的顺序。
4. Headphone 复用 `DomainDecisionAgent`、`DomainConstraintEvaluator`、通用 Product Query/KB/Evidence/Checker、`DeterministicDecisionRanker`、`DomainPreferenceMemoryStore` 和 ReAct/LangGraph 兼容适配器，不实现 `HeadphoneChecker` 或第二套 Ranker。
5. Open Research 网页字段提取规则由 Pack 声明，共享 Normalizer 只解释有界规则；页面相邻块只在精确目标型号上下文后的有限窗口内关联。Open Evidence 始终不进入治理 Ledger 或 Trusted Checker。

## 结果

- 12 个精确配置、4 个品牌、20 个来源、336 条字段证据；299/299 个非空 Checker 事实有 Evidence。
- 主观证据覆盖官方硬事实、进入 Checker、恢复不合规候选均为 0。
- 8 组 What-if 只改变排序，不改变 Checker 集合；相同输入字节一致。
- 三品类字段、数据、Evidence、索引和 Memory 交叉污染为 0；Headphone 代表任务的 ReAct/LangGraph 资格结果一致。

## 边界

当前数据只覆盖美国/加拿大销售配置；没有动态价格，预算约束保持 `unknown`。专业测量和主观来源仅提交自制短摘要与元数据，不能解释为普适产品结论。Open Research 的真实页面结果是临时、特定时间和地区的验证，不自动晋升为治理事实。
