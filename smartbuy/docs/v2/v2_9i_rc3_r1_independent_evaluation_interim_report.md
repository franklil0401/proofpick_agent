# RC3-R1 独立评测：冻结复核通过，首次运行因评测器兼容缺陷暂停

日期：2026-09-05。结论性质：**阶段审计，不是完整发布评测或发布批准。**

## 结论先行

R1 Manifest 修复经独立核验有效。隔离 Windows 环境可安装、构建并启动三品类服务，全量离线测试通过。

但本轮新任务仅执行2/90，随后我方独立评分器发生误报并触发停止。复核明确：**第2题不是产品安全失败，而是我方没有兼容 V1 EvidenceReference 的 JSON 字符串和引用空值。** 不应据此要求开发者修改正确的产品值或放宽 Checker。

第1题存在独立的真实功能问题：用户给出了精确商品身份和两个待查询字段，却被不必要地要求澄清。

当前不得发布新的三品类正确率、F1、Online完成率或RC3通过结论；未运行的88条Trusted和15条Online保持未运行。原始结果、错误评分和本审计并存，不覆盖历史。

## 1. 冻结身份与独立核验

| 项目 | 实测 |
|---|---|
| 生产 Commit | `ba6606ae249bafc89c18b320935c767a3f756c34` |
| 生产 Tree | `84766c5d8840b50a27c612e24379b6dd63736741` |
| R1 Payload | `abf655017bdb0b27dfe3dd220d1e173e8a0e3e0ff2244590efc0d42d79fd6791` |
| 独立分支 | `eval/v2-9i-independent-rc3` |
| 评测器与题集冻结提交 | `3fa3902`，首次调用前已推送 |
| Git 成员审计 | 19组、267个唯一文件、370次成员出现；错误0 |
| 换行模式验证 | autocrlf=true、false、LF checkout；定向2/2通过 |
| 新题精确去重 | 扫描50个历史JSONL，602条历史输入，精确重复0 |

独立脚本直接执行 `git ls-tree` 和 `git cat-file blob`，重算每个Git原始对象、19组Aggregate与Payload，不以开发者的“成功”报告代替验证。

独立性边界：评测者未参与生产修复，但已经见过历史失败类型、结果和公共接口；本轮题目是新编并冻结的首次运行任务，不是完全双盲研究。精确字符串去重不等于证明没有语义重合。

完整定义见[冻结审计](../../eval/v2_9i_independent/freeze.json)与[评测说明](../../eval/v2_9i_independent/README.md)。

## 2. 数据和运行环境

在独立短ASCII clone与独立仓库外运行目录完成真实构建，没有复用开发仓库的运行指针。

| 检查 | 结果 |
|---|---|
| frozen依赖安装 | Python3.12.3，296包 |
| Windows Preflight | 11/11 |
| 三品类数据库 | 每品类12配置；SQLite完整性ok、外键违规0 |
| Monitor索引 | 60 documents/chunks，1024维 |
| Laptop索引 | 12 documents/chunks，1024维 |
| Headphone索引 | 12 documents/chunks，1024维 |
| 真实Embedding重建 | 成功，估算¥0.015586 |
| 页面和服务 | 首页、health、monitor、capabilities、classic、MinIO health均HTTP200 |
| Offline Replay | HTTP200，Experimental及非实时回放声明可见 |
| 五个固定Demo合同 | 5/5，API调用0；不是五个新在线测试 |
| 收尾端口 | 8000/8088/9000/9001均无监听 |

## 3. 新测试设计

Trusted90条，每品类30条，包含10条双字段事实查询、10条双条件购买筛选、5条双商品比较、5条困难负例。Online15条，每品类5条、每题3个请求字段。

金标直接来自冻结Catalog/Product Pack/字段证据，由独立简单比较器生成允许候选集合，不使用被测Parser或Checker生成答案。事实、比较和购买筛选分别计分；unknown、冲突、 unsupported和澄清有单独要求。

调用实际的 `portfolio_run` 产品入口，配置与启动脚本一致。显示器走V1兼容ReAct；Laptop/Headphone走显式V2 Domain Agent。不私自改变默认编排器或开启可选LLM约束回退。

本轮90条采用独立session、关闭长期Memory。现有Memory生命周期、What-if及LangGraph兼容测试属于工程回归，不能宣传为新增独立在线覆盖。

## 4. 已运行的两题

### 第1题：产品过度澄清

问题：

> 请做资料核对：UltraSharp U2723QE（CN地区；配置标识 dell-u2723qe-cn）的机身宽度和分辨率各是什么？分别附上证据，不用给购买建议。

冻结数据有宽度611.4mm、分辨率3840×2160，用户也提供了精确地区和product_id。但系统返回“请明确具体商品配置、地区或可执行的数值阈值”，未调用工具，未返回两个已知字段。

只读诊断定位至 `smartbuy/agent/react.py:880` 的 `_preflight_clarification_reason`：共享词UltraSharp匹配多个catalog名称，即返回`ambiguous_catalog_identity`；没有让同句中的精确U2723QE/product_id解除此歧义。这属于可用性/意图解析缺陷，不是违规推荐或Checker绕过。

建议开发方后续统一身份解析优先级：精确配置命中优先于系列词；并增加“系列全称+精确型号+地区+product_id”的通用回归。**评测方没有实施此修复。**

### 第2题：产品回答正确，评测器误报

问题：

> 请做资料核对：dell-s2722qc-cn的刷新率和屏幕尺寸各是什么？分别附上证据，不用给购买建议。

实际回答的`FieldAssessment.actual_value`为60.0和27.0，对应60Hz、27英寸。两条引用的Evidence ID、Source ID、URL、型号和地区均匹配冻结金标；没有推荐商品。

我方评分器存在两个缺口：

1. V1 EvidenceCheck从SQLite TEXT直接返回`EvidenceReference.value`，因此出现字符串`"60.0"`、`"27.0"`和JSON编码的地区`"\"CN\""`。评分器只处理了int/float语义等价，没有解码这一既存接口形式。
2. KB返回的引用可只有ID、字段和来源，`value=null`。它不是一个矛盾事实断言，却被评分器算作错误绑定。

因此冻结评分器报`invalid_evidence_binding`，触发停止；人工审计确认是 **harness failure**，不是已确认的产品安全事故。9条合成自检没有覆盖这两种V1接口形式，这是本次评测设计遗漏。

## 5. 原始结果和修订纪律

已永久保留：

- [首次原始响应及调用账本](../../eval/v2_9i_independent/results/trusted_first.jsonl)。
- [原冻结评分器输出](../../eval/v2_9i_independent/results/trusted_scores_first.json)，其中0/2和错误绑定误报**不可作为有效产品指标引用**。
- [自动停止现场](../../eval/v2_9i_independent/results/trusted_safety_stop.json)。
- [人工事故审计](../../eval/v2_9i_independent/results/harness_incident_audit.json)。

原始响应SHA-256：`a14ca12f372d3eb8267dfc079270e353a5271b813181a36397514c21e9d3a5cb`。

没有修改已冻结题集、金标、评分器、生产代码、数据或索引，没有再次调用前两题，也没有运行剩余题或Online。

经授权后可新增一个单独版本的接口兼容层：明确区分“数值断言”和“仅引用”，依据冻结字段类型进行严格JSON解码；补充合成测试和契约测试，再审计已有两条原始响应。不需要重新付费运行这两题。新旧评分器、原始误报和修订输出必须同时保留；剩余88题保持首次调用，不能把修订历史删掉后声称从无评测器事故。

## 6. 费用、质量与发布状态

| 项目 | 结果 |
|---|---|
| 两题真实模型请求 | 7次：qwen-plus5、Embedding1、Reranker1 |
| 两题Token | 输入22,484，输出1,241 |
| 两题估算成本 | ¥0.0202718 |
| 含建库估算总成本 | ¥0.0358578，低于¥5 |
| Provider重试/题目重跑 | 0/0 |
| Source Search | 0次 |
| CI等价全量离线测试 | 518/518，3条已知弃用警告 |
| 评测器原合成测试 | 9/9；覆盖不足已记录 |
| Ruff/Compileall | 通过 |
| JavaScript/PowerShell | 13/13、6/6 |
| 生产逻辑改动 | 0 |
| PR/Tag/Release | 未创建 |

成本为项目冻结账本估算，没有访问账户账单核实扣费。全部评测产物经过凭据扫描，运行数据库、索引与服务日志留在仓库外。

**发布判断：当前尚无有效、完整的新独立发布评测结论。先处理评测器兼容事故，再决定继续；不要把这次中断解释成RC3三品类全线失败，也不能把518个离线测试通过当作90题发布验收已通过。**
