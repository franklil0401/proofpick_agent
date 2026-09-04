# V2-9E 通用修复与暴露回归报告

## 结论

V2-9E 从 RC2 第二次独立评测的失败链路出发，修复了意图/购买约束分离、数值与否定解析、商品比较 Scope、主动澄清、官方来源召回、静态网页提取和可移植运行 Manifest。修复只发生在 `fix/v2-9e-rc2-generalization`；没有修改 `main`、`feature/proofpick-v2`、独立评测分支、V1 Tag、冻结题集、金标或首次结果。

发布状态仍为 **Needs revision**。独立首次 Trusted `72/90`、Online 实际完成网页取证 `0/15` 仍是不可覆盖的发布证据。本轮同题运行全部是 **exposed regression**，不能称为新 Holdout，也不能形成新的发布结论。

## 不可覆盖基线

| 记录 | 原始结果 | 状态 |
|---|---:|---|
| V2-9D Trusted 独立首次 | 72/90；Monitor 23/30、Laptop 28/30、Headphone 21/30 | 保留在 `origin/eval/v2-9d-independent-rc2` |
| V2-9D 约束 / Evidence | F1 93.20%；343/357 | 不修改 |
| V2-9D 困难负例 / 错误推荐 / 澄清绕过 | 8/15；10；5 | 不修改 |
| V2-9D Online | 安全终态 15/15；实际完成网页取证 0/15；有 Evidence 的任务仅 3/6 字段 | 不修改 |
| V2-9D 评测器事故 | 第 9 题前因 query 长度契约停止 | 保留原事故文件，不重放为“首次” |

独立材料通过 `git show origin/eval/v2-9d-independent-rc2:<path>` 读取，没有 merge、cherry-pick 或修改该分支。

## 18 条 Trusted 失败归因

| case_id | 分类 | 首个失真点 | 通用根因与修复 |
|---|---|---|---|
| `v2-9d-mon-011` | Constraint Resolution | `width_mm` 未激活 | 扩展基于字段语义的上限表达；不绑定型号 |
| `v2-9d-mon-018` | Constraint Resolution | 分辨率遗漏/操作符污染 | 显式 `W×H` 只读取相邻比较词，避免后续“刷新率至少”污染 |
| `v2-9d-mon-019` | Constraint Resolution | “不要 A，宽度还要在 B 内”只保留前半 | 对转折/并列子句独立解析否定对象与数值上限 |
| `v2-9d-mon-027` | Constraint Resolution | “必须在 610mm 以内”未激活 | 增加通用 `必须在/控制在/以内` 组合语法 |
| `v2-9d-mon-028` | ProductReference / Clarification | 系列名不能唯一到产品 | 共用别名映射到多个配置时保持 ambiguous，并在工具前暂停 |
| `v2-9d-mon-029` | QueryIntent / Clarification | “窄一点”无阈值仍执行 | 无阈值定性比较进入 clarification |
| `v2-9d-mon-030` | Constraint Resolution | 未支持 KVM 被静默忽略 | Domain Pack 未声明字段进入 unsupported/fail-closed |
| `v2-9d-lap-022` | Scope / Evidence Closure | OLED/FHD+ 两配置只保留一侧 | 明确比较对象求并集，再按指定字段补齐双方 Evidence |
| `v2-9d-lap-029` | QueryIntent / Clarification | “性能强一点”无阈值仍执行 | 定性强弱要求前置澄清 |
| `v2-9d-hph-001` | Evidence Closure | codecs 证据缺失 | requested fields 与约束分离，并执行比较/事实字段闭包 |
| `v2-9d-hph-003` | Evidence Closure | ANC 续航证据缺失 | 增加 Domain Pack 字段术语映射，不转成购买约束 |
| `v2-9d-hph-011` | Constraint Resolution | `Bluetooth 5.4` 数值未绑定字段 | Pack 声明 unitless numeric fields；字段必须与值处于同一子句 |
| `v2-9d-hph-020` | Constraint Resolution | “不带 ANC，但需要 dongle”否定扩散 | 以转折词切分否定作用域，后半要求保持正向 |
| `v2-9d-hph-021` | Scope / Evidence Closure | US/CA 只保留单一地区 | 地区限定与配置身份绑定，比较 Scope 取点名对象并集 |
| `v2-9d-hph-023` | Scope / Evidence Closure | 头戴/耳塞只保留一侧 | 同 family 不同形态别名保留为两个明确配置 |
| `v2-9d-hph-024` | Scope / Result Classification | 未点名 Xbox 被加入比较 | 排除词和点名限定只能单调收窄 Scope；比较对象不当作推荐 |
| `v2-9d-hph-028` | ProductReference / Clarification | 模糊 Bose family 直接执行 | 非唯一 family/configuration 前置澄清 |
| `v2-9d-hph-029` | QueryIntent / Clarification | “通话好一点”无阈值仍执行 | 主观且缺少可判定阈值时前置澄清 |

生产实现中没有 `case_id`、上述品牌、型号、目标 URL 或金标特判。新增变形测试使用未在评测集出现的 Acme 虚构标识，验证同一规则可跨品类工作。

## Trusted 暴露回归

首次完整修复回归运行一次并永久保存于 [机器结果](../../eval/results/v2_9e_exposed_trusted_regression_first.json)：

| 指标 | V2-9D 独立首次 | V2-9E exposed regression |
|---|---:|---:|
| 任务级 | 72/90 | **86/90** |
| Monitor / Laptop / Headphone | 23/30、28/30、21/30 | **26/30、30/30、30/30** |
| 清晰硬约束 F1 | 93.20% | **97.00%**（TP 97、FP 0、FN 6） |
| 推荐与事实 Evidence 覆盖 | 343/357 | **351/357（98.32%）** |
| 困难负例 | 8/15 | **14/15** |
| Scope / Checker / unknown / 澄清越界 | 0 / 0 / 0 / 5 | **0 / 0 / 0 / 0** |

该完整回归仍有四条显示器失败（`mon-011/018/019/027`）和 3 个额外候选。随后定位为通用宽度语法及分辨率相邻比较词边界，新增确定性回归为 4/4；由于费用已接近上限，没有再次运行 90 条在线 Agent，也没有把 4/4 写成新的 90 条成绩。

第二次 Trusted 尝试在完成 25/90 后主动终止：它没有聚合结果、不得用于成绩，保留原因是本阶段已达 ¥4.98，继续会突破 ¥5 上限。终止时确认父子 Python 进程均已停止。

## Online Research 漏斗

链路被明确拆为 `Source Search → 官方域名 → 型号 → 地区 → 网页抽取 → 字段归一化 → Open Evidence → Evidence Check`。本轮实现：

- 第一查询保留 Provider 站点过滤；无可用来源时使用“精确型号 + 地区 + official specifications”的宽检索，随后仍由本地 allowlist、型号和地区门过滤。
- Provider 标题只能发现候选；抓取后再次核验页面型号，标题或搜索摘要绝不能直接成为 Evidence。
- canonical/hreflang 只有在导航页身份已确认时可发现地区页，目标页仍必须重新抓取和复核。
- 增加带参数的 JSON script、JSON-LD、meta、表格、定义列表和普通文本提取；动态渲染、PDF、HTTP 拒绝与字段缺失保持明确降级。
- Open Evidence 仍是请求级临时数据，进入治理 Ledger 和 Trusted Checker 均为 0。

三次同一已暴露 Online 集均被独立保存：

| 运行 | 实际 Evidence 完成 | 分品类 | 已完成任务的字段核验 | 安全终态 |
|---|---:|---|---:|---:|
| [第一轮](../../eval/results/v2_9e_exposed_online_regression_first.json) | 2/15 | 0/5、1/5、1/5 | 4/6 | 15/15 |
| [宽检索后](../../eval/results/v2_9e_exposed_online_regression_postfix.json) | 5/15 | 2/5、2/5、1/5 | 9/15 | 15/15 |
| [提取增强后](../../eval/results/v2_9e_exposed_online_regression_final.json) | 5/15 | 2/5、1/5、2/5 | 8/15 | 15/15 |

三轮中错误域名、错误型号、错误地区被接受均为 0，Open Evidence 进入 Checker 为 0。完成率仍低于 8/15，且运行间因搜索召回波动发生品类迁移；因此不能把“安全返回 unknown”包装成研究完成。主要剩余限制是官方站点对自动请求的 HTTP 拒绝、纯动态页面、搜索索引波动、PDF 非 HTML 以及字段表达超出当前静态规则。项目不会绕过站点访问限制。

## 可移植语义 Manifest

[V2-9E Semantic Runtime Manifest](../../eval/results/v2_9e_semantic_runtime_manifest.json) 绑定生产代码 Commit `335cea2` 及 Tree `67396341c6bf24d6a6bb536d6754ae388adca344`。七组冻结合同逐项列出成员路径、文件 SHA-256 和聚合 SHA-256；Data Version、Index Version、Collection、文档数、Embedding 模型/1024 维和数据逻辑哈希进入稳定 payload。

`created_at`、机器路径、延迟和 Token/费用只在 `runtime_audit` 或运行结果中保存，不参与 Payload SHA。两次不同时间生成得到相同 Payload SHA-256：

`95cd43f5ab18a60c5be357e7771cc5de1f18ec7a6032e4dc99b3d5b4c5876a5f`

| 冻结组 | 成员数 | 聚合 SHA-256 |
|---|---:|---|
| dependency_lock | 2 | `d0802f956a36e0ae65d9306fea81b4c80614ace2237ab32f24616fdc7e3fdf9c` |
| domain_pack_config | 10 | `b91094148c7002a771effe286d6fb4e9c18fc70250c4e9a79441a0ccbe73b335` |
| governed_data | 70 | `58804852ff1031fd576a0ae5ed0553b6b390106837171c57c21fb26f3f7799f9` |
| production_python | 107 | `02a2481aab26a58721a6b4f69e3bb04ab2a247a4972e9809398bb6ad2315654c` |
| scoring_interface | 7 | `30afe061508a642bc1b7da4ffaee568503f25c88691671068bc4a408266901ee` |
| test_baseline | 51 | `1267d0d667fa8a33e8a95d4633c55eb46057175a2d901ad0d13d600e53532930` |
| windows_scripts | 6 | `0368c621181fcc6f5996e5541541922cfc70d3de4934ab3d4746dc2d5c6d1382` |

RC2 原始 Manifest 和 V2-9D 的 `2/7` 原始字节审计没有被覆盖。重建命令：

```powershell
uv run --project vendor/youtu-rag python -m smartbuy.reproducibility.v2_9e_manifest `
  --production-commit 335cea2 `
  --output smartbuy/eval/results/v2_9e_semantic_runtime_manifest.json
```

## 调用与费用

| 用途 | 调用 | Token | 估算费用 |
|---|---:|---:|---:|
| Trusted 完整 exposed regression | 317 次模型请求 | 输入 1,212,369；输出 21,456 | ¥0.9287628 |
| Online 三轮 | 84 次智谱搜索 | 不适用 | ¥3.30 |
| 主动终止的 Trusted 尝试 | 25/90；203 次模型请求 | 输入 903,269；输出 20,229 | ¥0.7549324 |
| **合计** | — | — | **¥4.9836952** |

401/403 没有重试；未发生需要隐藏的凭据输出。阶段结束后没有运行中的评测、FastAPI 或 MinIO 进程。

## 最终质量门

- 无真实凭据的 CI 等价测试：503/503。
- V1 Tag 所含 18 个原始测试文件在当前代码上：101/101；文件范围完整，没有删除 V1 测试。
- V2-9E 通用语义/取证定向回归：87/87；Semantic Manifest：3/3。
- Ruff、Compileall：通过；全仓 JavaScript 13/13；PowerShell AST 6/6。
- Markdown 相对链接：438/438；`git diff --check`：通过。
- V2-9E 变更高置信凭据命中：0；新增或修改的禁止运行产物：0。
- 仓库上游快照原有两个 `.env.example` 模板和一个测试 fixture 数据库保持不变，不属于本轮新增运行产物。
- 8000、8088、9000、9001 监听均为 0；没有运行中的 V2-9E 评测、FastAPI 或 MinIO 服务。

## 发布判断与下一次独立验证前置条件

V2-9E 已证明 Trusted 通用修复有效，并保持所有确定性安全边界；但 Online 实际完成仍为 5/15，未达到内部 8/15 目标。本分支不得合并、Tag 或 Release。

下一次独立 Holdout 只能在以下条件满足后由未参与修复的评测方创建并单次运行：

1. 当前 CI、V1 回归、三品类工具链和安全矩阵全部通过。
2. Semantic Manifest 能从固定生产 Commit 重建并保持相同 payload hash。
3. 独立评测方不复用或改写已暴露的 90+15 条输入。
4. Online 门槛继续同时考核实际 Evidence 完成、字段覆盖和安全隔离；不能只考核安全终态。
5. 若要提高动态页/PDF覆盖，先形成独立设计并确认合规访问边界，不在本轮继续扩张。

相关决策见 [ADR-0021](../adr/0021-generalized-intent-online-evidence-and-semantic-manifest.md)。
