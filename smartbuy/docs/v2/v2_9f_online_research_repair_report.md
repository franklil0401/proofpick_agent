# V2-9F Online Research 专项修复报告

## 结论

V2-9F 在 `fix/v2-9f-online-research` 上完成了官方来源发现、静态网页/PDF 提取、字段规范化和逐层可观测性的通用修复。安全边界全部保持：安全终态 `15/15`，错误域名、型号、配置、地区进入 usable 均为 `0`，搜索摘要成为 Evidence 为 `0`，Open Evidence 进入 Trusted Checker 为 `0`，unknown 过度声明为 `0`。

本轮唯一有效完整 **exposed regression** 实际完成取证为 **6/15**，Monitor / Laptop / Headphone 分别为 `2/5`、`1/5`、`3/5`；有 Evidence 的任务请求字段核验为 **11/18（61.11%）**。它没有达到 `8/15`、每品类 `2/5` 和字段核验率 `80%` 的联合门槛，因此 **V2-9F 未完成发布收敛，不具备冻结 RC3 的条件**。不得据此创建新 Holdout、合并、Tag 或 Release。

## 不可覆盖历史

| 记录 | 实际完成取证 | 说明 |
|---|---:|---|
| V2-9D 第二次独立首次 | 0/15 | 独立发布评测，原始结果不修改 |
| V2-9E exposed 第一轮 | 2/15 | 已暴露任务 |
| V2-9E exposed 宽检索后 | 5/15 | 已暴露任务 |
| V2-9E exposed 提取增强后 | 5/15 | 已暴露任务 |
| V2-9F exposed | 6/15 | 本报告结果，不是新 Holdout |

独立评测题集、评分器和首次结果均从 `126486861e08a33a94d4c6c5ffeafc121db2ee5e` 只读加载；没有 merge、cherry-pick 或修改独立评测分支。

## 修复前失败漏斗

[修复前机器审计](../../eval/results/v2_9f_online_failure_funnel_pre_repair.json)在修改生产代码前冻结，SHA-256 为 `340fc9e2fe23077d48e7828d759befaa1f3e73f71705fe95f552f1eb04c523a1`。

| 层 | 通过任务 |
|---|---:|
| Source Search | 15/15 |
| 官方域名过滤 | 14/15 |
| 型号匹配 | 14/15 |
| 目标地区直接匹配 | 5/15 |
| 页面获取 | 9/15 |
| 正文提取 | 7/15 |
| 字段规范化 / Evidence Check / 实际完成 | 5/15 |

首要失败为地区不匹配 `6`、页面获取失败 `5`、requested field 缺失 `4`、动态页 `2`、正文空 `2`、规范化失败 `1` 和冲突 `2`；同一任务可属于多个失败类别。

## 根因与通用修复

| 根因 | 通用修复 | 安全约束 |
|---|---|---|
| 单个营销页被 403/缺字段后没有替代页 | Zhipu 使用至多 4 条确定性查询变体；先字段/地区页，再支持页和广域官方身份页；只在主引擎无 usable 时用搜狗引擎 | Provider 站点过滤只作召回提示；每批结果重新做域名、型号和地区校验 |
| 页面存在 canonical/hreflang 或型号绑定的规格/支持/PDF 链接，但未继续提取 | 在已确认商品身份的官方页中发现有界 related links，至多跟随 2 个；每次重做 SSRF、跳转、域名、型号和地区检查 | 不维护商品 URL；不绕过 403、登录、验证码或地区限制 |
| 现代页面把规格放在内嵌状态而非可见 DOM | 不执行脚本，仅在同时包含精确型号的内嵌状态中截取 requested-field 周边的有限窗口 | JavaScript 不执行；响应大小、片段数和超时均有硬上限 |
| 官方规格附件是 PDF | 增加内存内、页数/字节受限的文本 PDF 解析 | 不写下载文件；加密、损坏、过大或无相关文字时降级 |
| 各品类别名、单位和多值表达不一致 | Domain Pack 声明官方品牌域名、identity-sensitive fields 和字段提取规则；Loader 启动时校验规则 | 未声明字段、非法规则、缺失值保持 unknown；多个值保留 conflict |
| 续航与充电时长、多个瓦数互相污染 | 支持排除词；USB-C PD 取与供电语义最近的瓦数；IP 等级与显示尺寸表达通用化 | 不用最大值猜测，不把营销文本补造为事实 |

测试中的新商品标识使用 Acme 虚构型号；生产模块没有 `case_id`、评测型号、品牌专属分支或目标 URL 特判。品牌级官方域名是 Domain Pack 来源治理配置，不是商品答案。

## 唯一有效完整 exposed regression

机器结果：[v2_9f_exposed_online_regression_final.json](../../eval/results/v2_9f_exposed_online_regression_final.json)，SHA-256 `500093ed072eefaa43ab684a29e4b7bf50fcfd6eb7fef5be0c532404bdeab26b`，run ID `v2-9f-exposed-online-20260904T151258Z-ece02e9b`。独立[运行 Manifest](../../eval/results/v2_9f_exposed_online_regression_manifest.json)绑定生产实现 Commit `52d4d20d0858c8f8954786b756ea7a90ef4fdd8b`、Tree `1721f501b90fb727023797a0cafeb8df804ea372`、评测器 Commit 和三品类 Data/Index 合同；冷缓存运行，不是独立 Holdout。

| case_id | 品类 | Search 终态 | 实际 Evidence | 已核验字段 | 主要未闭环原因 |
|---|---|---|---:|---|---|
| `web2-mon-001` | Monitor | no_region_matched_source | 0 | — | 只发现 CN 页面；US 页面 403 |
| `web2-mon-002` | Monitor | success | 15 | resolution、USB-C PD | 尺寸多值冲突 |
| `web2-mon-003` | Monitor | success | 0 | — | US 候选 403；其他地区正文不可用于 US |
| `web2-mon-004` | Monitor | no_region_matched_source | 9 | resolution | 尺寸冲突、USB-C PD 缺失 |
| `web2-mon-005` | Monitor | no_region_matched_source | 0 | — | 已发现页面均 403 |
| `web2-lap-001` | Laptop | success | 10 | memory、storage | USB4 未闭环，部分候选超时 |
| `web2-lap-002` | Laptop | success | 0 | — | 唯一 US 候选 403 |
| `web2-lap-003` | Laptop | no_region_matched_source | 0 | — | 目标地区不足且页面超时 |
| `web2-lap-004` | Laptop | no_region_matched_source | 0 | — | 页面地区 unknown；字段规范化为空 |
| `web2-lap-005` | Laptop | no_region_matched_source | 0 | — | 已发现页面均 403 |
| `web2-hph-001` | Headphone | no_region_matched_source | 0 | — | 页面 403，地区未闭环 |
| `web2-hph-002` | Headphone | no_region_matched_source | 7 | battery、ANC | Bluetooth version 缺失；页面通过 hreflang 确认 US |
| `web2-hph-003` | Headphone | success | 7 | dongle、weight | battery 缺失 |
| `web2-hph-004` | Headphone | no_region_matched_source | 0 | — | 页面地区 unknown；字段规范化为空 |
| `web2-hph-005` | Headphone | success | 15 | ANC、water resistance | ANC battery 多值冲突 |

“实际完成取证”沿用历次 Online 报告的口径：至少形成一条字段级 Open Evidence；它不表示全部 requested fields 已闭环。

## 修复后完整漏斗

| 层 | 通过任务 | 相对修复前 |
|---|---:|---:|
| Source Search | 15/15 | 0 |
| 官方域名过滤 | 15/15 | +1 |
| 型号匹配 | 15/15 | +1 |
| 地区匹配（搜索或页面复核） | 8/15 | +3 |
| 页面获取 | 10/15 | +1 |
| 正文提取 | 10/15 | +3 |
| 字段规范化 | 6/15 | +1 |
| Evidence Check | 6/15 | +1 |
| 实际完成取证 | 6/15 | +1 |

最终失败分类为：地区不匹配 `7`、页面获取失败 `5`、正文空 `5`、规范化失败 `4`、Evidence conflict `3`；15 条任务均至少缺少一个 requested field。搜索与抽取变得更可观察，但安全过滤后仍无法从概率搜索和静态抓取稳定恢复 Laptop 官方规格。

## Provider、提取方式、延迟与费用

| 项目 | 结果 |
|---|---:|
| Zhipu 搜索（完整 exposed run） | 53 次；53 成功；重试 0；估算 ¥1.77 |
| Bailian / BoCha 正式调用 | 0 / 0 |
| 平均 / P95 任务延迟 | 18.036 s / 33.933 s |
| Provider Token | 接口不报告，记为 N/A，不记为 0 消耗 |

成功页面中的提取方法观测次数为 JSON-LD `25`、embedded JSON `7`、内嵌状态 `19`、规格表/定义 `12`、可见正文 `30`；这些是页面/方法观测，不是独立成功任务数，不能相加为完成率。PDF 能力通过真实内存 PDF 单元夹具验证，本次 15 条没有形成 PDF Evidence。

开发期另有 11 次小型 Zhipu Smoke，估算 ¥0.37。首次正式运行在第 1 条结果序列化时发生评测器事故，准确调用数未落盘，只能审计为 1～4 次、费用上界 ¥0.14；详见[事故记录](../../eval/results/v2_9f_online_harness_failure.json)。因此本阶段总调用为 **65～68 次**，总估算费用为 **¥2.17～¥2.28**，低于 ¥5 上限。两次 preflight 失败均发生在 Provider 构造前，调用为 0。

## 安全与兼容

- Source Candidate 只用于导航；搜索摘要进入 Evidence `0`。
- Open Evidence 的 `usable_for_trusted_checker=false`；进入 Trusted Checker `0`。
- 错误域名、型号、配置、地区进入 usable 均为 `0`。
- unknown 与 conflict 没有被写成 verified；unknown overclaim `0`。
- 401/403 不重试；本次 53 个 Provider 调用均成功，无 Provider 重试。
- V1 默认路径、Checker、Product Pack、治理数据、索引、独立题集和历史指标均未改动。
- 没有启用 Playwright；动态页和拒绝静态访问的页面继续明确降级。

## 质量门

- 无真实凭据的 CI 等价范围：`513/513`。
- V1 Tag 所含 18 个原始测试文件：`101/101`；没有删除或漏收集 V1 测试。
- Trusted 意图、Scope、澄清核心离线回归：`96/96`；没有重新运行付费 Trusted 全量。
- V2-9F Source Search / Open Research / Runner 定向回归：`63/63`。
- Ruff、Compileall：通过；全仓 JavaScript `13/13`；PowerShell AST `6/6`。
- Markdown 相对链接：`446/446`（96 份文档）；`git diff --check`：通过。
- 全仓及本阶段高置信凭据命中：`0`；本阶段新增禁止运行产物：`0`。
- 8000、8088、9000、9001 监听：`0`；未启动 FastAPI、MinIO 或其他服务。

## 未解决问题与后续前置条件

1. 概率搜索仍经常只返回错误地区页；不能放宽地区门或用页面标题替代地区证据。
2. Dell、Sony、Microsoft 等页面对静态客户端返回 403；项目不绕过访问控制。
3. HP 页面在受控超时内未稳定返回；Lenovo/SteelSeries 页面可读但地区和结构化字段不足。
4. USB4、Bluetooth version、续航与部分显示器字段仍缺少精确规格闭包；不得推测。
5. 浏览器渲染默认未实现。若继续，应先单独设计并验证 Windows 安装、SSRF、脚本/下载、跳转、资源大小与时间预算，不得以浏览器绕过站点限制。
6. 若继续引入 Bailian/BoCha 回退，需要独立 ADR、逐 Provider 费用/延迟账本和相同本地安全门；本轮没有实现 Composite Provider。

只有在新的修复阶段用离线夹具证明上述通用路径、并以新的 exposed 结果达到 `>=8/15`、每品类 `>=2/5`、字段核验 `>=80%` 且所有安全门保持 0 后，才可讨论冻结 RC3。下一套未见发布集仍必须由独立评测方创建；开发方不得自行制作或运行。

相关运行边界见 [V2-9F 运行说明](v2_9f_online_research_runtime.md)和 [ADR-0022](../adr/0022-bounded-official-source-discovery-and-extraction.md)。
