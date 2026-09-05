# ADR-0023：RC3 发布范围收敛为 Trusted Core，Online Research 保持 Experimental

- 状态：Accepted for V2-9G scope decision；RC3 尚未冻结
- 日期：2026-09-05
- 关联：[V2-9G 报告](../v2/v2_9g_online_scope_and_feasibility_report.md)

## 背景

Online Research 的不可覆盖历史为：第二次独立评测首次 `0/15`，V2-9E exposed regression 最高 `5/15`，V2-9F exposed regression `6/15`。V2-9F 报告中的“地区匹配 `8/15`、页面获取 `10/15`”是不同候选分支分别取 `any` 后形成的非单调统计，不能解释为八个目标地区分支中抓取成功了十个任务。

V2-9G 按候选 lineage 重算后，任务级累计漏斗为 `15 → 15 → 15 → 8 → 6 → 6 → 6 → 6 → 6`。随后只对已暴露失败类型做默认关闭的 Playwright 和 Bocha 小规模 PoC，没有运行新的 Holdout 或完整 15 条付费回归。

## 证据

- 52 个候选分支、52 次页面尝试中共有 33 次 2xx；其中只有 15 次位于最终可验证目标地区的候选分支。旧“页面获取 10/15”包含 4 个只在错误/未知地区分支上成功抓取的任务。
- Playwright 测试 5 个受控任务，恢复 1 个此前零 Evidence 的 Monitor 任务，并为另一个 Monitor 任务增加 1 个请求字段；Laptop 新增 Evidence 为 0。
- Bocha 只在 Zhipu 没有目标地区候选的三类各一条任务上回退，新增目标地区候选和 Evidence 均为 0。
- 保守投影为完成 `7/15`，Monitor/Laptop/Headphone 为 `3/5`、`1/5`、`3/5`，有 Evidence 任务字段核验 `15/21（71.43%）`。没有同时达到 `8/15`、每品类 `2/5` 和字段 `80%`。
- 错误域名/型号/地区接受、搜索摘要转 Evidence、Open Evidence 进入 Trusted Checker 均为 0。

## 决策

1. 后续 RC3 的发布范围调整为 **Trusted Multi-domain Decision Core**。三品类治理数据、Product/KB 查询、Evidence Check、确定性 Checker、Ranker、Memory 和可审计降级属于核心候选范围。
2. Online Research 标记为 **Experimental/Beta**。只声明已实现受控官方来源搜索、请求级临时 Open Evidence、失败降级和 Open/Trusted 隔离；不承诺稳定网页取证、全市场研究或实时价格。
3. 安全返回 `unknown` 只算安全终态，不算网页研究完成。错误/未知地区、搜索摘要和 Open Evidence 继续不能进入 Trusted Checker。
4. 不把 Playwright 接入正式运行链。现有 PoC 默认关闭，仅在 `smartbuy.eval` 下验证可行性；浏览器依赖来自现有上游 `search` dependency group，不修改 `uv.lock`。
5. 不实现 Composite Provider。三条 Bocha 回退没有增加目标地区覆盖，额外 Provider 会增加凭据、费用、延迟和维护面，却没有证据证明可跨品类稳定达到发布门槛。
6. 不运行新的 15 条回归，因为有限 PoC 已证明联合门槛不可达；避免为已暴露任务继续付费调参。

## 发布表述

允许：

- “Trusted Core 覆盖 Monitor、Laptop、Headphone 三个治理品类。”
- “Online Research 为实验能力，展示受控搜索、临时证据、明确降级与安全隔离。”
- “V2-9F 已暴露回归完成网页字段取证 `6/15`；V2-9G 有限 PoC 投影 `7/15`，不是完整回归。”

禁止：

- “支持全市场实时研究”或“稳定完成网页取证”。
- 把安全降级 `15/15` 写成 Online 研究完成 `15/15`。
- 把 Playwright PoC 写成生产能力，或把暴露任务写成新 Holdout。

## 后果

RC3 仍未冻结，也没有 PR、Tag 或 Release。若未来重新评估正式 Online 能力，应先证明跨品类的目标地区发现、受控浏览器提取和字段闭包能稳定达到门槛，再由独立评测方创建新的未见任务；不得沿用这 15 条暴露任务得出发布结论。
