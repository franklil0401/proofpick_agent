# ADR-0012：受控网页抽取与 Open Evidence 隔离

- 状态：Accepted
- 日期：2026-09-02
- 决策范围：V2-4 Web Extractor、临时证据与开放研究模式

## 背景

V2-3 只能发现官方 URL。搜索标题和摘要不是网页正文，也不能证明某个字段值。数据库外商品如果直接进入 V1 `EvidenceRecord` 或 Constraint Checker，会把概率性搜索结果伪装成治理数据，并突破 Trusted 推荐资格边界。

## 决策

1. 采用 `Source Candidate → URL Safety → Static HTML Extractor → Evidence Normalizer → Temporary Evidence Store → Open Evidence Check → Open Research Report` 的单向链路。
2. `trusted` 仍是默认模式。只有请求显式指定 `open` 且两个特性开关均开启时，Agent 才注册并调用 `web_extractor`。
3. Web Extractor 只接受本轮 Source Search 已观察的候选 URL。用户或 LLM 直接提供的任意 URL 会在 Agent 门禁处被拒绝。
4. URL Policy 仅允许白名单官方域名的 HTTP(S)，拒绝 userinfo、异常端口、IP 字面量和 DNS 解析后的非公网地址；每次重定向都重新校验，最多 3 次。HTTP 客户端 `trust_env=false`，不继承系统代理。
5. 只解析静态 HTML/XHTML，解压后上限 5 MiB。JSON-LD、规格表/定义列表优先，其次为字段相关的可见文本。PDF、二进制、超大页面、超时和静态正文不足均显式降级；本阶段不引入 Playwright。
6. 只保存字段核验所需的短片段、定位、来源、地区、抓取时间和内容哈希，不保存完整 HTML。常见跟踪参数在请求前被移除。
7. Open Evidence 固定 `evidence_scope=open`、`usable_for_trusted_checker=false`、TTL 24 小时。临时存储位于仓库外，以 user/session/thread/request 的不透明哈希隔离，原子写入并校验 Schema。
8. `OpenEvidenceRecord.to_trusted_checker_input()` 显式失败；Open Report 固定 `trusted_eligible=false`，不能包含正式推荐。LLM、工具节点和报告层都不能提升该资格。
9. Open Evidence 与治理证据可以比较，但保留双方作用域。值、地区或观察期不一致时返回 `conflict`，不静默覆盖；无正文片段返回 `unknown`。
10. canonical/hreflang 只用于从 V2-3 navigation candidate 发现新的候选 URL。新 URL 必须重新经过安全、型号、地区和正文抓取，发现链接本身不是证据。
11. “晋升”在本阶段仅能导出 `review_required` 的 promotion candidate；不得自动修改 Product Pack、SQLite、事实卡、Chroma 或长期 Memory。

## 证据

- 21 条 V2-4 定向测试覆盖 SSRF、DNS 私网/回环/IPv4-mapped IPv6、恶意重定向、非 HTML、超大页面、超时、重定向上限、动态页面、临时存储、四类冲突、Agent 模式门和 Checker 隔离。
- 最终真实验证从智谱 Source Search 发现数据库外 `BenQ PD3226G` 美国官方页，普通 HTTPS 抽取成功并形成 21 条请求级临时证据；6 个目标字段全部核验，`trusted_eligible=false`。
- `LG 27GS95QE-B/CN` 与 `BenQ PD2725U/CA` 的 canonical/hreflang 自动恢复均未获得可安全抓取的目标地区页，保持降级和 unknown，没有硬编码 URL。
- `Dell P2725QE/CN` 的最终页面可抽取，但 USB-C 供电片段出现多值，按 `conflict` 保留，没有选取更漂亮的单值。

详细结果见 [V2-4 技术报告](../v2/v2_4_open_research_report.md)。

## 影响与边界

- 优点：数据库外商品可以获得可追溯正文证据，同时不污染治理数据或 Trusted 推荐集合。
- 代价：静态解析对动态站点和复杂营销页面覆盖有限；DNS 校验与后续连接之间仍存在通用 TOCTOU 风险，因此本实现是本地 MVP 安全门，不是生产爬虫沙箱。
- Open Evidence 只在单次研究范围内有效；重启、TTL 到期、关闭功能或删除请求数据后不会自动恢复。
- 本阶段没有 Evidence Promotion、浏览器渲染、开放 Web 全品类或 V2-5 自然约束能力。

## 未采用方案

- 将搜索摘要作为字段证据：不可复核原始正文。
- 自动写入正式 Ledger/Pack：缺少人工许可、地区、版本和冲突审查。
- 允许任意 URL 抽取：扩大 SSRF 与来源污染面。
- 使用浏览器自动化绕过动态页面或反爬：超出本地 MVP 的合规和安全边界。
