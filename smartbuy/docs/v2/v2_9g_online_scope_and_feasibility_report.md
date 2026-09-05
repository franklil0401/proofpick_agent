# V2-9G Online Research 发布范围与可行性报告

## 结论

V2-9G 没有继续无边界调参。严格单调的任务级漏斗证明旧指标混合了不同候选分支；默认关闭的 Playwright 与 Bocha 有限 PoC 只把保守完成投影从 `6/15` 提高到 `7/15`，Laptop 仍为 `1/5`，字段核验投影为 `15/21（71.43%）`。联合门槛仍不可达，因此本轮没有接入正式浏览器或多 Provider、没有运行完整 15 条 exposed regression。

根据 [ADR-0023](../adr/0023-trusted-core-and-experimental-online-research.md)，后续 RC3 发布范围应收敛为 **Trusted Multi-domain Decision Core**；Online Research 明确标记 **Experimental/Beta**。这不是原 Online 门槛通过，也不是 RC3 冻结或发布结论。

## 不可覆盖历史

| 记录 | 实际完成网页字段取证 | 分类 |
|---|---:|---|
| V2-9D 第二次独立首次 | 0/15 | 独立首次，永久保留 |
| V2-9E exposed regression | 2/15 → 5/15 → 5/15 | 已暴露回归 |
| V2-9F exposed regression | 6/15 | 已暴露回归 |
| V2-9G 有限 PoC | 投影 7/15 | 失败类型可行性验证；不是完整运行 |

没有创建或运行新 Holdout，没有覆盖任何历史结果。

## 指标口径修正

机器审计见 [v2_9g_monotonic_funnel_audit.json](../../eval/results/v2_9g_monotonic_funnel_audit.json)，输入绑定 V2-9F 结果与已暴露 Online case 文件的 SHA-256。

旧 Runner 对每层独立执行 `any(candidate branch)`：US 候选 403、CN 候选 2xx 的同一任务会同时计为“地区匹配”和“页面获取”，即使没有任何一条候选链贯通两层。V2-9G 改为：任务只有在同一候选 lineage 满足所有前序条件时才能进入下一层；目标地区可由搜索元数据或抓取后的官方页确定性确认。

| 任务级阶段 | 当前阶段分母 | 通过 | 累计通过/15 | 首个失败数 |
|---|---:|---:|---:|---:|
| Source Search | 15 | 15 | 15/15 | 0 |
| 官方域名过滤 | 15 | 15 | 15/15 | 0 |
| 型号匹配 | 15 | 15 | 15/15 | 0 |
| 目标地区验证 | 15 | 8 | 8/15 | 7 |
| 目标地区分支页面获取 | 8 | 6 | 6/15 | 2 |
| 同分支正文提取 | 6 | 6 | 6/15 | 0 |
| 字段规范化 | 6 | 6 | 6/15 | 0 |
| Evidence Check | 6 | 6 | 6/15 | 0 |
| 实际完成取证 | 6 | 6 | 6/15 | 0 |

这里“实际完成”仍沿用历史口径：至少形成一条请求级 Open Evidence，不代表所有请求字段均闭环。

### 候选级统计（不可与任务漏斗混用）

- 15 个任务中 13 个存在多个候选分支；候选分支/提取操作均为 `52`。
- 所有候选分支 2xx 抓取 `33/52`，正文片段 `32/52`。
- 最终可验证目标地区的候选分支 `18/52`；这些分支的 2xx 抓取与正文片段均为 `15/52`。
- 非目标地区分支 2xx 抓取 `18/52`。
- 旧页面获取包含 4 个没有贯通目标地区 lineage 的任务：`web2-mon-001`、`web2-mon-003`、`web2-lap-004`、`web2-hph-004`。其中 `web2-mon-003` 同时存在目标地区 403 分支和其他地区 2xx 分支。

## 有限 PoC

原始脱敏结果见 [v2_9g_online_feasibility_poc.json](../../eval/results/v2_9g_online_feasibility_poc.json)，SHA-256 `016f90ac70a11d94bcd125bea6c0f40e23a8c9e6343877e5971a449070753631`；语义复核见 [PoC audit](../../eval/results/v2_9g_online_feasibility_poc_audit.json)。只使用已暴露失败类型和 V2-9F 已接受来源，没有硬编码商品 URL 或 case 答案。

### Playwright

- 版本 `1.55.0`，来自现有 `vendor/youtu-rag/uv.lock` 的 `search` dependency group；锁文件未修改。Chromium 安装在 Windows 用户缓存，不进入仓库。
- `PROOFPICK_V2_BROWSER_POC_ENABLED` 默认 `false`；PoC 位于 `smartbuy.eval`，未注册到 API、Agent、SSE 或 Demo。
- 只接收 `region_matched` Source Candidate；导航前和最终 URL 均执行 SSRF/HTTP(S)/域名检查。白名单外资源、图片、媒体、字体和下载被阻断；跳转、时间、HTML 大小和片段数有上限。
- 受控样本 `5`：安全形成字段 `3`，恢复此前零 Evidence 的任务 `1`，为已有 Evidence 增加请求字段的任务 `1`，地区拒绝 `1`，HTTP 403 `1`。
- 新恢复发生在 Monitor；Laptop 新增字段和任务均为 `0`。因此浏览器可以解决部分静态客户端 403/渲染差异，但不能跨品类稳定补齐目标地区与字段闭包。

首次 PoC harness 在解析前没有拒绝 HTTP 403，把一个无字段结果的状态写成 `success`。原始文件保留；该状态不影响恢复数、字段数和投影。隔离 helper 已增加 `HTTP >= 400` 前置拒绝，未为此重复付费搜索，细节记录在 PoC audit。

### 多 Provider 有界回退

- Zhipu 仍为主 Provider。为重新发现两个既有“目标地区已知但静态抓取失败”的候选执行 `6` 次调用，估算 `¥0.18`，没有重试。
- 只在主 Provider 没有目标地区 lineage 的 Monitor/Laptop/Headphone 各选一条，Bocha 共调用 `3` 次；均为 HTTP/Provider 200，但本地重新校验后新增目标地区候选 `0/3`、新增 Evidence `0/3`。
- `site:` 只是召回提示；域名、型号和地区仍由本地 Validator 决定。搜索摘要成为 Evidence `0`。
- Bocha 响应不返回费用字段；公开个人定价页当前列为免费，但项目仍只记录三次调用，不把不可观测账单伪装成精确费用。已知可估算费用为 `¥0.18`，低于本轮 `¥2` 上限。

## 工程可解性判断

| 失败类型 | PoC 观察 | 判断 |
|---|---|---|
| 静态客户端 403、浏览器可访问 | Monitor 恢复 1 条 | 部分可解，但不是所有站点 |
| 站点继续返回 403 | Laptop 样本仍无字段 | 浏览器不能作为绕过访问控制的手段 |
| 动态正文缺字段 | 一个 Monitor 补 1 字段；Laptop 未补 USB4 | 部分可解，需要站点级实证，尚不稳定 |
| 无目标地区官方候选 | Bocha 0/3 新覆盖 | 当前 Provider 组合不能证明可解 |
| 地区 unknown/mismatch | 一个 Headphone 页面继续被拒绝 | 必须安全降级，不能用内容相似代替地区证据 |
| 字段缺失/冲突 | 投影仍只有 71.43% | 提取器无法从不存在或多值冲突的正文推测答案 |
| PDF/附件 | V2-9F 已有受限解析能力，本 PoC 未新增恢复 | 保持实验能力，不扩大下载面 |

## 门槛与发布建议

| 门槛 | PoC 保守投影 | 结论 |
|---|---:|---|
| 实际完成 ≥ 8/15 | 7/15 | 未达到 |
| 每品类 ≥ 2/5 | 3/5、1/5、3/5 | Laptop 未达到 |
| 有 Evidence 任务请求字段 ≥ 80% | 15/21（71.43%） | 未达到 |
| 安全违规均为 0 | 0 | 达到 |

因此建议停止 Online 功能扩张，按 ADR-0023 将它降为 Experimental/Beta。README 只描述“受控搜索、临时 Open Evidence、失败降级与安全隔离”，不宣称全市场实时研究或稳定网页取证；安全返回 unknown 不统计为研究完成。

## 修改范围与限制

- 新增通用、无商品答案的漏斗审计器、默认关闭的隔离 PoC helper/runner、虚构商品 HTML Fixture 和对应测试。
- 修复仅位于 `smartbuy.eval` 的 PoC HTTP 状态分类；生产 Agent、Source Search、Extractor、Normalizer、Evidence、Checker、数据、索引和历史评测均未修改。
- 没有引入新依赖或修改 `uv.lock`；没有正式接入 Playwright、Bailian/Bocha Provider 或 Composite Provider。
- 未运行完整 15 条或任何 Trusted 付费评测，没有创建 Holdout、PR、Tag、Release。

完整质量门结果随本分支最终提交记录；V2-9F 原有安全边界继续生效。
