# RC4 事实与比较任务：字段完成合同修复

本轮仅在 `fix/v2-fact-completion` 进行开发修复，固定起点为 `99c7bccc523addc7e8904571dbe8e20a24615c66`。不是独立评测、发布或新的 RC 冻结。生产版本以本分支最终提交为准，不能用离线通过替代真实模型验收。

## 1. 材料与历史边界

只读取独立评测固定 Commit `014a50f433211ba1578b228429cfba9709c78dae` 中授权的报告及 `failure_audit.json`。没有读取剩余 79 条 Trusted、15 条 Online 任务、金标或评测器；没有合并或 cherry-pick 评测分支，也没有创建新的 Holdout。

独立方四条已暴露真实回归仍为 **3/4**。剩余失败是中国版 PA27JCV 的宽度/分辨率查询：KB 已命中，Agent 未执行 Evidence Check 就结束；字段 unknown、引用 value=null，但 `abstained=false`。治理数据已有 612.2mm 与 5120×2880，独立方直接调用原 Evidence Check 得到 matched。不是数据缺失或引用评分误报。本轮未重跑这四条真实模型任务，更没有重写原成绩。

材料原件：[独立报告](https://github.com/franklil0401/proofpick_agent/blob/014a50f433211ba1578b228429cfba9709c78dae/smartbuy/docs/v2/v2_9k_rc4_independent_evaluation_report.md)；开发首败另存 [failure audit](../../eval/results/fact_completion_development_first.json)。

## 2. 根因与修改位置

以下位置以函数为稳定入口，基线行号仅用于对照历史：

| 模块/位置 | 原行为 | 修复 |
|---|---|---|
| [react.py](../../agent/react.py) `_invoke_tool`，基线 finish 约517行 | 门禁只看 SQL `candidate_rows`，不看 KB 登记的完整池 | `finish_decision` 核对全部目标商品×字段完成矩阵 |
| 同文件 `KB_FACT_SUFFICIENT` 分支 | 简单事实反而禁止 Evidence Check | 删除“KB 命中就足够”的编排捷径，仍使用原只读 Evidence 工具 |
| 同文件末尾回退，基线约1278行 | 只覆盖 filter/comparison/dynamic 且 assessments 必须完全为空 | fact/comparison 逐项补齐未核验字段，已完成与已失败的核验不反复调用 |
| 同文件 `_record_evidence_result` | 部分返回覆盖先前字段；重复字段末项可能吞掉 conflict | 合并 typed observations，保留冲突及双方引用；失败响应不变成已核验 unknown |
| [reporting.py](../../agent/reporting.py) `build_report` | 有 KB 且空 assessments 不含 unknown/conflict 就算充分；跨商品使用全局字段集合 | 候选、引用、未解决字段与终态统一消费逐格完成结果 |
| [domain_agent.py](../../agent/domain_agent.py) `_checked_fact_fields` 与事实循环 | 执行 Evidence 后未消费 `field_results`，再由目录值和引用重新合成 matched | 使用实际工具四态、返回身份及 evidence/source IDs；缺失、失败、预算截断不能从目录反推为完成 |
| [router.py](../../api/router.py) `portfolio_run` callback | 事件白名单不认识新的完成审计 | 兼容增加完成矩阵和确定性核验观察；请求 Schema 不变 |

新增 [fact_completion.py](../../agent/fact_completion.py) 是共享的完成合同，不是第二个 Evidence Check、比较器或 Checker。购买过滤、领域规则、Prompt、Pack、数据、索引、Ranker、Memory 与默认编排器均未重写。

## 3. 完成合同与终态

目标来自确定性解析后的 Scope；明确比较对象即使没有 KB 命中也保留在矩阵。请求字段优先取确定性 `scope.requested_fields`，不从 LLM 的最后一段回答反推。型号等身份定位符与事实字段分开，也不把 requested fields 写入购买 ConstraintSet。

| 单格状态 | 意义 | 能否关闭该格 |
|---|---|---|
| `verified_value` | 工具已返回 matched/not_matched、非空实际值及绑定引用 | 是；只是事实核验，不授予购买资格 |
| `verified_unknown` | 已真正执行核验，得到 unknown | 是；答案仍不能声称该事实已经确定 |
| `verified_conflict` | 已真正执行核验，得到 conflict，保留冲突值和引用 | 是；不得用某个值覆盖冲突 |
| `not_checked` | 未执行、部分返回遗漏或身份/引用合同无效 | 否；不是“已确认资料缺失” |
| `tool_failed` | 核验失败或终态补核返回结构不完整 | 否 |
| `budget_exhausted` | 工具次数、运行时间或费用边界不允许再补核 | 否 |

`completion_status=complete` 仅代表全部必要格子已核验；`answer_sufficient` 仅在全部格子都有可确定的事实值时成立。真实 unknown/conflict 可以完成流程，但仍 `abstained=true`，不描述为完全满足。部分完成为 `partial`，全部未完成为 `incomplete`；`unresolved_facts` 逐商品、逐字段解释实际原因。0/0 不算完成。

fact/comparison 的 `recommended_model_ids`、淘汰购买集合保持为空，候选 `eligible=false`、无购买推荐理由。原 Checker 仍按原权限运行；事实完成模块不改变 Checker 的任何结果。检索引用不再以 null 值抢先覆盖真实字段引用；报告引用只来自核验结果，不使用摘要或模型猜测填值。

### 身份、重复返回与旧 API

绑定型号、配置、地区、数据/索引版本。生产 Monitor 从当前只读目录取得权威身份；工具元数据不能补写目录没有认证的配置。可选旧版本字段可以缺省，但一旦工具声称某个配置/版本，就必须能与权威身份核对。错误身份不会进入可用事实集合。

为兼容旧的纯 `build_report(AgentState)` 调用，`fact_identities=None` 可使用调用方已经提供的 typed assessments 中一致身份；真实运行总是先设置目录 map，**即使读取失败得到空 map，也不会启用该兼容分支**。新增测试区分了这两种情况。没有放宽旧断言或生产身份门。

同一工具返回重复字段时不采用 last-write-wins；完成矩阵和报告均保留 conflict，不会一边显示冲突、一边输出 matched。

## 4. 实际默认入口与有界补核

入口不变：`POST /api/smartbuy/portfolio/run`。

- Monitor：原默认 Portfolio → 默认 ReAct → `PurchaseDecisionAgent`，无需自然语言解析隐藏开关。
- Laptop/Headphone：原 Portfolio runtime → `DomainDecisionAgent`，复用同一完成矩阵及原 Domain Evidence 工具。
- LangGraph 仍是显式兼容封装；没有切换默认值。Open Research 路径不接入本次 Trusted 完成合同。

Monitor 在 LLM 请求 finish 及有界循环退出时检查缺失格子，使用已有只读 Evidence Check。完成过的字段不重复核验；部分响应至多有一次只针对遗漏字段的终态补查，失败不无限重试。调用计入原 `max_tool_calls`，每次受原 `tool_timeout_seconds` 限制，终态补查同时受 `max_steps × tool_timeout_seconds` 的本轮时间上限与现有费用上限约束；不增加 LLM 或其他付费调用。

保留 V1 `tools_used` 的 Agent 工具选择兼容表现（简单事实仍可仅规划 KB）。确定性终态核验不是隐藏动作：单独公开 `usage.verification_tools_used`、`usage.fact_completion.checks`，计入 `tool_call_count`，通过 `fact_verification_observation`/`fact_completion` 事件、Monitor 元信息与 Markdown 核验完成度展示。Domain 的已有 Evidence 调用仍保留在普通工具轨迹中。HTTP 包装层 `status=completed` 表示请求已返回，不表示所有事实已知；事实充分性必须看报告完成矩阵和 `abstained`。

## 5. 测试与审计

新增的虚构商品覆盖 Acme Orbit、Axiom 等目录，使用真实本地 SQLite/Evidence/Checker，只有模型与 KB 为 Fake；没有针对品牌、型号、case_id 或独立问句编写生产特判。

- [默认 Portfolio API 测试](../../tests/integration/test_fact_completion_portfolio.py)：KB-only、直接 finish、部分字段、缺少比较一方、matched/unknown/conflict、失败/超时/预算、无重复核验、身份/Scope、事件、无购买排序。
- [共享完成合同](../../tests/unit/test_fact_completion_contract.py)：逐格闭包、版本和引用绑定、工具身份自证阻断、重复观察、旧纯报告兼容与真实运行的区别。
- [Domain 回归](../../tests/unit/test_domain_fact_completion.py)：消费实际 Evidence 四态、双边冲突、未完成与 unknown 区分、预算、异常、序关系字段及无购买推荐。

首次新 API 14/14 失败，Domain 7/7 失败；中间全量曾通过 657/657，随后加强身份安全时暴露一项旧纯报告兼容失败（全量675通过/1失败，V1 100通过/1失败）。兼容修复只改生产适配，不改旧测试。所有中间记录单独保留，不把不同分母合并成一轮实验。

最终质量结果见 [开发回归记录](../../eval/results/fact_completion_development_regression.json)。本轮付费 API **0 次、¥0**，未重建运行数据库/真实索引、未启动外部服务；测试临时 SQLite 使用测试临时目录。

| 最终检查 | 真实结果 |
|---|---|
| CI等价全量（含上游配置安全测试） | 681/681，158.41秒；原597项未删改，新增84项 |
| 默认Portfolio API / 共享合同 / Domain新增测试 | 24/24、51/51、9/9 |
| V1 Tag原始18个测试文件 | 101/101，15.12秒 |
| Ruff / Compileall / diff check | 通过 |
| 全仓库已跟踪JavaScript / PowerShell AST | 13/13、6/6 |
| Markdown相对链接 | 515/515，107份文档 |
| 凭据与禁止产物 | 真实凭据0；新增禁止产物0 |
| 服务端口 | 8000、8088、9000、9001无监听 |

全文件扫描1193个路径：原有 `run_stage6_resilience.py` 的 synthetic workspace placeholder触发一项模式命中，经脱敏复核不是凭据，文件未改。原有上游 `text2sql_mem_test/bnss_ai_incoming.db` 是已跟踪测试夹具，与基线Blob一致，未新增/修改运行数据库。这里没有把既有文件静默删除，也不把原始模式命中数伪称0。三条测试警告均为原有依赖弃用提示。

复核命令（清空测试子进程模型/Search凭据，不读取系统变量真实值）：

```powershell
uv run --project vendor/youtu-rag --frozen python -m pytest smartbuy/tests vendor/youtu-rag/tests/rag/api/test_config_security.py -q
uv run --project vendor/youtu-rag --frozen ruff check smartbuy
uv run --project vendor/youtu-rag --frozen python -m compileall -q smartbuy
uv run --project vendor/youtu-rag --frozen python -m smartbuy.scripts.check_markdown_links
```

V1 原始测试文件集合直接取自 `git ls-tree -r --name-only v1.0.0-portfolio -- smartbuy/tests`。JavaScript、PowerShell 和其他质量命令沿用原 CI，不改变依赖或开关。

## 6. 剩余限制与交接

修复保证的是已解析 Scope 和 requested fields 的完成合同，不等于对所有自然语言的理解已经通过独立评测。V1 兼容目录仍使用既有版本 envelope，本轮不做 Pack/数据迁移。运行数据库不可用、字段/身份无法核实、预算不足时仍可能返回部分完成；这是明确的能力限制，不是完整成功。

没有改动历史任务、金标、评分器、原始结果、保护分支或 V1 Tag；没有创建 PR/Release/Tag/Holdout。是否冻结下一个候选仍需用户决定。后续由独立评测方在本分支固定生产提交上复跑同四条已暴露回归；通过后，再决定是否执行 79 条未运行 Trusted，不能由本轮离线结果代替该决定。

导航：[项目结构](../development/PROJECT_STRUCTURE.md) · [前一轮工程报告](v2_9j_trusted_contracts_repair_report.md) · [现有 Windows 启动说明](v2_9h_windows_reproduction.md)。
