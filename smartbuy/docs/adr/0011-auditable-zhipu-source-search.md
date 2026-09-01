# ADR-0011：使用可插拔智谱 Provider 实现受控来源搜索

- 状态：Accepted
- 日期：2026-09-01
- 决策范围：V2-3 Source Search MVP

## 背景

V1 的 `web_search` 是明确的 unavailable 占位工具。V2-3 需要发现真实官方来源 URL，但搜索元数据不能直接成为字段证据，也不能影响 Constraint Checker。搜索 API 的索引覆盖具有概率性，域名正确也不代表型号和地区正确，因此“搜索命中”不能等同于“事实核验成功”。

只读 Provider 选型实验使用同一组 8 条已治理官方页面任务，且只接受 Provider 结构化结果中的 URL：

| Provider | 精确地区覆盖 | 结论 |
|---|---:|---|
| 阿里云百炼 | 4/8 | 能返回结构化来源，但官方页面覆盖不足 |
| 智谱 Web Search | 6/8 | 三者中最高；`search_pro_sogou` 在预选实验中恢复 3 个任务 |
| 博查 Web Search | 1/8 | 没有提高组合覆盖 |
| 三家组合 | 7/8 | 仍无法保证所有目标地区页面被索引 |

缺失页面真实存在，不能通过接受错误地区、地区未知页面或硬编码目标 URL 来修改答案。

## 决策

1. 定义可插拔 `SourceSearchProvider`，V2-3 只实现 `ZhipuSourceSearchProvider`。
2. 第一引擎为 `search_pro`；没有 `region_matched` 候选时，有界调用 `search_pro_sogou`。
3. 不实现 Bailian/Bocha 正式 Provider，也不实现 Composite Provider。三 Provider 会增加延迟、费用和维护复杂度，却仍不能解决全部地区缺口。
4. `DeterministicSourceValidator` 独立校验 HTTP(S)、规范化 hostname、合法子域、完整型号 token 和地区。Provider 的站点过滤只作为检索提示，不作为安全边界。
5. 候选状态为 `region_matched`、`region_mismatch`、`region_unknown`、`model_mismatch`、`domain_rejected`、`invalid_url`。只有 `region_matched` 可以进入 `usable_candidates`。
6. `region_mismatch` 与 `region_unknown` 只能进入有界 `navigation_candidates`，并固定 `usable_for_evidence=false`、`usable_for_checker=false`。
7. Source Candidate 不能转换为 EvidenceRecord 或 Checker 输入；转换入口会显式抛出 `SourceIsolationError`。
8. 功能由 `PROOFPICK_SOURCE_SEARCH_ENABLED` 显式开启，默认关闭。关闭、无凭据或 Provider 故障时，V1/V2 本地 KB + SQL 路径保持不变。
9. 401/403 不重试；429、5xx 和超时只有限重试。原始扫描上限 50、可用结果上限 10、单请求调用/费用/总延迟有硬边界。
10. 只缓存完整的公开 URL 元数据成功结果；错误、空结果和不完整结果不缓存。缓存键包含 Provider/版本/引擎/查询/型号/地区/域名/freshness。

## 证据

最终精确站点复测中，`search_pro` 直接命中 4/8，搜狗回退恢复 2 条，最终 6/8；另外 2 条安全返回 `no_region_matched_source`。8/8 均真实执行，错误地区、unknown 地区、白名单外来源和错误型号进入可用结果均为 0。首次使用根域过滤的 4/8 结果也保留在 [V2-3 报告](../v2/v2_3_source_search_report.md)，不以复测覆盖。

## 影响

- 优点：真实来源发现、严格地区安全、失败可解释、费用有界，且不污染既有证据和推荐资格。
- 代价：搜索覆盖率不是 100%；同一查询可能随索引变化而波动；开启后增加网络延迟和固定调用费用。
- V2-4 前置：只有后续完成 canonical/hreflang 检查、正文提取和字段级核验后，目标地区页面才可能形成 EvidenceRecord。本 ADR 不授权这些能力。

## 未采用方案

- 接受其他地区官方页面：违反地区安全规则。
- 将摘要或模型正文作为 Evidence：无法审计原始字段事实。
- 硬编码已知 URL：不能验证 Source Search 的真实发现能力。
- 三 Provider 聚合：7/8 覆盖仍不完整，复杂度与费用不成比例。
