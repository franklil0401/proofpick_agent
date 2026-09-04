# ADR-0021：通用意图修复、开放证据漏斗与语义 Manifest

- 状态：Accepted for V2 repair branch；release blocked
- 日期：2026-09-04
- 关联：[V2-9E 报告](../v2/v2_9e_generalization_repair_report.md)

## 背景

RC2 第二次独立评测显示 Checker、Scope leakage、unknown 和 Open/Trusted 隔离仍安全，但进入这些安全门之前存在约束遗漏、比较对象不完整、澄清绕过和网页取证覆盖不足。原运行 Manifest 又将时间、延迟和机器路径等易变字段纳入原始文件哈希，不能作为跨机器字节门禁。

## 决策

1. `fact_query`、`comparison` 与 `purchase_filter` 保持独立；requested fields 不自动成为购买硬约束。
2. 数字、单位、否定、覆盖和比较操作符由 Domain Pack 字段语义及确定性解析器校验；无法完整解释的硬条件在收费工具前澄清或 fail closed。
3. Product Reference 先确定初始 Scope，后续工具只允许取交集；明确比较对象必须全部进入 Evidence 闭包，且比较对象不等于推荐对象。
4. Source Search 的 Provider 站点过滤只是召回提示。宽检索结果仍必须通过本地域名、型号、地区校验；搜索摘要永远不是 Evidence。
5. canonical/hreflang 只用于安全发现候选，目标页面必须重新抓取、确认型号与地区并提取字段；Open Evidence 永不进入 Trusted Checker。
6. 语义 Manifest 哈希只包含代码/配置/数据成员及 Data/Index/Collection/文档数/维度/数据逻辑哈希。运行时间、路径、Token、费用和延迟保留在独立 audit envelope，不参与稳定哈希。

## 否决方案

- 不按 case_id、品牌、型号或目标 URL 加补丁。
- 不把错误地区、搜索标题或摘要提升为 Evidence。
- 不通过接受 unknown 或忽略未解析条件提高完成率。
- 不用修复后的 exposed regression 覆盖独立首次结果。
- 不部署浏览器绕过访问限制，也不把静态抽取失败伪装成已核验。

## 后果

Trusted exposed regression 从 72/90 的独立首次基线改善到 86/90，安全越界保持为 0；这仅用于修复验证。Online 提升到最高 5/15，但仍未达到发布门槛，V2 继续保持 Needs revision。语义 Manifest 可跨生成时间保持同一 Payload SHA，同时仍保留 RC2 原始字节审计。
