# ProofPick V2-4：Web Extractor、临时证据与开放研究模式报告

最后更新：2026-09-02

分支：`feature/proofpick-v2`

基线：`990c046d7a13c67a69549bb1657ae7fa6fd249da`

结论：V2-4 验收范围已完成；功能默认关闭，未进入 V2-5

## 1. 范围与真实案例

本阶段实现：

```text
Source Search
  → Source Candidate 状态门
  → URL Safety / 每跳重定向复核
  → 静态 HTML Extractor
  → Monitor Domain Pack Evidence Normalizer
  → 仓库外 Temporary Evidence Store
  → Open Evidence 四态核验
  → provisional Open Research Report
```

真实主案例选择 `BenQ PD3226G / US`。它不在 V1 的 12 个型号或 V2-2 的第 13 个型号中；URL 由智谱 Source Search 真实返回，页面无需登录、普通 HTTPS 可获取，标题和正文同时包含 32 英寸、4K、144Hz、Thunderbolt/USB-C 视频与 90W 供电。仓库只记录来源 URL、脱敏元数据和自制结论，不提交网页 HTML。

首次真实抽取暴露了营销对比轮播中的相邻型号尺寸/分辨率噪声，导致两个字段被正确标为 conflict。随后收紧确定性规则：可见文本中的尺寸和分辨率必须在同一有界片段出现目标型号；结构化表格/JSON-LD 不受此限制。没有修改目标值或静默丢弃真正的冲突。最终重新运行完整在线链路。

## 2. 实现与安全边界

### 2.1 URL 与 HTTP

- 独立 `URLSafetyPolicy` 只允许 HTTP(S)，拒绝 userinfo、非 80/443 端口、IP 字面量、白名单外域名和后缀欺骗。
- DNS 解析结果中出现 loopback、private、link-local、multicast、reserved、unspecified、非 global 或私网 IPv4-mapped IPv6 即 fail closed。
- 每次重定向都重新执行完整校验；上限 3 次；最终请求 URL 已被校验。
- `httpx.AsyncClient(trust_env=False, follow_redirects=False)`；连接 5 秒、读取 10 秒、总请求 20 秒。
- 流式读取解压后正文，HTML/XHTML 上限 5 MiB；PDF、图片、压缩包和其他内容类型不解析。
- 常见 affiliate/UTM 跟踪参数在请求和临时证据落盘前移除。

### 2.2 抽取与规范化

- 顺序：JSON-LD → 表格/定义列表 → 字段相关的标题与可见文本。
- 每条片段最多 1,000 字符，记录可复现 locator；最多 100 条，不保存完整页面。
- 规范化复用 Monitor Domain Pack 的字段、单位、别名和枚举；未支持字段、空值和地区不符不能生成 matched。
- 搜索摘要没有进入 Normalizer；LLM 没有参与字段生成。

### 2.3 Open/Trusted 隔离

- API、AgentState、SSE/Monitor、结构化报告和 Markdown 均包含 `trusted/open` 模式。
- Trusted 为默认值；Open 工具 schema 只在显式 Open Mode 暴露。
- Web Extractor 只接受本轮 Agent 状态中由 Source Search 返回的候选；任意 URL 无法直接调用。
- Open Report 固定 `trusted_eligible=false`、`recommended_model_ids=[]`、`candidates=[]`。
- Constraint Checker 仍执行强制终态，但 Open 商品从未进入正式候选池；Source Candidate/Open Evidence 进入 Checker 的数量均为 0。
- Product Pack、正式 Evidence Ledger、SQLite、事实卡、Chroma、长期 Memory 和 V1 冻结文件均未修改。

## 3. 最终真实验证

最终代码使用仓库外目录运行 4 条有界任务；不调用 qwen-plus：

| 用例 | Source Search | 抽取/报告 | 字段结果 | Trusted eligible |
|---|---|---|---|---:|
| BenQ PD3226G / US（数据库外） | `success`，`search_pro` 1 次 | HTTP 200，688,481 bytes，21 条临时证据 | 6/6 matched，unknown 0，conflict 0 | false |
| Dell P2725QE / CN（数据库外） | `success`，2 次有界搜索 | HTTP 200，845,759 bytes，14 条临时证据 | resolution/USB-C video matched；供电多值 conflict | false |
| LG 27GS95QE-B / CN | `no_region_matched_source` | 抓取 HK 导航页后未发现可安全恢复的 CN hreflang | 3 个目标字段 unknown | false |
| BenQ PD2725U / CA | `no_region_matched_source` | 导航页重定向安全校验失败，未恢复 CA | 3 个目标字段 unknown | false |

PD3226G 最终内容 SHA-256 为 `9ce418c68b892c4bfbcf1a803e97bce945895157db9e594f5273af530335b514`。6 个 matched 字段的 source/region/observed_at 完整率为 100%；完整 HTML 未写入仓库。

canonical/hreflang 专项结论：LG 与 BenQ 两例均真实尝试但恢复 0/2，继续返回 degraded/unknown。没有使用已知 URL、错误地区页面或搜索摘要补答案。

## 4. 冲突、失败与生命周期测试

四类冲突均保留双方证据并返回 conflict：

1. 治理证据与当前官方网页值不同。
2. 同型号目标地区与其他地区页面不同。
3. 同一字段旧观察与新网页观察不同。
4. 两个官方正文片段值不同。

安全/失败矩阵：

| 分类 | 结果 |
|---|---|
| file/data/ftp、userinfo、异常端口、IP 字面量 | 全部拒绝 |
| DNS 私网、回环、link-local、mapped IPv6 等 | 全部拒绝（Fake Resolver，无内网真实请求） |
| 白名单后缀欺骗、跨域重定向 | 全部拒绝 |
| 非 HTML、解压后超 5 MiB、超时、重定向超限 | 按契约降级 |
| 静态正文不足/动态脚本页 | `dynamic_render_required`，关键字段 unknown |
| 临时存储过期、损坏、删除、关闭 | 分别返回 expired/corrupt/missing/disabled，不污染正式数据 |
| Source Search 摘要进入 Evidence/Checker | 0 / 0 |
| 错误地区证据进入目标商品 | 0 |
| Open 商品进入 Trusted eligible | 0 |

临时记录默认 24 小时，按 user/session/thread/request 不透明 token 隔离，原子写入。promotion export 固定 `review_required`、`auto_publish=false`。

## 5. 测试、成本与回归

- V2-4 定向：21/21。
- `smartbuy/tests`：222/222，3 条上游依赖弃用警告。
- V2-4 引入前 V2-3 为 201/201；新增正好 21 条测试，没有删除或跳过旧测试。
- CI 等价套件（含上游配置脱敏 node）：223/223；3 条警告均为既有上游依赖弃用提示。
- Ruff、Compileall、JavaScript 12/12、PowerShell AST 5/5、Markdown 相对链接 289/289 和 `git diff --check` 通过。
- 敏感扫描不安全命中 0；4 处 `ws-...` 形状均为既有 `placeholder/test/fake` 测试夹具。禁止运行产物、依赖/锁文件和冻结数据/评测变更均为 0。

真实调用账本：

- 案例选择：7 次搜索，估算 ¥0.27。
- 三次有记录的完整验收运行：各 7 次搜索、各估算 ¥0.27；首次暴露并保留轮播噪声，第二次验证收紧规则，第三次验证最终 URL 去跟踪参数代码。
- 合计：28 次智谱搜索，估算 ¥1.08；qwen-plus/Embedding/Reranker 调用 0，模型成本 0。
- 低于 V2-4 Source Search + LLM ¥2 上限。

## 6. 已知限制与 V2-5 前置条件

- 静态解析不覆盖必须执行 JavaScript 才能出现的规格；本阶段不使用 Playwright。
- 营销页可能包含相邻型号信息；当前对身份敏感的尺寸/分辨率采用更严格片段关联，其他字段仍依靠冲突态 fail closed。
- canonical/hreflang 覆盖取决于官方页面实现，本次专项恢复为 0/2。
- Temporary Evidence Store 是 Windows 本地 MVP 文件存储，不是生产多租户隔离系统。
- DNS 预解析无法完全消除解析与连接之间的 TOCTOU；生产部署需网络级 egress 代理/沙箱和 DNS pinning。
- 本阶段不自动晋升证据、不改变正式数据、不实现自然约束/主动澄清。

进入 V2-5 前必须由用户明确确认；V2-5 不得借 Open Evidence 绕过既有 Constraint Checker、地区规则或 Trusted/Open 资格上界。
