# ADR-0010：版本化 Product Pack 与字段级 Evidence Ledger

- 状态：Accepted for opt-in local ingestion
- 日期：2026-08-31
- 阶段：V2-2
- 关联：[V2-2 报告](../v2/v2_2_product_pack_report.md)、[运行说明](../v2/v2_2_runtime.md)

## 背景

V1 以单一 canonical JSON 和生成脚本维护 12 个显示器。继续靠修改 Python、SQLite 或事实卡接入商品，会让来源、地区版、字段证据、索引和回滚失去统一版本边界。V2-1D 已建立通用契约与 Monitor Domain Pack，但 ProductPack 当时只有只读接口。

## 决策

1. Product Pack 使用 Draft 2020-12 JSON Schema 和严格 Pydantic 契约，Schema/Pack/Data/Domain/Embedding/Chunk 配置分别版本化；禁止动态 Python、额外字段和重复 JSON key。
2. 新商品用稳定 product id、market、variant key 与 alias 对齐。未知值必须是 null，单位只按 Domain Pack 白名单换算；重复型号、别名冲突和错误地区一律拒绝。
3. 每个非 null 字段必须绑定 source id、片段、地区、配置版、来源版本、观察时间和再分发状态。来源只允许公开 HTTPS 和可再分发元数据/摘要；第三方原文不进入 Pack。
4. 统一 Evidence Ledger 同时承载 V1 Adapter 证据和新 Pack 治理证据。请求级证据使用独立 `temporary/not_reviewed` 契约，只能位于仓库外，不能自动晋升。
5. `stage` 先在仓库外临时目录生成 SQLite、事实卡、向量文档、Ledger、索引清单和 artifact hashes，再原子移动；`publish` 原子切换当前指针，`rollback` 只指向已校验不可变版本。失败不得污染当前版本。
6. SQLite 继续复用 V1 四实体 Schema 与只读工具；Checker/Evidence 比较规则不重写。新增商品由数据驱动，工具只增加通用路径参数，不增加型号特判。
7. Product Pack 运行路径由 `PROOFPICK_PRODUCT_PACK_ENABLED` 显式控制且默认关闭。关闭时不访问 Pack；开启后配置或版本错误 fail closed，不允许静默回退。
8. 每个数据版本生成独立索引 collection。Embedding 固定为 `text-embedding-v4`/1024；数据、切分、模型或维度变化必须重建。离线构建只标记 `documents_ready`，真实 Chroma 完成前不得标记 `completed`。

## 后果

收益是新增第 13 个显示器无需型号级 Python 逻辑，所有字段可追溯并可整体回滚；旧 V1 数据和工具仍能通过 Adapter 使用。代价是一个发布版本包含完整的 13 型号快照，构建时间与存储高于增量覆盖；真实 Chroma 仍需显式、有成本上限的独立步骤；当前 Schema 只证明 Monitor Pack，不证明第二品类。

## 否决方案

- 直接修改 V1 canonical JSON：会破坏冻结哈希和历史评测基线。
- 允许无来源字段或自动补全 unknown：会削弱 Evidence/Checker 安全门。
- 发布时逐文件覆盖当前目录：中途失败会产生数据库、事实卡和索引版本撕裂。
- 使用旧 collection 增量写入新维度/模型：无法证明索引契约一致，且难以可靠回滚。
- 将临时联网片段自动晋升为正式证据：缺少许可、地区和人工治理门。

## 回滚

运行 `rollback` 将 `current.json` 指向已校验旧版本，或把 `PROOFPICK_PRODUCT_PACK_ENABLED=false` 后重启恢复 V1，无需迁移 V1 SQLite、Chroma、事实卡或冻结评测。禁止通过删除版本目录、移动 V1 Tag 或修改历史文件完成回滚。
