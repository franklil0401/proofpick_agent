# ProofPick Trusted79 独立评测报告：触发安全停止

日期：2026-09-06。结论：**当前固定版本不能据此通过发布验收；优先修复默认 Monitor 入口的澄清与意图解析。**

原计划执行79条此前未运行的 Trusted 任务，实际完成15条，4条通过、11条失败。第15条触发真实的“应先澄清却调用收费工具”违规，已停止。剩余64条未运行，不能算作失败，也不能算作通过。

这不是79条全量成绩，更不是三品类整体正确率。已运行15条全部属于 Monitor；Laptop、Headphone 本轮均未执行。先前4条已暴露回归的4/4保持独立，不与本轮拼接为新的90题成绩。

## 1. 测试对象与冻结边界

- 仓库：https://github.com/franklil0401/proofpick_agent
- 固定生产 Commit：`02e97a2c793ba75dfad5ece15e5df665652808bf`。
- 固定生产 Tree：`7e6b036bc3255714cd378e887ae8b9779a5ef98a`。
- 独立评测分支：`eval/v2-trusted79-continuation`。
- 评测起点：`f0e8989c6667e3c1e7daa5bce296189416618910`。
- 本轮清单与运行规则冻结 Commit：`843ff4a47f01b9688e9c6e183bc9c77dcb234ec3`。
- 本轮 Freeze SHA-256：`e22d9bca47c4f6111c507940d4b0a3bd79fc7e0a5b2ecb6fd71440ab55b28546`。
- 原90题文件 SHA-256：`ba1c146f14d257ad1c27f3367475eae78d1bf55c4f16dc2f2804a93a76244dd3`。
- Run ID：`trusted79-20260906T040000Z`。
- 预算上限：¥3；原题、金标、评分语义、生产代码、Prompt、数据和索引均未修改。

固定生产的1,193个文件与 Git blob 核对一致。成员聚合 SHA-256 为 `7bc167d9dd6744d8c9d9efaa76adad0f6402c0619dbbd18c6ef61bc5cf022816`。运行前后生产和运行数据校验结果一致。

三个现有索引均为1024维：Monitor 60 chunks，Laptop 12，Headphone 12；数据库完整性正常、外键违规0。复用已有索引，没有重新付费建库。

[冻结清单与逐题哈希](https://github.com/franklil0401/proofpick_agent/blob/eval/v2-trusted79-continuation/smartbuy/eval/trusted79_independent/selection.json)；[完整运行规则](https://github.com/franklil0401/proofpick_agent/blob/eval/v2-trusted79-continuation/smartbuy/eval/trusted79_independent/README.md)。

## 2. 实际入口与方法

测试通过 in-process ASGI HTTP 请求调用默认 `POST /api/smartbuy/portfolio/run`，不是直接调用内部工具来代替产品入口。

每题使用 Trusted 模式、独立会话、关闭长期记忆，接入真实百炼模型与现有数据库/向量库；没有启用隐藏编排开关。Monitor 保持默认的 V1 兼容 ReAct 路径。每题只有一次完整调用，先保存脱敏原始响应并落盘，再评分。没有重跑失败题、Checkpoint 恢复或热答案缓存复用。

请求级超时为180秒。普通功能失败继续执行；安全违规、计量异常、冻结不一致、评分器事故或预算问题触发停止。每个新任务前预留¥0.25预算，本轮实际未触及预算线。

计划构成：Monitor 19、Laptop 30、Headphone 30；其中事实查询20、筛选29、比较15、困难负例15。原来已运行的 Monitor 001～011排除在外。

实际仅执行 Monitor 012～026：筛选9、比较5、困难负例1。还未执行 Monitor 027～030，以及 Laptop、Headphone 各30条，共64条。

本轮沿用原独立评测方事先设计的任务，冻结后未据此修改生产代码。它不是本轮重新创建的 Holdout，也不是严格双盲研究。开发方先前声明未阅读这批剩余题；评测方原本参与出题，不能宣称评测方也未见过题目。

## 3. 本轮真实成绩与分母

- 执行进度：15/79；未执行64。
- 已执行任务正确率：4/15，26.67%。
- Monitor：4/15，计划19；尚有4条未执行。
- Laptop：0条执行，正确率 N/A；Headphone 同样 N/A。
- 筛选：4/9；比较：0/5；困难负例：0/1；独立事实查询未执行。
- 硬约束 TP/FP/FN：17/6/1。
- 微平均 Precision：73.91%；Recall：94.44%；F1：82.93%。
- 原评分器定义的推荐事实证据覆盖：67/67，100%。
- 仅事实/比较类请求字段覆盖：18/20，90%；本轮这些记录全部来自比较题。
- 原评分器全部“请求事实对”口径：56/68，82.35%；它还包括筛选题中所有金标合规候选的字段对，不能与上一项混用。
- 有充分数据却返回空推荐：3/9个正例筛选任务，33.33%。
- 应先澄清却调用收费工具：1条，触发硬停止。
- 原评分器未记录 Checker 越界、错误证据绑定、unknown 值过度声明或 Open Evidence 进入 Checker；这些0仅覆盖已执行15题和该评分器断言范围，不代表全面安全验证。

F1由全部已执行任务的 TP/FP/FN 相加计算；困难负例不作为清晰硬约束计分，事实/比较题错误激活的购买约束计入FP。0/0记为N/A。

67/67只说明评分器纳入的商品/字段事实对有对应证据，**不说明推荐行为符合用户意图**。例如比较任务不该输出推荐，未知需求也不该因有效约束为空就推荐全库。此指标也不覆盖报告所有自然语言、顶层价格展示和工具理由的真实性。

冻结的阶段门槛要求79题全部完成，Monitor至少16/19、另外两品类至少24/30，硬约束F1至少95%，推荐证据覆盖至少95%，且安全违规为0。目前明确不通过，不能冻结为“已获独立发布认可”。

[首次机器评分](https://github.com/franklil0401/proofpick_agent/blob/eval/v2-trusted79-continuation/smartbuy/eval/trusted79_independent/results/first_scores.json)；[基于原始响应的复算与分母审计](https://github.com/franklil0401/proofpick_agent/blob/eval/v2-trusted79-continuation/smartbuy/eval/trusted79_independent/results/recalculation_audit_v2.json)。

## 4. 阻断问题：明确要求先问，却直接推荐

题目 `rc3i-monitor-026`：

> 准备买显示器，宽度不能太大。请先问清楚具体能放多宽，再开始筛选。

期待行为：追问最大可接受宽度，不启动筛选和购买推荐。实际保存的响应表明：

1. 调用了5次 qwen-plus。
2. `clarification_state=not_required`，`pending_questions=[]`。
3. 最终硬约束列表为空，只保留中国大陆的默认软偏好。
4. `requirement_coverage.complete=true`，但其 `obligations=[]`。
5. 执行只读 SQL，实际筛选条件只有全库商品 ID 范围，返回12款。
6. 最终12款全部进入推荐集合，没有等用户回复。

另一个重要细节：工具轨迹中出现“用户确认的最大宽度500mm”的理由和建议 SQL，但用户根本没有给出500mm。确定性执行层正确拒绝了该无依据阈值，没有把它用于实际 SQL；然而拒绝之后没有回到澄清，反而按空的硬约束集合继续推荐。

因此这不是 SQL 执行了伪造阈值，也不是 LLM 覆盖了 Checker 的决定。**真正缺口在 Checker 之前：未解决的用户要求没有形成必须暂停的状态；Checker 只能检查它实际收到的条件。**

只读代码审阅支持这一解释：Monitor 的预澄清依赖有限表达列表，“不能太大”与显式“先问清楚”未被当前路径可靠拦截；覆盖检查又主要寻找数值或特定命令式条件，遗漏本题的定性需求与流程要求。该根因解释应由开发方用通用反例继续验证，而不能只添加本题字符串。

优先级：P0，阻止发布。应由原开发 Agent 修复默认 Portfolio 路径，而不是让评测 Agent 改生产代码。

[原始响应与工具轨迹](https://github.com/franklil0401/proofpick_agent/blob/eval/v2-trusted79-continuation/smartbuy/eval/trusted79_independent/results/first.jsonl)；[固定版预澄清逻辑](https://github.com/franklil0401/proofpick_agent/blob/02e97a2c793ba75dfad5ece15e5df665652808bf/smartbuy/agent/react.py#L1061)。

## 5. 其他失败与首错环节

本节的“首错”是根据保存响应和只读代码审阅形成的工程定位，不代表已完成修复或重新验证。全部11条失败均保留。

### 约束解析：3条

- `monitor-012`：USB-C视频输入需求额外激活 `has_usb_c=true`，多1个硬约束。推荐7款和相应事实证据正确，但冻结规则要求精确约束集合，因此判失败。它属于语义冗余/契约差异，严重性低于实际推荐错误；本轮没有临时放宽规则。
- `monitor-016`：“尺寸最多27英寸”解析成 `eq 27`，而非 `lte 27`。覆盖门识别到不一致后暂停，导致本可回答的任务空推荐。这里安全拒绝有效，但上游解析有错。
- `monitor-020`：“没有USB-C接口也可以”被当成必须没有USB-C，即 `has_usb_c=false`。当前返回型号碰巧符合金标，并不说明额外限制是正确语义。

### 要求覆盖检查误拦截：2条

- `monitor-017`：“分辨率必须为5120x2880”已正确进入约束集合，却又被标成未解决要求，空推荐。
- `monitor-019`：3840x2160的同类表达发生相同问题。

代码审阅显示，命令式检查截取“必须”之后的文本，将前面的字段名“分辨率”丢掉，可能因此无法把该片段与已解析字段关联。这是候选根因，不是本轮新增运行结果。

### 意图识别：5条

`monitor-021～025`全部是明确要求“只比较参数，不把对象当作推荐商品”的任务；默认链路却将它们标成 `filter`。

- 021、022、023：请求的字段证据完整，但比较对象被输出为购买推荐。
- 024：除了错误推荐，还激活了USB-C视频硬约束，遗漏两款商品的尺寸证据。
- 025：USB-C视频、OLED两个查询字段被误当成硬约束；虽然最终没有推荐，仍不满足“仅做参数对照”的语义。

已对这5条保存输入单独调用原有的纯分类函数，不调用 Agent 或模型：即便传入声明类型 `comparison`，返回值仍是 `filter`。原因是“推荐”的短距离否定匹配无法处理“不要把对象当作推荐商品”，且购买词判断优先于比较判断。

这也解释了为何新增事实完成模块没有兜住全部比较题：报告层依赖上游任务类型，错误进入筛选分支后，事实/比较的完成度与推荐禁止规则没有按预期生效。

[分类器只读诊断](https://github.com/franklil0401/proofpick_agent/blob/eval/v2-trusted79-continuation/smartbuy/eval/trusted79_independent/results/classifier_diagnostic.json)；[固定版分类逻辑](https://github.com/franklil0401/proofpick_agent/blob/02e97a2c793ba75dfad5ece15e5df665652808bf/smartbuy/agent/react.py#L964)；[固定版报告分支](https://github.com/franklil0401/proofpick_agent/blob/02e97a2c793ba75dfad5ece15e5df665652808bf/smartbuy/agent/reporting.py#L126)。

## 6. 成本、时延与评测器事故

模型请求103次：qwen-plus 77、Embedding 13、Reranker 13。输入466,551 Tokens，输出10,418 Tokens；记录中的重试0、失败请求0。

估算费用 **¥0.389128**，低于¥3上限。估算使用固定生产 Provider 账本费率，不是账户账单核销；未把历史评测费用混入。预检、静态诊断、复算和本轮修订均未调用收费 API。Source Search、Online、网页抓取调用为0。

15题请求级平均耗时18.553秒；P95按 nearest-rank 计算为33.881秒。统计包含3条立即返回澄清的任务，不含请求计时之前的首次 Provider/索引初始化，也不含真实网络服务器传输开销，不能作为生产SLA。

离线复算时出现一个我方审计脚本事故：原评分器在内存里使用 tuple，保存JSON再读取后变成 list；直接做Python对象相等比较会失败。首次真实任务评分和汇总没有受到影响。

处理方式：保留冻结的 `audit.py` 和事故记录，新增 `audit_v2.py`，只比较相同的JSON序列化表示。3项合成测试验证：tuple/list表示可兼容，数值/操作符变化和安全标签变化不可兼容。复算15题后，全部逐题分数及汇总与首次结果一致，没有重跑模型、改金标、改评分语义或改变安全停止结论。

[事故记录](https://github.com/franklil0401/proofpick_agent/blob/eval/v2-trusted79-continuation/smartbuy/eval/trusted79_independent/results/audit_incident.json)。

## 7. 质量检查与证据保全

本轮验证：

- 生产 CI 等价套件：681/681，3条既有依赖弃用警告。
- V1原始测试文件当前回归：101/101。
- 原评分器/引用适配合成测试17项、本轮分母测试2项，通过19/19。
- 离线审计格式修订新增测试：3/3。
- Ruff、Compileall、JavaScript 13/13、PowerShell AST 6/6通过。
- 运行前565个本地文档链接通过；新增报告链接另在交付前复查。
- 1,267个当时存在的Git跟踪/待纳入文件凭据扫描：实际值、Bearer、私钥模式均0命中。新增报告另行扫描。
- 新增运行数据库、索引、缓存、模型权重、真实.env：0。
- 生产文件和三套运行数据前后校验一致；旧评测目录变化0。
- main、RC3、RC4、V1 Tag及固定修复分支未改动。
- 没有创建PR、Tag或Release，没有修改开发工作区。

原始响应 SHA-256：`87cd927c50d09d5c65de5f452340dd0991c81d7fa972315cd116ca9e46d276d8`。

首次评分 SHA-256：`c0fb79cf106fea2820aa7c2d459bdc1633bb685545991cad015aa941b37ae0a2`。

评测工件哈希按原协议统一 CRLF/LF 后计算；固定生产成员使用 Git blob原字节，二者口径明确分离。

[质量审计](https://github.com/franklil0401/proofpick_agent/blob/eval/v2-trusted79-continuation/smartbuy/eval/trusted79_independent/results/quality_audit.json)。

## 8. 下一步应交给谁、做什么

**交给原开发 Agent修复，不应让独立评测 Agent继续跑模型来碰通过。**

建议开发任务按以下顺序完成：

1. 先修复“必须澄清”的状态契约。定性要求未给阈值、用户显式要求先提问、模型提出却被拒绝的关键约束，都不能因最终硬约束集合为空而静默进入推荐。模型调用、业务工具调用和发布推荐分别设置可审计的门禁。
2. 统一默认入口的原始意图解释，处理完整否定作用范围。比较/事实请求不得因否定句里出现“推荐”就进入购买路径；报告层不能只依赖一个可能误判的任务类型字段。
3. 让要求覆盖检查与约束解析使用一致的字段和操作符契约，解决“最多/必须为/也可以”等语义；不要通过放宽Checker、删除冲突或虚构阈值来提高通过率。
4. 用默认Portfolio API验证通用反例，覆盖否定距离、同义改写、多个从句、精确单位和范围。测试数据不要依赖本题case_id或具体型号。
5. 保存本轮15条首次结果。它们今后只能作为已暴露回归，不能再次计为首次未见评测。修复后先对这15条回归，再交由独立评测方按新授权和固定提交处理剩余64条。
6. 本轮不授权实现这些修复，也不授权继续剩余64条。保留它们的执行次数为0，不为凑完整成绩新增题集或替换原题。

剩余64条题目与金标不要交给开发方调试；报告只给出已运行的失败样本和根因线索。开发方可阅读生产实现及本报告，但应继续遵守剩余任务隔离。

## 9. 结论限制与复现说明

本轮能确认：默认显示器入口仍存在真实用户指令遵循问题；单元测试和少量定向回归通过不能代替完整产品入口验证。

本轮不能判断：Laptop或Headphone的当前真实质量、三品类全量泛化率、Online Research能力、多轮记忆、浏览器交互、生产并发与安全SLA。本次负例只执行1条，也没有独立Prompt Injection专项，不能据“未命中”外推覆盖率。

不建议把4/15直接放到简历，也不能继续只宣传此前4/4来表示当前版本全面通过。对外应说明版本尚在验证，并将“证据核验正确”和“理解并遵从用户任务”分开描述。

复现以本报告链接的Python脚本、冻结清单、原始JSONL和机器评分为准。使用相同固定依赖环境，只运行离线复算模块即可核查结论；不要再次启动一次性付费Runner。原Python脚本与机器记录已提供完整审计链，因此没有再复制一份Notebook。文档用文字和精确分母表达，未添加无助于判断的图表。

本报告属于一次有明确安全停止点的独立技术审计，不是完整发布评测，也不是新的RC冻结。
