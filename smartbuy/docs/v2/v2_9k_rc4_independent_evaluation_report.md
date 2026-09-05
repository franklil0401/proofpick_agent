# ProofPick RC4 独立验收报告：真实回归未全通过

评测日期：2026-09-05（北京时间）

结论：**前置真实回归 3/4，暂不进入剩余独立任务，也不建议据此发布。**

RC4 修复了此前的中文宽度约束遗漏；本次没有再推荐宽 611.9mm 的违规商品。但一条事实问答在检索后跳过 Evidence Check，虽然数据库已有答案，最终仍将两个请求字段返回为 unknown。该问题已通过原始响应、固定生产代码和只读工具复核确认，不是旧引用格式评分事故。

本轮只测四条**已暴露失败回归**，不是四条新 Holdout，更不能用 75% 代表三品类总体效果。余下 **79 条 Trusted、15 条 Online 均未运行**。停止依据是预先冻结的“四条已暴露失败全部修复后再继续”前置门，不是把该小样本当成完整发布评分。

## 1. 固定版本与评测隔离

- RC：proofpick-v2-rc4。
- 交接 Commit：`e7ea993a6393c4c886be977a5eed2532d800fe26`。
- 生产 Commit：`99c7bccc523addc7e8904571dbe8e20a24615c66`。
- 生产 Tree：`6b6e98009cefe5aa13f64cf8fe1b24d001fbadb1`。
- Manifest Payload：`7126740e9a893a18575f829aff78ef48b346eca0f622db73c952ece4cff8eb25`。
- 独立评测分支：`eval/v2-9k-independent-rc4`。
- 本轮评测器预冻结 Commit：`6715bd3`，发生在收费调用之前。
- Run ID：`rc4-exposed-20260905T143614Z`。

独立分支保留旧 RC3 评测历史并合入 RC4 交接，未移动旧独立评测分支、RC3/RC4 发布分支、main 或 V1 Tag。所有执行的725个生产成员均核对至固定 Git blob；评测分支自己的 Tree 不冒充生产 Tree。只新增评测文件和报告，没有修改生产代码、Prompt、Pack、数据、评分器、题目或金标。

原题与金标仍来自 [原冻结记录](../../eval/v2_9i_independent/freeze.json)，类型兼容仍使用此前获授权的 [score_v2.py](../../eval/v2_9i_independent/score_v2.py)。本轮没有再次修订评分逻辑。

## 2. 前置核验

独立复算23组、725个唯一成员、组 Aggregate 和 Payload，全部一致。脚本直接读取 Git blob；工作区执行文件另做换行归一化比较，不混淆语义冻结与 checkout 字节。

三品类本地 SQLite 完整性均为 ok、外键违规0，每品类12个商品。实际 Chroma 片段数为 Monitor 60、Laptop 12、Headphone 12，全部1024维，Collection/Data/Index版本与 RC4 一致。Laptop、Headphone 数据指针同时由现有严格 Loader 验证。本轮复用上一轮仓库外索引，未重新向量化；这不是一次新的干净克隆部署评测。

实跑质量门：

- CI 等价离线测试：597/597，3条既有弃用警告，163.86秒。
- V1 原始18个测试文件在当前版本回归：101/101，15.82秒。
- 既有评测器兼容测试：17/17。
- Ruff、Compileall：通过。
- JavaScript：13/13；PowerShell AST：6/6。
- 文档链接：112份文档、545个链接均有效；新评测材料实际凭据和高置信敏感模式均0命中。相关服务端口均无监听。

这些是工程/离线证据，不与真实模型成绩相加。用户提供的远端生产 CI 记录不冒充本轮评测分支远端 CI。

## 3. 四条真实回归

实际通过 HTTPX ASGITransport 向挂载的 FastAPI 发送 `POST /api/smartbuy/portfolio/run`，执行原生产默认路由。仅省略本机TCP网络层，没有替换云端Provider，也没有使用专用内部Runner。Monitor仍是默认 V1兼容ReAct，未打开 Natural、DomainPack 或 LangGraph 隐藏开关。

长期Memory关闭，每题独立session。使用真实 qwen-plus、text-embedding-v4、qwen3-rerank；没有模型任务重跑、Checkpoint恢复或热缓存包装。

- **001：通过。** 精确 U2723QE 事实核对，所需宽度、分辨率证据齐全，不再因 UltraSharp 系列词而错误澄清。
- **005：通过。** 精确 PA279CRV 事实核对完成，查询字段没有错误激活为购买硬约束。
- **007：失败。** 精确 PA27JCV 身份已正确识别，也成功召回片段；但跳过字段核验，宽度和分辨率未给出。
- **011：通过。** 刷新率至少144Hz、机身宽度最多610毫米两项均进入有效约束、实际SQL与Checker。返回 ASUS PG27AQDM、BenQ EX2710U、LG 27GS95QE-B 三款，均符合条件；Dell G2724D（611.9mm）未被推荐。

因此，旧“身份歧义”和“宽度约束丢失”已有真实改善；007这次失败的原因不同于 RC3，不能说旧身份修复完全没有效果。

本轮精确分母：

- 任务：3/4；三个事实任务2/3，一个筛选任务1/1。
- 清晰硬约束：TP/FP/FN=2/0/0，仅来自一条筛选任务，不外推为通用100%。
- 事实任务请求字段覆盖：4/6。
- 推荐商品硬字段证据覆盖：6/6。
- 旧评分器汇总 requested_fact_evidence=10/12，包含事实问答4/6和筛选金标字段6/6，不应把它误写为纯事实问答覆盖率。
- 本轮评分器捕获的安全违规：0；**不等于所有安全场景已覆盖**。剩余失败属于任务完成度和终态一致性问题。

## 4. 007失败：数据库有答案，Agent却提前结束

原输入：

> 请做资料核对：ProArt PA27JCV（CN地区；配置标识 asus-pa27jcv-cn）的机身宽度和分辨率各是什么？分别附上证据，不用给购买建议。

原始工具轨迹：

1. 提前调用 KB，被既有“先 set_requirements”守卫拒绝。
2. set_requirements 成功，所需字段正确为 width_mm、resolution。
3. KB Search 成功命中5个片段，Reranker正常。
4. 未执行 Evidence Check，finish_decision 却被接受。

最终响应 HTTP200，候选ID正确、没有购买推荐，但 candidates.fields为空。两个字段的引用都只有 Evidence ID/来源链接，`value=null`；unresolved_facts将width_mm与resolution标为unknown。同时 `abstained=false`，停止原因称“知识库证据检索完成”，形成“已结束但没有回答请求字段”的终态不一致。

只读核验结果：

- SQLite中的PA27JCV/CN：width_mm=612.2，resolution=5120x2880。
- 两条同型号、同地区治理证据都存在：
  `ev-asus-pa27jcv-cn-width-mm`、`ev-asus-pa27jcv-cn-resolution`。
- **直接调用现有只读 EvidenceCheckTool.invoke，不调用LLM，两个字段均matched。**
- 此次只读工具输出单独保存，绝不补进原始Agent响应来“修正成绩”。

源码证据（固定生产Commit）：

- [结束守卫](../../agent/react.py)：约525行只检查 `state.candidate_rows`；KB约763—794行登记的是 `candidate_pool_rows`。只走KB的事实任务可以绕过“有候选但没核验不得结束”的检查。
- [确定性补查](../../agent/react.py)：约1278行仅覆盖filter/comparison/dynamic，未覆盖fact；所以循环后也没补上核验。
- [报告充分性](../../agent/reporting.py)：约323行把“存在KB命中，且assessments中没有unknown/conflict”视为证据充分。assessments为空也会满足该条件，故本题 `abstained=false`。

这说明：**候选购买资格通过Checker，不等于用户询问的事实字段已经回答完成。** 两者需要不同的完成合同。

旧评测器兼容事故不适用于此题：本次不是把JSON TEXT数值解码错了，而是原响应确实没有字段值。正确引用不能自动替代已核验答案。

## 5. 建议开发方只做一个有界修复

不需要换模型、重建数据、增加搜索Provider、放宽Checker或重新出一整套题。建议本轮只补“事实/比较任务完成合同”：

1. 以解析后的商品Scope和requested_fields形成“商品×字段”的待核验集合；与权威候选池对齐，不能仅看SQL candidate_rows。
2. finish前检查每个请求字段的核验状态。KB命中、引用存在、assessments非空都不能单独表示全部字段完成。
3. 在工具次数、时间与费用限制内补调已有Evidence Check；部分字段漏查也应检测，不仅检测assessments完全为空。预算耗尽或工具失败时明确说明部分完成/未完成，不无限重试。
4. 报告终态由该合同决定。没有完成核验时不得显示证据充分；unknown/conflict如确由字段核验产生，则如实说明，不能将其描述为已确认产品事实。
5. 不给fact/comparison加购买推荐；不将requested_fields变成硬约束；保持Scope、Evidence四态与Checker权限。
6. 用虚构商品建立确定性测试：只走KB、完全跳过Evidence Check、仅核验一个字段、多商品缺一方字段、工具失败、预算耗尽、真正unknown/conflict。不得按case_id、型号或这条问句写特判。
7. 保留本次3/4和全部原始结果。开发方完成离线修复后，再由独立方以新固定生产版本复跑同四条**已暴露回归**，通过后才继续79条未运行题。

这次不能据小样本宣布三品类全面退化，也不能仅因“没有违规推荐”而跳过功能缺口。最小、可检验的下一步是补齐上述运行时合同，而不是继续扩张功能。

## 6. 成本、原始结果与限制

真实API请求33次：qwen-plus 21、Embedding 6、Reranker 6；输入124,770、输出3,567 Tokens，估算费用 **¥0.105153**。供应商请求重试0、失败0；工具轨迹中的顺序守卫拒绝不等于API网络失败。四个请求的端到端耗时约32.08、19.59、16.76、28.67秒。金额是用量估算，不是账户账单。

只读归因没有收费调用。诊断时两次临时命令误用了表名/工具方法，均在执行模型前失败；核对Schema和接口后纠正，不属于Agent重跑或评分器变更。

- [前置审计](../../eval/v2_9k_independent/preflight_audit.json)
- [冻结计划](../../eval/v2_9k_independent/README.md)
- [原始四题响应](../../eval/v2_9k_independent/results/exposed_first.jsonl)
- [原始评分](../../eval/v2_9k_independent/results/exposed_scores.json)
- [只读失败审计](../../eval/v2_9k_independent/results/failure_audit.json)
- [可复现诊断脚本](../../eval/v2_9k_independent/diagnose.py)

原始四题响应LF规范化SHA-256：`df4ae2f4b632eaff507abd50e49f1ae74eb091c8981a1bda29c86c7944e8cccd`。

评分文件SHA-256：`364617a317a1ecdc6c6ff4466cecaf6e6cdf0340fdb2c57a8e3695a688fed502`。

剩余79条Trusted的开发方未接触声明沿用RC4 Handoff；本轮未执行这些题、未创建新题。Online15条未运行，不能增加任何RC4 Online效果结论。模型别名未固定日期版本，本轮只有单次真实回归，不是稳定性/生产SLA评测。

## 7. 可以直接发给开发Agent的话

请读取本报告和failure_audit.json。RC4四条已暴露真实回归为3/4，宽度遗漏已修复；剩余问题是fact任务只命中KB便允许finish，Evidence字段核验缺失，报告却显示abstained=false。

本轮只修复事实/比较任务的字段完成合同：以Scope×requested_fields检查字段状态，统一candidate_pool来源，在有界预算内补调已有Evidence Check，并让报告终态与真实完成度一致。不要改变Checker/Evidence权限，不增加型号或case_id特判，不读取剩余79条Trusted与15条Online题及金标，不重新出Holdout，不覆盖本次3/4。

在新的修复分支完成通用实现、虚构商品负例测试、全量/V1回归和文档，提交推送后停止。报告固定生产Commit与diff，由独立评测方执行四条暴露真实回归；未经确认不要发布、合并main或移动现有RC。
