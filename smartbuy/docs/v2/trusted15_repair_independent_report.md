# ProofPick 意图与澄清修复：原始15题真实复测报告

2026-09-06。**真实回归从4/15提升到14/15；上一轮的澄清安全问题已在原题上修复，但仍有1条USB-C要求被误拦截，不能宣称15题全部通过或V2发布通过。**

本次独立执行的是原始15题，不是开发方重建题。每题只进行一次新的真实运行，全部完成；未修生产代码、未重跑失败题、未改金标或评分规则。剩余64题和Online任务均未运行。

## 1. 核心结果：主要问题修复，仍有一个确定性误拦截

- 同一组已暴露原题：旧生产4/15，本次14/15，93.33%。
- 筛选：8/9；比较：5/5；澄清困难负例：1/1。
- 原先通过的4题本次仍通过；原先失败的11题中10题恢复，1题仍失败。
- 硬约束TP/FP/FN：18/0/0；Precision、Recall、F1均100%。
- 推荐事实证据覆盖：34/34，100%。
- 比较任务请求字段证据：20/20，100%；5条均没有购买推荐。
- 有充分数据却空推荐：1/9个正例筛选任务。
- 原评分器安全违规：0。关键澄清题另经原始响应人工复核，不仅依赖评分器通过。
- 真实模型接口请求117次，估算¥0.4239502，低于本轮¥1上限。

**F1为100%不等于任务全部正确。** 剩余题目的两个硬约束实际上解析对了，但后续覆盖门再次要求澄清，所以没有完成选购任务。

这批15题全部属于Monitor、已经暴露并用于修复定位，属于真实模型回归，不是新的未见Holdout，不能外推成三品类或全市场正确率。

[首次机器评分](https://github.com/franklil0401/proofpick_agent/blob/eval/v2-trusted15-repair-check/smartbuy/eval/trusted15_repair_independent/results/first_scores.json)；[同题配对与独立复算](https://github.com/franklil0401/proofpick_agent/blob/eval/v2-trusted15-repair-check/smartbuy/eval/trusted15_repair_independent/results/recalculation_audit.json)。

## 2. 最重要的安全问题：现在会先暂停，而不是直接推荐

原题 `rc3i-monitor-026`：

> 准备买显示器，宽度不能太大。请先问清楚具体能放多宽，再开始筛选。

旧版本调用5次LLM，最终推荐12款显示器。新版本的真实响应为：

- `clarification_state=pending`，有非空待确认问题。
- 模型调用0，业务工具调用0，推荐商品0。
- `abstained=true`。
- 要求覆盖检查明确为不完整，保留 `explicit_confirmation_required`，不再把未解决要求当成空条件。
- 本次HTTP操作返回成功，但报告仍是等待澄清，不代表已经完成购买决策。

因此，“未问清楚就开始筛选推荐”的本题安全缺陷已经验证修复。这不是Fake测试的推断。

仍有一个不阻断本项安全验收的交互问题：提问文案会复述原句并显示工程错误码。后续可改成“桌面最大能放多宽？请给毫米或厘米”，但本轮没有修改UI或文案。

证据见[保存的原始响应](https://github.com/franklil0401/proofpick_agent/blob/eval/v2-trusted15-repair-check/smartbuy/eval/trusted15_repair_independent/results/first.jsonl)末条记录及复算文件的 `clarification_corroboration`。

## 3. 比较、数值上限及可选条件已在原题上恢复

本次真实结果确认：

- `monitor-016`：“尺寸最多27英寸”不再按等于27英寸解释，筛选通过。
- `monitor-017/019`：5120×2880、3840×2160的“分辨率必须为……”表达不再被覆盖检查误拦截，两题通过。
- `monitor-020`：“没有USB-C接口也可以”不再成为必须没有USB-C，两条真实硬约束正确保留。
- `monitor-021～025`：全部归类为比较，全部覆盖两款商品所需的金标字段，不再把比较对象输出为购买推荐，也没有把查询字段误激活成购买硬约束。

修复前后结果采用原题、原金标和同一评分器。由于这是各版本一次真实运行，并非多次随机对照实验，不能把单次耗时差异或通过率变化外推为稳定SLA。

## 4. 唯一剩余失败：USB-C视频要求被重复解释成独立接口硬要求

原题 `rc3i-monitor-012`：

> 请从已收录的显示器中挑选：尺寸正好27英寸，必须支持USB-C视频输入。不限制地区，保持各配置独立，给出符合条件的选择及依据。

新版本已正确得到：

- 屏幕尺寸等于27英寸：硬约束。
- 支持USB-C视频输入：硬约束。
- 隐含具有USB-C接口：兼容软字段，不应成为用户单独提出的硬约束。

但覆盖检查又扫描到“USB-C”别名，将 `has_usb_c` 作为必须独立存在的硬要求。由于它现在是软字段，检查将原句标成 `unresolved_explicit_requirement`，要求用户再次确认，最终返回空推荐。

本题在首次模型调用前即被拦截：费用0、工具调用0。因此不是随机模型回答差，而是解析器与覆盖检查对同一句话的解释不一致。

与上一版的区别是：上一版推荐正确但多激活一个硬约束，因精确约束评分失败；这一版修掉了冗余硬约束，却引出覆盖检查误拦截。不能只看约束F1恢复为100%就认为整题完成。

### 为什么开发方Fake 15/15没有发现它

开发方保存的重建题写的是：

> 请从已收录显示器中筛选：尺寸正好27英寸，需要USB-C视频输入。不限制地区，保持各配置独立。

原题是“**必须支持**”，重建题是“**需要**”。新覆盖检查针对“必须”等命令式词语执行额外审计，因此两种表达进入不同判断路径。

本轮额外进行了只读的纯解析函数对照，没有再次调用Agent或模型：

- 原始题：覆盖检查 `complete=false`。
- 开发方重建题：覆盖检查 `complete=true`。

这说明重建题并不等价于原题；并不表示开发方伪造了成绩，其报告已明确披露重建与Fake边界。

建议修复方向：让复合能力字段与隐含接口关系在要求审计中使用一致的语义映射，避免“所有命中的别名都必须独立成为硬约束”。同时保留用户单独明确要求接口、明确禁止接口、真正未知字段的校验，不能简单删除覆盖门或将所有软字段视作满足硬要求。

[只读对照脚本与结果](https://github.com/franklil0401/proofpick_agent/blob/eval/v2-trusted15-repair-check/smartbuy/eval/trusted15_repair_independent/results/remaining_failure_diagnostic.json)；[固定生产覆盖检查](https://github.com/franklil0401/proofpick_agent/blob/bad83ea7512e6b53ae554bbd4a1f80f0c3f4f715/smartbuy/decision_core/requirements.py)；[固定生产约束解析](https://github.com/franklil0401/proofpick_agent/blob/bad83ea7512e6b53ae554bbd4a1f80f0c3f4f715/smartbuy/constraints/normalize.py)。

## 5. 分母说明：证据指标不能替代完整任务验收

本轮15题构成为筛选9、比较5、澄清1。硬约束微平均按TP/FP/FN汇总，负例不作为清晰硬约束计分；比较题如误激活硬约束仍计FP。无分母时记为N/A。

推荐证据34/34只涵盖实际输出的推荐事实对；不包含被空推荐遗漏的候选。它不是“所有用户需要的信息均已回答”。

原评分器的全部请求事实口径为54/68，79.41%；上一轮为56/68，82.35%。本次总任务通过数上升，但这个覆盖率略降，原因是唯一失败的012题涉及7个合规候选×2个字段，共14个未回答的事实对。其余已知事实对全部覆盖。不能隐藏这个下降，也不能只宣传34/34。

仅比较任务的分母固定为20，本次20/20；其与全部68个事实对是不同指标。旧版推荐事实67/67与新版34/34的分母随实际推荐内容改变，尤其旧版含错误产生的比较推荐，不能把分母减少解释为证据能力退步。

## 6. 固定版本、执行路径和费用

- 固定生产 Commit：`bad83ea7512e6b53ae554bbd4a1f80f0c3f4f715`。
- 固定 Tree：`5f3bdc6f50ec4ad71636ac745d31881f4323f7ed`。
- 独立分支：`eval/v2-trusted15-repair-check`。
- 原题/评分器/运行配置冻结提交：`5ccdd3b`。
- Freeze SHA-256：`c414585b07883e27da2eb63106e1fb9d819f87659945d9080ba093f3cc44e9f0`。
- Run ID：`trusted15-repair-20260906T120144Z`。
- 固定生产1,204个成员均与Git blob核对一致；成员聚合哈希：`ab022c69801cd1dd5cfc403d9d76e3ad97aabfc1c733c1a9dfc86837c1f49e28`。

通过 in-process ASGI HTTP 请求调用默认 `POST /api/smartbuy/portfolio/run`。Monitor使用原默认兼容ReAct，没有启用隐藏编排器或用内部函数替代产品入口。每题独立会话、关闭长期Memory，复用已验证索引。

三品类数据/索引合同前后核对一致：每类12个配置，Monitor 60 chunks、Laptop 12、Headphone 12，均1024维；SQLite完整性正常、外键违规0。此校验不是重新执行三品类真实评测。

本轮真实接口请求117次：qwen-plus 87、Embedding 15、Reranker 15；输入507,365 Tokens、输出11,472 Tokens。记录中的请求失败、重试、Checkpoint恢复均0。

估算费用¥0.4239502，低于¥1；使用固定Provider账本费率，不是账户实际账单核销。没有重建索引、联网搜索或运行剩余64题。纯解析诊断和结果复算费用0。

请求级平均耗时20.208秒，P95 nearest-rank为30.378秒。样本含2条无需模型即返回的任务，不含计时前的首次Provider/索引初始化，也不含真实TCP和浏览器耗时，不能作为生产SLA。

## 7. 校验、历史保全与可复查证据

- 本机重新执行生产全量：790/790，3条既有依赖弃用警告。
- V1原始测试文件当前回归：101/101。
- 原评分器及引用适配测试17项、本轮分母测试2项：19/19。
- Ruff、Compileall、JavaScript 13/13、PowerShell AST 6/6通过。
- 首次结果保存后，使用同一评分器从原始JSONL重新计算，逐题结果与汇总完全一致；没有修改评分器，没有新的评测器事故。
- 关键澄清题另核对实际问题、pending状态、模型调用、业务工具和推荐集合，不把一个非空状态字符串当作澄清证据。
- 1,297个当时存在的跟踪/待纳入文件凭据扫描：实际值与高置信模式命中0；后续新增诊断和报告另在交付前检查。
- 新增禁止运行产物0，生产文件未修改，旧原题/金标/评分器/结果目录变化0。
- main、V1 Tag、RC3、RC4、开发修复分支及上一轮评测分支保持不变；没有创建PR、Tag、Release。
- 8000、8088、9000、9001无残留监听。

原始JSONL SHA-256：`acc30c5adf24d770aafdcf3d2824ebcb860cacd2cd4ecb10408cf54995209a51`。

评分SHA-256：`8634fbd08f4994f2bba22bd5ca615a58d8a2a07ed629eb51fd6e159373ec13c0`。

评测工件依原协议统一换行后散列；固定生产成员直接散列Git blob原字节，不混用两种口径。

[完整原始响应](https://github.com/franklil0401/proofpick_agent/blob/eval/v2-trusted15-repair-check/smartbuy/eval/trusted15_repair_independent/results/first.jsonl)；[质量审计](https://github.com/franklil0401/proofpick_agent/blob/eval/v2-trusted15-repair-check/smartbuy/eval/trusted15_repair_independent/results/quality_audit.json)；[运行规则与复现入口](https://github.com/franklil0401/proofpick_agent/blob/eval/v2-trusted15-repair-check/smartbuy/eval/trusted15_repair_independent/README.md)。

## 8. 下一步：针对一个剩余问题收尾，不必扩大开发范围

建议交原开发Agent修复USB-C复合字段的覆盖检查一致性，并使用原始012题及通用改写验证“必须/需要/硬性要求”等表述。不要只修改测试文本，也不要按型号、case_id或完整句子打补丁。

保留本次14/15和旧4/15。修复后可先独立真实复测这条失败原题，并保留其他已通过任务的回归门禁；是否继续剩余64题，应在新固定提交与用户明确授权下另行决定。本轮不自动修复或继续评测。

本次结论是“主要修复已被真实原题验证，仍有一个功能缺口”，不是“项目仍只有4/15”，也不是“已经获得完整发布认可”。

尚未回答的问题包括：剩余64题能否通过、三品类未见表达的泛化表现、长期Memory与多轮UI实测、Online Beta能力。这些不能从本次已暴露Monitor回归推断。安全0也只对应本轮样本及现有断言，不是全量攻击面证明。

报告沿用用户既有Markdown交付方式。Python模块、冻结清单、原始JSONL和机器审计提供可复查的方法记录，不另做重复Notebook；少量精确指标以文字列明，未使用可能掩盖样本范围的图表。
