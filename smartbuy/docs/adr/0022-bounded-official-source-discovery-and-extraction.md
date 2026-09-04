# ADR-0022：有界官方来源发现与静态多格式提取

- 状态：Accepted for repair branch；release blocked
- 日期：2026-09-04
- 关联：[V2-9F 报告](../v2/v2_9f_online_research_repair_report.md)

## 背景

V2-9D 独立 Online 首测只安全降级，没有完成字段取证；V2-9E exposed regression 最高为 `5/15`。主要断点是概率搜索漏召回目标地区官方页、单一候选被 403/动态页面阻断、规格位于内嵌状态或附件，以及跨品类字段表达不能稳定规范化。安全隔离本身没有失败，不能通过放宽地区、型号或 Evidence 权限提高完成率。

## 决策

1. 保持 `SourceSearchProvider` 可插拔，但当前正式路径仍只用 Zhipu。执行最多四条确定性查询：字段/地区、技术支持/地区、广域官方身份和仅在无 usable 时的搜狗回退。
2. Provider 域名过滤和 `site:` 只作召回提示。所有结果均由确定性代码重新校验 HTTP(S)、规范 hostname、官方 allowlist、精确型号和目标地区。
3. 在身份已确认的官方页面内，可发现 canonical、hreflang 及型号绑定的规格/支持/PDF 链接；目标页仍需重新抓取并通过 SSRF、跳转、域名、型号和地区门。
4. 静态提取按 JSON-LD、规格表、definition list、普通正文、非执行内嵌状态和受限 PDF 处理。响应字节、PDF 页数、片段数、相关链接数与超时全部有硬上限。
5. 抽取规则由 Domain Pack 声明并在加载时校验。找不到字段保持 unknown；同一字段多值保留 conflict；搜索摘要不能成为 Evidence。
6. Open Evidence 继续保持请求级、仓库外、短 TTL 和 `usable_for_trusted_checker=false`，不能被提升为治理数据或 Trusted Checker 输入。
7. 不默认引入 Playwright。静态页面不可访问、动态渲染失败、PDF 无文本或访问受限时显式 degraded，禁止绕过网站限制。

## 否决方案

- 不按 `case_id`、品牌、具体型号或评测目标 URL 写补丁。
- 不把其他地区或 unknown 地区页面当作目标地区证据。
- 不把搜索标题、摘要、模型常识或第三方页面当作规格 Evidence。
- 不为了召回同时调用三个搜索 Provider；V2-9F 仍未证明额外复杂度能解决地区与提取瓶颈。
- 不执行网页脚本，不自动下载附件，不绕过 403、登录、验证码或访问策略。

## 后果

修复前漏斗的官方域名/型号/地区/正文层分别为 `14/15`、`14/15`、`5/15`、`7/15`；V2-9F exposed regression 改善到 `15/15`、`15/15`、`8/15`、`10/15`，实际 Open Evidence 完成为 `6/15`。所有安全越界保持为 0，但 `6/15`、Laptop `1/5` 和字段核验 `11/18` 未达到发布门槛，因此此决策只证明通用静态链路更可观察、更安全地覆盖部分页面，不支持冻结 RC3。
