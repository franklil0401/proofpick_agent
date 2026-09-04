# RC2 仍不具备发布条件：第二次独立评测发现新鲜输入泛化与开放取证不足

## 结论

`proofpick-v2-9c-rc2` 的第二次独立发布评测结论为 **Needs revision / 不授权发布**。不创建 PR、Tag 或 Release，不合并 `feature/proofpick-v2`，也不修改 `main` 与 `v1.0.0-portfolio`。

新鲜 Trusted 任务为 **72/90（80.00%）**。笔记本达到 28/30，但显示器 23/30、耳机 21/30，均低于预先冻结的单品类 80% 门槛。硬约束字段 F1 为 93.20%，证据覆盖为 343/357（96.08%），但困难负例只有 8/15，出现 10 个额外或错误推荐，并发生 5 次澄清绕过。

新鲜 Online 任务的安全终态为 **15/15**，错误域名、型号、地区来源进入可用集合为 0，Open Evidence 进入 Trusted Checker 为 0；但实际完成网页取证为 **0/15**。两题生成了 Open Evidence，只完成 3/6 个请求字段，因此安全拒绝能力明显强于真实研究完成能力。

这份结论不能与 V2-9B 的 64/90 做严格 A/B 比较，因为两次使用不同题集；V2-9C 的 86/90 是已暴露回归，也不能替代本次 72/90 的独立泛化结果。

## 评测对象与独立性

- 生产 Commit：`2d41773981c69b815efa21c0bf21675d095b920d`
- 生产 Tree：`9273e9f41a3ad62ac6712a02a6ee6a4486a90f24`
- RC2 Manifest Commit：`104a11e298d6f97d92b1a10a69a63c7b0d218a55`
- Manifest Payload SHA-256：`026e1ccff278c8285231223e3f2510f658e0ce2e68921c6ea94bf0a84eec1e2b`
- 独立分支：`eval/v2-9d-independent-rc2`
- 运行 ID：`v2-9d-independent-20260904T121111Z-94672285`
- 默认编排器：ReAct；冷缓存；运行时、日志与临时证据位于仓库外。

评测方在看到结果前创建并推送题集、Schema、评分规则与运行器，然后单独冻结评测 RC。Trusted 与 Online 结果均只执行一次；没有修改生产代码、Prompt、Domain/Product Pack、治理数据、Checker、既有金标或历史结果。

## 题集与评分口径

| 题集 | 数量 | 分布 | SHA-256 | 与 V2-9B 精确重复 |
|---|---:|---|---|---:|
| [Trusted](../../eval/v2_9d_independent/trusted_cases.jsonl) | 90 | Monitor/Laptop/Headphone 各 30 | `bb9edd89...d92ea0f` | 问题 0；可执行 Gold 签名 0 |
| [Online RC2](../../eval/v2_9d_independent/online_cases_rc2.jsonl) | 15 | 三品类各 5 | `2bd87699...574ffb4` | 查询/型号/地区三元组 0 |

Trusted 每个品类包含 10 条事实核验、10 条全库筛选、5 条显式比较和 5 条困难负例。独立校验读取冻结治理数据，共核对 36 个商品、357 个必需 Evidence 对、229 个“预期商品—约束”关系和 37 个完整候选集合；没有调用生产 Resolver、Agent 或 Checker 生成 Gold。

Online 预先冻结双层门槛：安全终止率、来源精度、证据血缘和 Open/Trusted 隔离必须为 100%；除此之外，实际完成取证总比例至少 50%、每个品类至少 40%，有 Evidence 的任务中请求字段核验率至少 80%。安全地返回 `unknown` 不计为完成研究。

## Trusted 首测

| 指标 | 结果 | 门槛 | 状态 |
|---|---:|---:|---|
| 总任务正确率 | 72/90（80.00%） | 仅报告 | — |
| Monitor | 23/30（76.67%） | ≥80% | 未通过 |
| Laptop | 28/30（93.33%） | ≥80% | 通过 |
| Headphone | 21/30（70.00%） | ≥80% | 未通过 |
| 硬约束字段 F1 | 93.20% | ≥90% | 通过 |
| Operator/Value 精确一致 | 95/103（92.23%） | 报告项 | — |
| 推荐与事实 Evidence 覆盖 | 343/357（96.08%） | ≥95% | 通过 |
| 困难负例 | 8/15（53.33%） | ≥90% | 未通过 |
| 额外或错误推荐 | 10 | 0 | 未通过 |
| Scope/Checker 越界 | 0/0 | 0/0 | 通过 |
| unknown 误写为满足 | 0 | 0 | 通过 |
| 澄清绕过 | 5 | 0 | 未通过 |

机器结果见 [Trusted 首次结果](../../eval/results/v2_9d_independent_trusted_first.json)，其 SHA-256 为 `5f14f510...896047d`；重新运行独立评分器得到字节等价的评分结构。

### 首错节点与代表样本

| 失效面 | 代表 Case | 观察到的行为 |
|---|---|---|
| 数值条件漏提取 | `mon-011/018/019/027` | 宽度或分辨率条件未进入活动硬约束，Checker 只能校验不完整条件，导致额外候选或错误非空结果。 |
| 模糊请求未澄清 | `mon-028/029`、`lap-029`、`hph-028/029` | 在没有明确型号或阈值时继续调用工具、返回全库/单一商品，或仅拒答但未进入 pending clarification。 |
| Unsupported 未阻断 | `mon-030` | KVM 不在支持字段中，但路径返回全部 12 个显示器，而不是明确 unsupported/abstain。 |
| 比较身份闭包不完整 | `lap-022`、`hph-023` | 两个点名配置只保留一个，另一方未进入 Scope 或 Evidence。 |
| 比较范围扩大 | `hph-024` | 点名 Nova 7P 与 Nova Pro PS，却把 Xbox 配置一并带入 Evidence。 |
| 请求字段 Evidence 不完整 | `hph-001/003/021` | 精确商品身份正确，但编解码器等点名字段没有进入 Evidence Check。 |
| 版本数值解析错误 | `hph-011` | “蓝牙版本至少 5.4”被转成 `bluetooth=true` 等派生字段，遗漏 `bluetooth_version>=5.4`，额外推荐 7 个候选。 |
| 组合否定绑定错误 | `hph-020` | “不带主动降噪但有无线接收器”被解析成 `wireless_dongle=false`，与原意相反。 |

这些失败不是 Checker 被绕过：推荐集合仍属于 Checker eligible 集合，Scope/Checker 越界均为 0。问题发生在 Checker 之前——约束或身份没有完整、正确地进入候选闭包，确定性安全门因输入契约错误而无法替用户校验真实意图。

## Online 首测

| 指标 | 结果 | 门槛 | 状态 |
|---|---:|---:|---|
| 安全终态 | 15/15（100%） | 100% | 通过 |
| 接受来源的域名/型号/地区精度 | 100% | 100% | 通过 |
| Evidence 血缘与 Open 边界 | 100% | 100% | 通过 |
| 实际完成取证 | 0/15（0%） | ≥50% | 未通过 |
| Monitor/Laptop/Headphone 完成 | 0/5、0/5、0/5 | 各 ≥2/5 | 未通过 |
| 有 Evidence 任务的字段核验 | 3/6（50%） | ≥80% | 未通过 |

15 个任务共发起 28 次结构化搜索，估算费用 1.10 元。只有两个任务进入正文提取：

- ASUS Zenbook A14 UX3407：产生 10 条 Open Evidence，完成 `memory_gb`、`storage_gb`，`usb4` 仍为 unknown。
- Logitech G522：产生 5 条 Open Evidence，只完成 `wireless_dongle`，`battery_hours` 与 `weight_g` 为 unknown。

其余任务为 8 个 `no_official_source` 和 5 个 `no_region_matched_source`。独立浏览器预检能找到多款目标商品的官方页面，例如 [Sony INZONE M9 II 规格页](https://www.sony.com/electronics/support/televisions-projectors-monitors/sdm-27u9m2/specifications)、[ASUS Zenbook A14 规格页](https://www.asus.com/us/laptops/for-home/zenbook/asus-zenbook-a14-ux3407/techspec/)、[Dell Pro Max 16 Premium](https://www.dell.com/en-us/shop/dell-laptops/dell-pro-max-16-premium-laptop/spd/dell-pro-max-ma16250-laptop/bts102_ma16250_usx)、[Bose QC Ultra 2nd Gen](https://www.bose.com/p/headphones/bose-quietcomfort-ultra-headphones-2nd-gen/QCUH2-HEADPHONEARN.html) 和 [Apple AirPods Pro 3 IE 规格页](https://www.apple.com/ie/airpods-pro/specs/)。这些 URL 没有硬编码进运行器；结果说明主要瓶颈是 Source Search 官方页召回与网页字段归一化，而不是目标页面客观不存在。

机器结果见 [Online 首次结果](../../eval/results/v2_9d_independent_online_first_rc2.json)，SHA-256 为 `df53fd44...ac43afe`。评分结构已独立复算一致。

### 评测器事故

初次 Online 运行在第 9 题发起请求前停止：评测 Schema 没有同步生产 `SourceSearchRequest.query` 最大 70 字符契约。前 8 题已完成并写入外部日志，没有聚合结果。

事故已永久保存在 [harness failure](../../eval/results/v2_9d_independent_online_harness_failure.json)。Evaluator-only RC2 只缩短尚未触达的 `web2-lap-004` 与 `web2-hph-002` 搜索字符串，没有修改型号、地区、域名、目标字段、Gold 或评分规则；前 8 题未重放，最终日志为 15 条连续唯一记录。该事故不计为产品失败，但计入评测流程成熟度限制。

## RC2 冻结与 Windows 工程验证

RC2 的 16 组、166 个仓库成员从固定生产 Commit 逐项重算，聚合哈希不一致为 0。仓库外运行索引的原始字节哈希只有 **2/7** 精确一致：两份 Product Pack `current.json` 一致，5 份索引指针/Manifest 不一致。重建文件包含 `created_at`、调用延迟与用量等运行相关字段，因此 Data/Index Version、Collection、文档数、1024 维度和 SQLite 完整性均一致，原始文件字节仍不可跨机器复现。详见 [运行 Manifest 审计](../../eval/results/v2_9d_runtime_manifest_audit.json)。这意味着 RC2 的语义运行契约可复现，但当前“7 文件原始字节聚合哈希”不适合作为可移植发布门禁。

工程门禁结果：

- CI 等价测试：479/479；V1 Tag 所含 18 个原始测试文件当前 98/98。
- Ruff、Compileall 通过；JavaScript 13/13；PowerShell AST 6/6；Markdown 438/438。
- Windows Preflight 首次由子 PowerShell 解析到旧 Python 3.10.9，保留 10/11 记录；同一评测进程确认 Python 3.12.3 后为 11/11。
- 五个固定 Demo：5/5，API 调用 0；在线首页、health、monitor、portfolio capabilities 与 MinIO health 均为 HTTP 200。
- Offline Replay：HTTP 200；停止后 8000/8088/9000/9001 监听为 0。
- 当前跟踪文件中的环境变量精确值与高可信凭据模式命中均为 0。

全程成本估算：索引重建 0.015586 元，Trusted 1.0326617 元，Online 1.10 元，合计约 **2.1482477 元**。Trusted 共 349 次模型请求，无重试、无失败请求；Online 共 28 次搜索。

## 发布判断与整改顺序

RC2 的核心价值已经明确：Checker、Scope 闭包、unknown 不夸大和 Open/Trusted 隔离在新题上仍保持稳定。但它还不能支撑“多品类电子产品决策 Agent 已可发布”的表述，原因是用户意图进入安全门之前仍会丢失或反转，且开放研究基本不能完成全字段取证。

建议开发分支按以下顺序修复：

1. 建立“显式条件完备性门”：每个量词、单位、否定对象与比较字段都必须映射到 Constraint/Requested Fields；有片段未解析时先澄清或 fail closed，不能带着残缺约束进入 Checker。
2. 修复组合否定和版本数值：覆盖“不带 A 但有 B”“至少蓝牙 5.4”等通用句式，以 Domain Pack 字段语义验证，不添加 case/model 特判。
3. 强化比较闭包：所有点名配置必须完整进入 Scope，Evidence 只能来自点名集合，并逐项覆盖 requested fields。
4. 统一澄清判定：模糊家族、缺少阈值的“窄一点/强一点/通话好一点”和 unsupported 字段必须在收费工具前终止。
5. 拆分 Online 质量漏斗：分别优化“官方页召回、地区识别、静态/动态正文提取、JSON-LD/表格/PDF 字段归一化”，并把实际完成率作为产品指标，不能只报告安全终态。
6. 将运行时冻结改为规范化语义 Manifest：从哈希输入中排除时间戳、延迟和运行路径，同时单独保留这些字段供审计。

本次 90+15 条题从现在起均为 exposed regression，只能用于修复验证。完成通用修复后，必须由未参与修复的评测方重新创建第三套全新 Holdout，才可重新判断发布；不得重跑本题集后把提升包装为新的独立结果。
