# V2-8 Headphone Domain Pack 阶段报告

## 结论

V2-8 已用第三个商品品类验证 Domain Pack 架构：Headphone 复用同一 Agent、工具、Checker、Ranker 和 Memory 框架，没有新增耳机专用 Checker。治理数据、真实 1024 维索引、30 条检索集、30 条工程集、四场景排序、Open Research 和三品类隔离均完成。结果属于作品集级 MVP/工程验证，不是生产 SLA。

## 数据与权限

- 12 个精确配置、4 个品牌、US/CA 两个治理地区；20 个来源、336 条 Evidence、38 个字段、30 个 Checker 字段。
- 官方/专业测量/主观来源分别为 12/4/4，Evidence 为 316/8/12。
- 非空 Checker 事实 Evidence 覆盖 `299/299`；属性缺失 `120/408`（29.41%），缺失保持 `unknown`。
- `subjective_review` 覆盖官方硬事实、进入 Checker 或恢复淘汰候选：全部 0。
- 两次构建 Manifest 均为 `36c0bf08ce945a67e7ecd0e485a9a269e7ad942788d428f2cb8af925208e8018`；SQLite 完整性通过、外键违规 0。

## 索引与检索

真实索引：Data Version `headphone-governed-2026-09-03-v1`，Index Version `headphone-governed-2026-09-03-v1-embedding1024-v1`，Collection `proofpick_headphone_v2_cae477364b46ccae`，12 documents/12 chunks，`text-embedding-v4` 1024 维。

30 条冻结检索集 SHA-256 为 `637c2b4a8fc61f97429af36cb6fc9e628b661212435c93497ae1b01d74e5efb1`：

| 指标 | Vector only | + qwen3-rerank |
|---|---:|---:|
| Recall@5 | 86.39% | 97.78% |
| nDCG@5 | 84.85% | 97.47% |
| 精确型号 Top-1 错误 | 1/19 | 0/19 |
| 错地区/配置绑定 | 0 | 0 |
| 跨品类召回 | 0/30 | 0/30 |
| 平均 / P95 延迟 | 338.3 / 392.6 ms | 220.8 / 281.3 ms |

小语料的 Recall@5 不代表开放环境检索质量；Reranker 失败时回退向量排序并公开 degraded 状态。

## Agent、排序与 Memory

30 条工程集 SHA-256 为 `851129b3eacac9b24bdbda675af5233912495c4d0d55bf8e4995e964de0b358d`。

| 指标 | 首次 | 通用修复后 exposed regression |
|---|---:|---:|
| 任务 | 27/30 | 30/30 |
| 清晰硬约束 F1 | 91.23% | 91.23% |
| 推荐事实 Evidence | 63/64 | 73/74 |
| 困难负例拒答 | 8/9 | 9/9 |
| 澄清绕过 | 1 | 0 |
| 明确违规/错配置/错地区/Scope/Checker/Report 越界 | 0 | 0 |

首次失败 `headphone-e2e-004/024/028` 永久保留；修复分别处理跨字段否定作用域、可拆卸麦克风精确字段映射和主观麦克风质量澄清。后续 30/30 是已暴露回归，不是独立 Holdout。

四个 Ranking Profile（commute/meeting/gaming/music）共 18 个维度；8/8 What-if 只改变顺序、不改变 Checker 集合，重复输入字节一致。长期 Memory 需明确确认，支持查看/覆盖/删除/关闭/开启与版本隔离；价格、库存、商品事实和未确认 Proposal 写入为 0。

## Open Research

最终从智谱搜索结果发现 Apple 爱尔兰官方 AirPods Max 页面，安全重定向到 AirPods Max 2 当前页；核验 `form_factor`、ANC、通透模式、空间音频和 20 小时官方续航，共 5/5 字段。来源 URL、IE 地区、时间、正文 SHA-256 完整；17 条临时证据均为 Open，进入治理 Ledger/Checker 为 0，`trusted_eligible=false`。

为避免隐瞒概率性搜索边界，前置 WH-1000XM6、G522、WH-CH720N、WL7024、ROG Delta II 宽域和 AirPods US 等空结果/地区降级均计入 20 次搜索诊断，总搜索费用 ¥0.76；最终验收调用 1 次、¥0.03。失败没有用硬编码 URL 绕过。

## 三品类与硬编码

三品类独有字段、Product Pack/SQLite、Evidence、索引、Memory 和错误版本组合均 fail closed；Headphone ReAct/LangGraph 3 条代表任务资格差异 0。共享生产目录对耳机字段、品牌、型号和 case ID 的新增硬编码扫描命中 0。详见[三品类交叉验证](v2_8_three_domain_evaluation.md)和 [ADR-0019](../adr/0019-headphone-source-authority-and-pack-reuse.md)。

## API 与成本

- 真实 Embedding/Reranker：62 次，¥0.1771825。
- Headphone Agent 首次与修复回归：51 + 49 次 qwen-plus，¥0.2075985。
- Open Research 搜索诊断：20 次，¥0.76；网页抽取和 Normalizer 无模型费用。
- V2-8 合计估算：¥1.144781，低于 ¥5；无 401/403 重试，无凭据落盘。

## 已知限制

数据只有 12 个配置且无价格；专业实测样本较少，主观结论不能泛化；30 条工程集由开发阶段创建，不是第三方盲测；Open Research 受搜索索引与静态页面可见性影响；Monitor 仍保留 V1 兼容适配层，LangGraph 未切为默认。V2-9 前应冻结独立发布集、完成产品 UI 和 Windows 三品类复现，不能用本阶段已暴露回归替代发布评测。
