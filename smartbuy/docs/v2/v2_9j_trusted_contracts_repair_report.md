# V2-9J：默认产品入口的可信约束与身份修复

本轮是开发修复，不是发布、RC 重新冻结或独立评测。分支为 `fix/v2-9j-trusted-contracts`，起点为 `release/proofpick-v2-rc3` 的 `033669d6c2d168dddbd712c2a54a105da53ffc1b`。不改变旧 RC3 的生产 Commit `ba6606ae249bafc89c18b320935c767a3f756c34`、Tree `84766c5d8840b50a27c612e24379b6dd63736741` 或 Manifest。本文记录新分支的修复，不将新代码冒充冻结 RC3。

## 1. 只读材料与归因边界

只读取独立分支 `eval/v2-9i-independent-rc3` / `a289ed8c944ad30f20e9bb3a9f8c7f389b23a3e7` 的以下三个文件：

- `smartbuy/docs/v2/v2_9i_rc3_r1_independent_evaluation_final_report.md`
- `smartbuy/eval/v2_9i_independent/results/product_failure_audit.json`
- `smartbuy/eval/v2_9i_independent/results/harness_incident_audit.json`

没有读取剩余未运行任务、金标或独立评分器，没有合并/cherry-pick 评测分支。只执行了 11 题的历史结果为 **7/11**，不能解释为三品类总体正确率。第 2 题原始 Evidence 报错是评测器 JSON TEXT/类型兼容与引用判定误报，已由评测方纠正；本轮没有为此修改 Evidence 规则。

第 11 题是真实产品错误：用户要求刷新率 ≥144Hz、机身宽度 ≤610毫米，LLM 提案包含两项，但 V1 确定性解析只识别英文 `mm/cm`，遗漏中文宽度。SQL 从不完整 ConstraintSet 重建条件；Evidence/Checker 同样只看刷新率，最终错误推荐了宽 611.9mm 的型号。Checker 执行正确并不能证明输入约束完整。

## 2. 实际产品入口审计

| 入口 | 修复前真正使用的链路 | 本轮变化 |
|---|---|---|
| WebUI Portfolio | `portfolio.js` → `/api/smartbuy/portfolio/run`，不传 `use_natural_constraints` | 请求格式、UI 和启动开关不变 |
| Monitor 默认 Portfolio | `get_smartbuy_orchestrator` → ReAct → `PurchaseDecisionAgent` → V1 `ConstraintNormalizer` | 旧解析器复用 Pack 单位合同，加入完整性守卫和统一身份范围 |
| Laptop/Headphone Portfolio | `PortfolioRuntimeManager` → `DomainDecisionAgent` → `NaturalConstraintEngine` | 同一量值合同；有效约束进入工具前再次审计完整性 |
| CLI/旧 Stage4/5/6 Runner | 直接构建 `PurchaseDecisionAgent` | 自然获得相同修复，不依赖专用 Runner |
| 领域 Runner | 直接构建 `DomainDecisionAgent`，通常显式配置 NaturalConstraintEngine | 复用相同守卫，不提供测试专用宽松开关 |

文档启动脚本 `start.ps1` 开启 `PROOFPICK_DOMAIN_AGENT_ENABLED=true` 以装配领域运行时；Monitor 仍走 V1 兼容入口。`PROOFPICK_NATURAL_CONSTRAINTS_ENABLED` 没有被偷偷打开，ReAct 仍是默认编排器，LangGraph 仍只是显式兼容外壳。本轮不变更依赖、Prompt、请求 Schema 或服务部署方式。

## 3. 通用修复与安全边界

### 3.1 共享量值合同与完整性守卫

新增 [quantities.py](../../contracts/quantities.py)，字段标签、别名、合法单位、转换因子来自当前 Domain Pack。`毫米/mm`、`厘米/cm` 与小数、混合单位范围均回到规范单位；原始 quote/span 使用用户原串切片。宽度、刷新率和重量的 V1/V2 重复规则改为调用共享解析。旧 `_augment_requirements` 不再维护另一套预算/尺寸/刷新率/宽度值解析，而仅适配同一 Normalizer 的输出。

新增 [requirements.py](../../decision_core/requirements.py)，独立列出原文要求并与最终有效硬约束逐字段、操作符和值对齐。数值未解析、单位不支持、阈值缺失或某个解析结果被适配层丢弃，均保留为 unresolved，返回 `clarification_state=pending`，无购买推荐。Monitor 在调用模型前、`set_requirements` 后及 Checker 前检查；领域入口在工具与候选筛选前检查。有效覆盖/取消只接受已校验 Proposal 和 diff 的证据，不把撤销的旧值继续当成要求。

该守卫不是第二个 Checker，也不会把 LLM 结果直接激活。原有 Quote-to-Span、字段、类型、单位、值域、Provenance Gate 和 Checker 保持权限；明确的购买指令不会因为后续“核验依据”子任务或模型声明 `fact` 而被清除。纯事实/比较 requested fields 不自动成为购买硬条件。

返回 `usage.requirement_coverage`，记录有效/未解决要求和公开原因。V1 的响应身份结构保持兼容，不将缺少完整 V2 身份字段的对象强塞进 `product_scope`。严格比较符若不在当前支持的操作符合同中，安全暂停，不伪装成包含边界的 `<=` 或 `>=`。

### 3.2 精确身份优先，但不掩盖冲突

新增 [identity/catalog.py](../../identity/catalog.py)，把可信 SQLite 的 `model_id/model_name/brand/region` 映射到统一身份 Resolver。同一引用中的精确目录 ID、完整型号或唯一配置可以收窄共享系列描述；仅系列名且无法唯一确定仍需澄清。地区/配置互相矛盾时暂停，购买动词也不能取消冲突。独立点名的比较对象分别保留，不用一侧精确 ID 吞掉另一侧。

Monitor 不再使用“某个共享 token 命中多个名称”作为独立歧义判据；即使调用方提供了已解析 ConstraintResolution，身份歧义检查也不能跳过。SQL 身份过滤、KB/Evidence 参数、工具返回吸收与最终 Checker 池都受目录所有的 Scope 限制。过宽工具结果会被剔除并标记 degraded；不会进入候选、证据或报告。V1 通过有界 `usage.candidate_scope` 暴露审计范围，不改变旧报告 Schema。

### 3.3 实际执行过滤可审计

Text2SQL Trace 区分 `suggested_sql` 与 `executed_sql`，旧 `sql` 展示实际 SQL；同时给出 `effective_filters`。展示不再把模型建议 SQL 当作已执行条件。SQL 对点名配置做身份检索，Checker 独立复核全部用户硬条件；全库筛选使用完整结构化条件。特意不通过改变 Checker 或受信数据来补救解析缺陷。

`execution_mode=deterministic_template` 表示过滤策略，不表示执行成功；失败或未执行时须结合 `status` 和空的 `executed_sql` 判断，不将建议 SQL 当作运行证据。

## 4. 测试先失败、修复后回归

[开发首败审计](../../eval/results/v2_9j_development_first.json)、[默认 API 首测](../../eval/results/v2_9j_portfolio_regression.json)、[身份首测](../../eval/results/v2_9j_identity_development_first.json)、[身份定向回归](../../eval/results/v2_9j_identity_development_regression.json)、[购买语境身份冲突首测](../../eval/results/v2_9j_identity_filter_conflict_first.json) 分别保留，未覆盖独立首测。

- 单位初始 9 项：1 通过、8 失败；身份初始 12 项：6 通过、6 失败。
- 默认 Portfolio API 初始 14 项：4 通过、10 失败，包括中文单位、SQL 展示、精确身份和未解决要求。
- 新增硬要求遗漏 5 项、领域覆盖 5 项首次均失败；随后增加 Scope 注入测试发现 KB/Evidence 额外配置进入报告，及购买语境被事实子任务覆盖的问题。
- 中间全量 579 项出现 20 失败：将部分 V2 身份 envelope 加入 V1 报告触发原 Schema 拒绝。已撤销这种跨版本响应混用，未弱化校验；中间结果保留。

默认 Portfolio API 的开发回归使用虚构 Acme Orbit 配置（`610.0mm/144Hz`、`611.9mm/165Hz`、`600mm/120Hz`），真实 SQLite/Evidence/Checker，仅模型和检索为 Fake。身份专项另用 Axiom/Prism 虚构目录；量值测试包括虚构 `clearance_mm` 字段与 `NOVA-OMEGA-42` 标识。没有按品牌、商品、case_id 或公开问句写生产特判。

公开的宽度事故输入另标为 **exposed development regression**：通过实际 Portfolio API，真实治理目录 SQLite、Evidence 和 Checker，模型为 Fake，KB 为数据库证据回放。修复后返回 `asus-pg27aqdm-cn`（605mm/240Hz）、`benq-ex2710u-cn`（609mm/144Hz）、`lg-27gs95qe-b-cn`（604.4mm/240Hz）；611.9mm 型号不在返回池中。该验证不等于真实云端 LLM/Embedding/Reranker E2E 重跑。

最终结果另存 [修复后开发回归](../../eval/results/v2_9j_development_regression.json)，不覆盖首败：

| 检查 | 真实结果 |
|---|---|
| 新增定向测试 | 79/79：单位21、身份20、输入覆盖5、领域覆盖10、默认Portfolio API23 |
| 当前 CI 等价全量 | 597/597，150.62秒；原基线518项＋新增79项 |
| V1 Tag 所含原始测试文件 | 18个文件，101/101，15.11秒；原文件与断言未改 |
| Ruff / Compileall | 通过 |
| 全仓库已跟踪 JavaScript / PowerShell AST | 13/13、6/6；未修改前端或脚本 |
| Markdown相对链接 / diff check | 通过，新增报告与结果链接有效 |
| 敏感扫描 / 新增禁止产物 | 真实凭据0、新增禁止产物0 |
| API请求与费用 | 0次、¥0；无真实模型/搜索/网页收费调用 |
| 服务端口 | 8000、8088、9000、9001无监听；未留下测试服务 |

三条警告为既有 PyPDF2/Pydantic/SQLAlchemy 弃用提示，不是功能失败。CI等价全量包含三品类工具链、原Checker/Memory、QuoteSpan、编排、Scope、Online安全与原始数据哈希回归。全部修复没有改变旧测试断言，故新增79项与原518项可以区分计数。

依赖声明和 `uv.lock` 均未修改。验证默认 frozen sync 时清理了本地原有25项可选PoC包，随后按其原锁定版本恢复，以保留用户已有本地环境；没有下载浏览器、升级依赖或接入Online能力。一次恢复命令的版本拼写错误在解析阶段失败，未安装任何包，核对锁文件后已纠正。

可复核命令（全部离线，不运行独立评测器）：

```powershell
uv run --project vendor/youtu-rag --frozen python -m pytest smartbuy/tests vendor/youtu-rag/tests/rag/api/test_config_security.py -q
uv run --project vendor/youtu-rag --frozen ruff check smartbuy
uv run --project vendor/youtu-rag --frozen python -m compileall -q smartbuy
uv run --project vendor/youtu-rag --frozen python -m smartbuy.scripts.check_markdown_links
```

测试进程的模型/Search凭据变量置空，只影响子进程，未读取或改写用户系统变量。JavaScript与PowerShell检查沿用 `.github/workflows/ci.yml`；V1文件集合直接来自 `git ls-tree v1.0.0-portfolio`，不是人为挑选通过的文件。

## 5. 运行与剩余限制

使用原 [RC3 Windows 运行说明](v2_9h_windows_reproduction.md) 的启动方式，无新环境变量或依赖。测试通过进程内 FastAPI TestClient 执行真实默认 Portfolio 路由，SQLite/运行数据位于临时目录；本轮不重新安装干净 Windows、不重建收费索引、不运行独立评测器。

本修复声明的覆盖范围是 Pack 驱动量值、明确命令字段、身份与当前解析合同的完整传递，不宣称任意自然语言都可以无歧义理解。不支持的单位或操作符可以要求用户改写；不会猜测再推荐。默认 Monitor 与 V2 Domain Agent 仍是两条兼容执行路径，本轮统一关键合同而非迁移整个框架。

仅本地测试证明修复范围内的行为。旧 RC3 被阻断的结论与历史 Online Beta 指标不变；是否冻结下一版候选须用户确认，并另行固定生产 Tree/Manifest。任何新的独立发布集均由独立方负责，本轮没有创建、窥读或运行它。

导航：[项目结构](../development/PROJECT_STRUCTURE.md) · [旧 RC3 R1 Handoff](v2_9h_r1_rc3_handoff.md) · [开发指南](../development/DEVELOPMENT_GUIDE.md)。
