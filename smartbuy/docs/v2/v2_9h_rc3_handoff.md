# V2-9H RC3 独立评测交接

## 候选身份

- RC：`proofpick-v2-rc3`
- 定位：Trusted Multi-domain Decision Core + Experimental/Beta Online Research
- 生产 Commit：`ba6606ae249bafc89c18b320935c767a3f756c34`
- 生产 Tree：`84766c5d8840b50a27c612e24379b6dd63736741`
- Semantic Manifest Payload SHA-256：`4883f4251c8cb1f4dc6b86b6777b3d19ace74bee92943129c1146fc4e266b367`
- 默认模式：Trusted

先读取 [机器 Manifest](../../eval/results/v2_9h_rc3_semantic_runtime_manifest.json)、[Manifest 说明](v2_release_candidate_rc3_manifest.md)、[RC3 报告](v2_9h_rc3_release_candidate_report.md)、[Windows 复现](v2_9h_windows_reproduction.md)、[ADR-0023](../adr/0023-trusted-core-and-experimental-online-research.md)和 [Demo 指南](v2_demo_guide.md)。

## 独立评测规则

1. 先校验生产 Commit/Tree、Payload Hash、19 组完整成员列表和三个 Domain 的 Data/Index/Collection/文档数/1024 维合同。
2. 评测方在看结果前独立创建、冻结并哈希新的 Trusted 与可选 Online 任务和评分规则；开发分支不得预览未来题目。
3. V2-9B/V2-9D 的 `90+15` 题及其改写均已暴露，不能冒充新 Holdout；V2-9C/E/F 回归和 V2-9G PoC 也不能变成发布首次结果。
4. Trusted 和 Online 分开计分。Trusted 使用本报告的联合阻断门槛；Online 的安全门是强制项，完成率是公开的非阻断 Beta 指标。
5. “安全返回 unknown”只证明 fail closed，不计为网页研究完成；实际完成必须形成请求字段对应的 Open Evidence。
6. 首次失败、Checkpoint 恢复、Provider 重试和评测器事故永久保存。不得改题、改金标、改评分器或删除失败后重跑成首次。
7. Open Evidence 进入 Trusted Checker、错误域名/型号/配置/地区进入 usable、Scope/Checker/Report 越界或 unknown 过度声明，均为安全失败。
8. 评测时不得修改生产代码、Prompt、Pack、数据、索引或默认模式；机器差异只通过 Semantic Manifest 审计，不用时间/路径原始字节哈希挡住复现。

## 建议评测分层

- Trusted：Monitor/Laptop/Headphone 分层报告，覆盖事实查询、比较、购买筛选、自然约束、身份/地区/配置、Evidence 闭包、澄清、Memory、Checker 与 Ranker。
- Online Beta：单独记录 Source Search→域名→型号→配置→地区→抓取→提取→规范化→Open Evidence 的严格单调漏斗，同时报告候选级分支，不混用分母。
- Windows：从新短 ASCII 路径复现 frozen sync、bootstrap、三 SQLite、三索引、页面/接口、五 Demo 与 stop。

## 禁止与停止条件

- 不合并独立评测分支，不把评测器代码直接并入生产，不创建 Tag/Release/PR。
- 不以 Online 安全终态替代实际取证，不宣称实时价格、库存、全市场覆盖或生产 SLA。
- 任一冻结合同不一致、测试失败或安全门失败时停止并报告，不移动 RC3 身份。

新的独立评测通过前，README 和 UI 的状态保持 Release Candidate / Experimental，不得写成 V2 已发布。
