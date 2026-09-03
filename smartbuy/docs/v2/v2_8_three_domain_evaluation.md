# V2-8 三品类交叉验证

## 验证对象

Monitor、Laptop、Headphone 共用通用 Product/Constraint/Evidence/ToolResult 契约、编排适配层、Checker 执行框架、Ranker 和 Memory 框架；字段、策略、Profile、Product Pack、SQLite 与索引由各 Domain Pack/Data Version 独立拥有。

## 结果

| 不变量 | 结果 |
|---|---|
| 品类 A 独有字段进入品类 B | 0 |
| 品类 A 数据/Evidence 被品类 B Repository 接受 | 0 |
| Headphone 索引跨品类召回 | 0/30 |
| 三品类长期 Memory 互相污染 | 0 |
| 错误 Domain/Data/Index 组合 | 全部 fail closed |
| Headphone 可信模式违规推荐 | 0/30 |
| 主观 Evidence 支持硬事实 | 0 |
| Headphone ReAct/LangGraph 代表资格差异 | 0/3 |

Monitor 的 V1 兼容映射与双编排器安全门、Laptop 的 10 条双编排器语义一致性，以及 Headphone 的 3 条资格一致性共同验证了三品类路径。LangGraph 仍是显式开启的 V1/通用 Agent 兼容外壳，不据此宣称已完成图原生生产迁移。

## 硬编码审计

扫描 `smartbuy/agent`、`tools`、`constraints`、`ranking`、`memory`、`orchestration`、`retrieval` 的 Python 生产文件，搜索耳机字段、品牌、具体型号、`headphone-e2e-*` 和品类专属分支：新增命中 0。耳机差异只存在于 Domain Pack、Product Pack、评测、测试和有界验收脚本。

## 限制

这是固定治理数据、离线不变量和已暴露工程集上的交叉验证，不是新独立 Holdout，也不是生产多品类 SLA。Monitor 仍通过 V1 兼容适配层工作；V2 默认编排器没有切换。
