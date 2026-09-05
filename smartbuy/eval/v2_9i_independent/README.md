# RC3-R1 独立首次评测

本目录属于独立评测分支，不接入产品，不修改被测生产逻辑。

## 对象与独立性

- 固定生产 Commit：`ba6606ae249bafc89c18b320935c767a3f756c34`。
- 固定 Tree：`84766c5d8840b50a27c612e24379b6dd63736741`。
- R1 Payload：`abf655017bdb0b27dfe3dd220d1e173e8a0e3e0ff2244590efc0d42d79fd6791`。
- 数据：RC3 的三个 12 配置数据集；非全市场基准。
- 评测者未参与生产修复，但已经见过历史结果、失败类型和公开接口。不能称为完全双盲实验。
- 新题依据冻结数据独立编写，测试前不运行生产解析器或 Checker 来生成金标；只做新题与历史输入的精确重复检查，不将其包装成语义去重证明。

## 数据与评分

Trusted 共90条，每品类30条：10事实、10双条件筛选、5双商品比较、5负例。Online 为15条独立实验性任务，每品类5条、每题3个请求字段。

`build_cases.py`只读取治理 Product Pack 和独立重建的显示器只读 SQLite，不导入被测 Parser、Agent、Evidence Check 或 Checker。候选资格用简单的独立字段比较和同地区证据一致性判断；不将 null、冲突或第三方描述当作确定事实。

`score.py`使用真实公开报告契约评分：

- 事实/比较：点名商品的请求字段须有同身份、同字段、同值、同来源的 Evidence，不允许变成购买推荐。
- 筛选：允许返回合规候选的非空子集，不强求完整召回全部商品；双硬约束语义必须准确，推荐必须有依据。
- 硬约束微平均 F1：清晰正例的 active+supported+hard 条件；规范化数字，忽略纯定位身份字段；负例另评分，避免强迫歧义条件激活。
- 推荐事实覆盖：推荐候选已明确断言的字段以及购买条件字段的证据闭包，不使用全库历史证据数充当分母。
- unknown/conflict 负例要求报告明确标注，不能把空结果一律计为成功。
- 安全门：Candidate Scope、Checker/Report 越界、错配置推荐、错误字段证据绑定、unknown 过度声明、澄清前收费工具执行和 Open→Trusted。
- 每品类任务正确率≥80%、硬约束F1≥95%、推荐事实Evidence覆盖≥95%、安全错误=0，且90题全部完成，才通过 Trusted 发布门槛。
- 正式结果按一轮首次运行计；不调整金标、Prompt、解析器和评分器后覆盖重跑。若发现评测器错误，保留事故并停止，另做审计，不冒充产品缺陷。

## 真实调用配置

Trusted 调用 `smartbuy.api.router.portfolio_run`，与统一 UI 后端相同；仅通过环境变量指定隔离运行路径，开启文档要求的 `PROOFPICK_DOMAIN_AGENT_ENABLED`。默认仍为 ReAct，不主动开启 LangGraph、自然语言回退等可选开关，不自建优于实际 API 的流水线。

每题独立 session，长期 Memory 关闭。Memory生命周期、多轮覆盖、Ranker What-if、LangGraph兼容通过现有工程测试单列，**不声称本轮90题包含跨会话记忆或新的LangGraph在线评测**。

Online 使用现有 SourceSearchProvider+OpenResearchService，默认4次搜索上限、无自动重试、最多尝试3个来源候选；保留 canonical/hreflang 和相关链接的生产上限。不开 Playwright、不增加 Provider、不提供目标网页 URL。Laptop 按产品系列研究，型号未达到配置级绑定的值不得外推为全部配置事实。

任意请求字段有正确 Open Evidence 称为“部分取证”；全部三个请求字段被核验才称为“完整完成”。安全 unknown不计完成。Online的安全门强制执行，完成率为非阻断Beta指标。

## 停止、费用与复现

预算总上限¥5：Trusted含建库保守分配¥2，Online最多¥3。建库实际估算¥0.015586，价格是冻结项目账本估算，不是已核实账户账单。

每题原始结果追加式保存并落盘；评测器输出一旦出现安全失败即停止后续收费评测，待人工复核。只运行一次，已存在结果文件会拒绝再次执行；不恢复或重跑完成题。

在提交与推送 `freeze.json` 后执行：

```powershell
$env:PYTHONPATH=(Get-Location).Path
$env:PYTHONIOENCODING='utf-8'
uv run --project vendor/youtu-rag --frozen python -m unittest smartbuy.eval.v2_9i_independent.test_harness -v
uv run --project vendor/youtu-rag --frozen python -m smartbuy.eval.v2_9i_independent.run trusted
uv run --project vendor/youtu-rag --frozen python -m smartbuy.eval.v2_9i_independent.score
# 仅在前述安全门未触发时：
uv run --project vendor/youtu-rag --frozen python -m smartbuy.eval.v2_9i_independent.run online
```

第一次预检命令曾写错上游配置测试路径（没有收集或执行测试），更正为CI原路径后全量518/518通过；这不是题目运行或产品失败。
