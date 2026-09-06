# 默认 Portfolio API：意图、澄清与约束覆盖修复

2026-09-06。**开发修复完成，等待独立方复测已暴露的15题；不是发布通过，也不是新的独立评测。**

## 1. 固定版本与证据边界

- 开发分支：`fix/v2-trusted-intent-clarification`。
- 被测旧生产：`02e97a2c793ba75dfad5ece15e5df665652808bf`。
- 本轮固定生产：`bad83ea7512e6b53ae554bbd4a1f80f0c3f4f715`；Tree：`5f3bdc6f50ec4ad71636ac745d31881f4323f7ed`。之后的交付提交只追加报告、质量记录与固定版本离线回归。
- 独立结果：`faa1b108771959949a2f1a71937c03860685daeb`，分支 `eval/v2-trusted79-continuation`；没有合并或 cherry-pick。
- 只阅读该分支的[报告](https://github.com/franklil0401/proofpick_agent/blob/faa1b108771959949a2f1a71937c03860685daeb/smartbuy/docs/v2/trusted79_independent_evaluation_report.md)、已执行15题的 `results/first.jsonl`、`first_scores.json`、分类诊断及 tuple/list 审计事故说明；用户提供的本地报告为同一内容。未读取 selection、剩余64题、金标目录或独立评分器。
- 历史独立成绩仍是 **4/15，11题失败，64题未运行**；TP/FP/FN=17/6/1，F1=82.93%。只覆盖 Monitor，不能当成79题或三品类总成绩。此前真实四题3/4及之后记录均未改写。
- 首次响应协议哈希仍为 `87cd927c50d09d5c65de5f452340dd0991c81d7fa972315cd116ca9e46d276d8`，首次评分为 `c0fb79cf106fea2820aa7c2d459bdc1633bb685545991cad015aa941b37ae0a2`（原协议统一换行）；原始文件留在独立分支固定提交，不复制覆盖。

## 2. 核实的根因与通用修复

| 问题 | 旧行为及代码证据 | 本轮改变 |
|---|---|---|
| 先澄清被绕过 | 旧 `react.py:1061` 仅定性词表且全文没有数字才暂停；`requirements.py:137` 可产生空而 complete 的义务集 | `clarification_obligations` 保留显式先询问流程和按字段绑定的未定阈值；Monitor 在首次规划前暂停，Domain 路径也在 Provider 前使用该检查 |
| 长否定句中的推荐词反转意图 | 旧 `react.py:978` 用短 lookbehind 判断“推荐”，且购买词优先；比较的报告防线被错误 filter 标签绕开 | 无商品依赖的 `query_semantics.py` 处理动作否定、转折及逗号插入语；Monitor、Domain、报告共享原始输入意图。真实“先筛选再比较”仍可筛选 |
| 尺寸最多被当成精确值 | 旧 `normalize.py:295` 提取英寸数字后固定 EQ；Proposal Parser 另有一套有限比较词 | 两条解析适配及覆盖审计共同使用 Pack 数量/单位合同；`最多/至多/以下`→LTE，`至少/以上`→GTE，范围保留两端，不把反向范围偷偷排序修正 |
| 已解析分辨率被误拦截 | 旧 `requirements.py:98` 只取“必须”后面的文本，丢失前置字段；ASCII 边界还阻止“4K分辨率”匹配 | 审计完整主谓分句，中文字段别名不套 ASCII 词边界；保留真正未解析要求，不删除覆盖门 |
| 可选接口误成否定硬约束 | 旧 `normalize.py:347` 将“没有USB-C也可以”匹配为必须没有；取消也可能遗留旧 Memory 硬要求 | `modality.py` 提取原文可选片段；可选≠false，字段取消和后续明确覆盖按出现顺序；接口、视频能力分开处理 |
| 隐含接口产生冗余硬条件 | 视频能力匹配同时创建 has_usb_c 硬条件 | 默认 Monitor 的隐含接口仅作兼容软字段，不能独立淘汰；单独明确要求接口仍是硬条件。旧50题的 Proposal 输出合同保留，未改历史金标 |
| Memory 掩盖新的未知要求 | 审计只看某字段是否已有 active 硬条件；旧4K可掩盖本轮“分辨率必须满足新的要求” | 明确非数值要求必须绑定当前输入，旧会话或长期值不能代替未解析新要求。只修消费约束入口，不修改 Memory 存储规则 |

对应现代码：[`query_semantics.py`](../../decision_core/query_semantics.py)、[`requirements.py`](../../decision_core/requirements.py)、[`quantities.py`](../../contracts/quantities.py)、[`modality.py`](../../contracts/modality.py)、[`normalize.py`](../../constraints/normalize.py)、[`engine.py`](../../constraint_proposals/engine.py)。没有按品牌、型号、case_id 或整句查询设置生产分支。新增表达测试使用虚构身份和参数，变形覆盖长距离否定、插入语、不同字段、单位及多从句。

## 3. 默认产品路径与完成语义

默认请求仍是 `POST /api/smartbuy/portfolio/run`，Trusted 模式：

- Monitor：[`portfolio_run`](../../api/router.py) → 既有编排器选择器 → 默认 `ReactOrchestrator` → [`PurchaseDecisionAgent`](../../agent/react.py)。不需要 `use_natural_constraints`、Domain Pack 开关或 LangGraph 开关。
- Laptop/Headphone：文档启动配置下既有 `PortfolioRuntimeManager` → [`DomainDecisionAgent`](../../agent/domain_agent.py)，继续使用原 Pack、Product Query、Evidence 和 Checker。
- 原始意图先分清事实/比较/购买；显式先询问及不明确阈值是**未解决要求**，不是“用户没有硬约束”。初始义务检查、`set_requirements` 后检查及最终报告前检查防止条件被吞掉。
- 暂停返回公开 `report.clarification_state=pending`、问题列表、`abstained=true`、空推荐及 `usage.result_status=needs_clarification`；发生在模型前时调用数为0。兼容顶层 `status=completed` 表示本次 HTTP 操作完成，不是决策已完成。此默认入口没有新增 checkpoint/resume 协议；用户补充清楚的要求后再次提交。
- 有效约束进入同一确定性 SQL 模板、Evidence Check 和 Checker；轨迹继续分别显示 suggested_sql、executed_sql、effective_filters，LLM 理由无权伪造确认阈值。
- [`reporting.py`](../../agent/reporting.py) 再检查原始意图：即使上游错误标成 filter，事实/比较也不能获得购买推荐资格。既有“所有对象×字段”的完成矩阵继续生效；无对象时仍保留请求字段的 unknown，不用空矩阵掩盖缺失。
- 没有放宽四态、Checker、Scope、来源/地区、Open/Trusted 边界。未改依赖、默认开关或 API 请求 Schema；没有替换自研 ReAct。

## 4. 开发首败与回归口径

首败及中间兼容失败保存在[开发失败记录](../../eval/results/trusted_intent_development_first.json)。新增测试遵循先红再修；旧测试、断言及冻结50题没有删改。中间全量曾为757 passed/6 failed，其中空候选动态字段丢失和旧 Proposal 精确合同退化均完成修复；新意图规则当时也处于并行整合中，不用后续成绩抹掉这些记录。

| 本轮离线验证 | 结果 |
|---|---|
| CI 等价全量 | **790/790**：原681项保留，新增109项；3条既有依赖弃用警告 |
| V1 原始18个测试文件当前回归 | **101/101** |
| 新意图变形 | 31/31 |
| 新数值/可选/覆盖取消语义 | 51/51 |
| 新原文义务和 Memory 遮蔽 | 10/10 |
| 新报告意图防御 | 3/3 |
| 新默认 Portfolio HTTP 测试 | 14/14，含零收费澄清、比较闭包和无条件正常路径 |
| 旧四态/Checker/三品类/Memory/事实完成 | 包含在保留的原681项和全量回归中，未跳过 |

[重建式15题输入](../../eval/trusted_intent_exposed_v1.json)仅来自已执行响应。**11条用响应摘要、字段和公开失败机制重建，4条保留公开原文；不是原题逐字重放，更不是原独立评分器。** 原始响应没有保存其余11条的完整用户句子；为保护未运行题，没有打开混有64题的题库来补全。

修复中的[首次 Fake 开发结果](../../eval/results/trusted_intent_offline_regression.json)与固定生产 `bad83ea` 的[独立保存的离线结果](../../eval/results/trusted_intent_offline_fixed.json)分开保留。两次均为15/15（筛选9/9、比较5/5、澄清1/1），开发合同TP/FP/FN=18/0/0、请求字段引用68/68；它们**不替代4/15，不是实际模型完成率**。第一次记录的 HEAD+工作区差异仅是中间开发审计；最终结果绑定已提交且运行时干净的生产版本。

Fake planner 使用有界脚本，比较任务故意声明为 filter 来测试服务端覆盖；Fake KB 从治理账本取定位信息，真实 SQL/Evidence/Checker仍执行，数据是既有12型号/4价格/16来源/180证据。SQLite integrity=ok，外键违规0，9/9筛选金标集合可由只读 SQL 校核。未运行真实向量检索、qwen-plus、Reranker、Source Search或其余64题。收费API=0，费用¥0；Fake耗时不能当作模型性能。

## 5. 质量门与保护范围

- Ruff、Compileall、JavaScript **13/13**、PowerShell AST **6/6**通过；Markdown链接及暂存区 diff 检查通过，细项见[质量记录](../../eval/results/trusted_intent_quality_audit.json)。
- 凭据模式扫描：暂存新增/修改内容0命中；全库有1个历史合成 Workspace 测试占位匹配，人工核对后真实凭据0。该历史文件未改。没有读取真实环境变量值；测试子进程清空模型凭据并只注入 Fake。
- 新增禁止产物0。原供应商已有测试数据库夹具保持原 blob，不把它误称成本轮运行数据库。临时 SQLite 位于仓库外；没有新 Chroma/MinIO/Memory/缓存/日志入 Git。
- 没有启动持久 FastAPI/MinIO，TestClient生命周期结束后目标端口8000/8088/9000/9001监听0。没有改用户系统环境变量。
- main、feature/proofpick-v2、RC3、RC4、V1 Tag及独立评测分支哈希保持不变；旧 Catalog、Pack、数据/索引文件、评分器、结果和原测试文件 diff 为0。本轮只在新修复分支提交、推送，不创建PR/Tag/Release，不合并。

## 6. 离线复现与下一步

使用现有冻结依赖；单元测试不需要真实凭据、服务或索引：

```powershell
uv run --project vendor/youtu-rag --frozen python -m pytest smartbuy/tests vendor/youtu-rag/tests/rag/api/test_config_security.py -q
uv run --project vendor/youtu-rag --frozen ruff check smartbuy
uv run --project vendor/youtu-rag --frozen python -m compileall -q smartbuy
uv run --project vendor/youtu-rag --frozen python -m smartbuy.scripts.check_markdown_links
uv run --project vendor/youtu-rag --frozen python -m smartbuy.eval.run_trusted_intent_regression --output C:\ai\trusted-intent-local-check.json
```

回归脚本拒绝覆盖既有结果，示例输出必须选不存在的本地文件。脚本强制Fake模型与KB并清空子进程凭据；不会运行独立评测器。新测试入口见[项目结构](../development/PROJECT_STRUCTURE.md)。

仍有限制：确定性规则不是任意自然语言语法器；未做真实模型、多轮前端或剩余64题验证；默认API的暂停是报告合同而非新会话交互控件；历史自然 Proposal 的正向视频隐含接口合同保留以兼容原50题，不将其旧结果改写为本轮新语义成绩。

建议独立方固定 `bad83ea7512e6b53ae554bbd4a1f80f0c3f4f715`，复测**已暴露15题**的默认 API、付费前澄清、操作符及可选条件、比较闭包和禁止推荐。是否继续64题及是否冻结下一版候选仍由用户与独立方决定；本报告不宣称发布通过。
