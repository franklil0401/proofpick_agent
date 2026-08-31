# ProofPick V2-2 Product Pack 与字段级证据账本报告

最后更新：2026-08-31

状态：**V2-2B 真实索引与 KB Search 收尾验收完成；Product Pack 正式运行路径仍默认关闭**

基线：V1 `d51b6668a6a45c1b01ef4e64da3c4b9ac84ed10c`；V2-2 `33e9540ba7ad5152cbc23acd5c5fafbdcf2da6c4`

## 1. 结论与范围

V2-2 把新增显示器从 Python 代码改动收敛为受版本控制的数据导入：严格 JSON Schema、字段级 Evidence Ledger、外部 staging、校验、原子发布、版本查看和指针回滚已经落地。V2-2B 又在仓库外为正式 Data Version 构建并实测了独立的真实 Chroma 索引。示例 Pack 仅新增 1 个美国版显示器，V1 的 12 个型号、SQLite、事实卡、60-chunk Chroma、40 条冻结任务、Checker 规则与历史评测文件均未修改。

V2-2 主体验收使用本地夹具与 Fake Provider，调用和费用为 0；V2-2B 只为 65 份文档建库和 6 条最小查询调用百炼 Embedding/Reranker。没有 Source Search、Web Extractor、第二品类、在线价格、Product Pack 自动联网导入或 V2-3 能力。

## 2. 95/120 与 94/119 计数只读审计

开始业务开发前，分别从 V1 Tag 和 V2-1C Commit 提取干净源码并比较 pytest node id；没有修改或补写任何历史测试。

| 审计对象 | `smartbuy/tests` 收集 | CI 等价收集 | 差异 |
|---|---:|---:|---|
| `v1.0.0-portfolio` / V1 Commit | 94 | 95 | CI 另显式收集 1 条 vendor 安全测试 |
| V2-1C `59e506640abeff4e11c8dc4264e930a0c63cfdae` | 119 | 120 | 同一条 vendor 安全测试 |

额外 node id 为：

```text
vendor/youtu-rag/tests/rag/api/test_config_security.py::test_redact_sensitive_config_recursively_without_mutating_source
```

V1 的 94 个 `smartbuy/tests` node id 在当前分支缺少 0 条；V2-1C 的 119 个 node id在当前分支缺少 0 条，没有测试被重命名、合并或变为未收集。因此，历史“95/120”采用的是 CI 等价范围，V2-1D 报告里的“94/119”描述的是 `smartbuy/tests` 范围，属于**统计口径差异**，不是实际回归缺失。本报告保留两套历史数字及其分母，不修改 V1 报告或冻结结果。

## 3. Product Pack 契约

版本化 Schema 位于 `smartbuy/product_packs/schema/product-pack-v1.schema.json`，当前 Schema/Pack 版本均为 `1.0.0`。Pack 顶层包含：

- 身份与版本：`pack_id`、`pack_version`、`domain_id`、`base_data_version`、`data_version`、`created_at`；
- 兼容边界：通用契约、Domain Pack、切分配置、`text-embedding-v4` 和固定 1024 维；
- 许可边界：再分发状态、数据许可说明，以及 `raw_content_included=false`；
- 数据实体：products、sources、evidence、追加式 observations。

Loader 同时执行 Pydantic 严格校验和确定性关系校验：拒绝额外字段、重复 JSON key、超限 Pack、错误版本、别名碰撞、重复型号、非规范地区、未知单位、字符串形式的 `unknown`、缺少字段来源、来源/型号/地区/配置版不一致、受限再分发状态、非公开 HTTPS 来源和内容治理哈希不符。未知值只能用 JSON `null`，不能用 0 或“unknown”替代。

## 4. 第 13 个显示器

示例 Pack：`smartbuy/product_packs/examples/monitor-u2725qe-us/pack.json`

| 项目 | 治理值 |
|---|---|
| 稳定 ID | `dell-u2725qe-us` |
| 型号 | Dell UltraSharp U2725QE |
| 地区/配置版 | US / `u2725qe-us-210-bqhr` |
| 来源版本 | Dell part `210-BQHR` |
| 官方来源 | [Dell 美国官方产品页](https://www.dell.com/en-us/shop/u2725qe-monitor/apd/210-bqhr/monitors-monitor-accessories) |
| 许可边界 | `metadata_and_summary_only`；只提交元数据、自制短摘要和结构化事实 |
| 关键字段 | 27 英寸、3840×2160、120 Hz、IPS Black、非 OLED、USB-C/DP 视频、最高 140 W EPR |
| 未知字段 | `release_date=null`；不猜测补全 |

型号名、别名、`market=US`、配置版、官方 source id 和 16 条字段证据完全由 Pack 提供，Python 代码中没有该型号分支。宽度由 24.11 inch 确定性换算为 612.394 mm；所有非 null 字段均有 source、snippet、market、variant、source_version 和 observed_at。

## 5. 字段级 Evidence Ledger

构建产物 `evidence_ledger.jsonl` 使用 `ledger_schema_version=1.0.0`。每条记录包含：

- `evidence_id/source_id/product_id/field_id` 与原始值、规范化值、单位；
- 来源片段、定位、URL、地区、配置版、来源版本、生效/观察时间；
- confidence、conflict_group、再分发状态、normalizer/data version 和内容哈希；
- `trust_state=governed`，用于区别请求级临时证据。

V1 180 条 evidence 通过只读 Adapter 映射，新型号增加 16 条，正式 Ledger 共 196 条。`RequestEvidenceWorkspace` 只允许写入仓库外目录，记录固定为 `trust_state=temporary`、`promotion_status=not_reviewed`；它支持查看与清理，但不会自动提升或写入正式 Pack。本阶段没有真实联网搜索。

## 6. Staging、发布与回滚

```text
pack.json
  -> load + normalize + validate
  -> 仓库外临时构建目录
  -> SQLite / fact cards / vector documents / ledgers / data manifest
  -> artifact SHA-256 + SQLite + documents_ready 契约再校验
  -> staging/<data_version>
  -> versions/<data_version>（原子移动）
  -> current.json（Data Version 原子指针）
  -> text-embedding-v4/1024 全量构建独立 Chroma
  -> 文档/Chunk/维度/元数据/逻辑哈希完整校验
  -> current_index.json（Index Version 原子指针）
```

- `stage` 在临时目录完整构建，任一步失败都会删除临时目录，当前版本指针不变。
- `publish` 只接受已校验 staging；同一版本内容不同会被拒绝，不覆盖已发布版本。
- `rollback` 只把数据指针切回已校验的不可变版本；`rollback-index` 只选择属于当前 Data Version 且已完整校验的索引。关闭开关仍可无迁移恢复 V1 路径。
- 运行根目录必须位于 Git 工作区外。`PROOFPICK_PRODUCT_PACK_ENABLED` 默认 `false`；关闭时不会访问 Product Pack 文件系统，也无需迁移 V1 数据。显式开启时若真实索引还只是 `documents_ready`，运行选择器会 fail closed，不会用空索引伪装成功。

CLI 支持 `import`、`validate`、`publish`、`versions`、`current` 和 `rollback`，详见 [运行说明](v2_2_runtime.md)。

## 7. 幂等、数据与工具验收

两次独立构建得到相同结果：

| 项目 | 结果 |
|---|---|
| V2-2 主体历史 Manifest SHA-256 | `555cc472cabb04d71b9e58da5e5a984fcf9e3859b0a6cf40a6b37d57611479d2`（保留原始记录） |
| V2-2B Manifest SHA-256（build 1 / build 2） | `ce2467a3aee76b56e996b79f5b67b618a43e929cc780f364fc9c16d32100db88` / 相同 |
| 规范化逻辑数据 SHA-256 | `21d565cb3d664e9de39f3006bb160d5b6ac71a57a55ccb66d95bed4455387fac` |
| SQLite 逻辑 SHA-256 | `375f3b317074bf6ea824179f8866f49527e273b47946cdcba0f4d0608a73c326` |
| Vector documents SHA-256 | `5f6e1ea9fa5e2b8cd7dbec883fe4a4d4db7c6ca633edfa178194d96d741247ee` |
| SQLite | products 13、prices 4、sources 17、evidence 196；`integrity_check=ok`；外键违规 0 |
| 生成内容 | 13 份事实卡、65 份向量文档、196 条 Ledger |
| 索引契约 | `text-embedding-v4`、1024 维、65 documents / 65 chunks；Data Manifest 为 `documents_ready`，独立 Live Index Manifest 为 `completed` |

V2-2B 为真实检索增加了别名、配置版和来源版本的 chunk 元数据，因此当前派生 Data Manifest/向量文档哈希与 V2-2 主体首次报告不同；逻辑商品数据和 SQLite 逻辑哈希保持不变。该变化只发生在 V2 仓库外重建产物，V1 Catalog、60-chunk 索引和历史实验结果没有改动。

第 13 个型号的离线主链验证：

- Text2SQL：用 `model_id` 与 `usb_c_power_delivery_w >= 140` 返回且只返回 `dell-u2725qe-us`。
- Evidence Check：尺寸、分辨率、USB-C 视频和供电 4/4 为 matched。
- Constraint Checker：美国版 27 英寸、4K、非 OLED、USB-C 视频和至少 140 W 的候选资格通过。
- KB Search：使用真实生成的 5 份 U2725QE 向量文档、现有 KB Search 代码和 Fake 1024 维 Provider/Store，命中正确 model_id 并绑定字段证据。

上述是 V2-2 主体的离线结论：当时只证明生成文档、元数据、型号过滤和 Evidence 绑定可被现有工具消费，Data Manifest 因此保持 `documents_ready`，没有被改写成在线完成。V2-2B 以下列独立 Live Index Manifest 闭合真实建库与查询，二者口径不混用。

### 7.1 V2-2B 真实索引与 KB Search

V2-2 主体的 Fake Provider/Store 结论继续保留，不能冒充在线结果。V2-2B 使用相同正式 Data Version 完成了以下独立验收：

| 项目 | 真实结果 |
|---|---|
| Data Version | `monitor-multi-region-2026-08-31-v2` |
| Index Version | `monitor-multi-region-h2-v2-embedding1024-r1` |
| Collection | `proofpick_monitor_v2_b9e7bc6d41a735fa` |
| 模型/维度 | `text-embedding-v4` / 1024 |
| 文档/Chunk | 65 / 65，13 个型号 |
| 建库 | 7 个成功 Embedding 批次，9,785 input tokens，估算 ¥0.0048925 |

`U2725QE`、`dell-u2725qe-us`、`210-BQHR` 三种查询均为正常 Reranker 路径，目标型号的 5 个片段占据 Top 1～5；命中统一绑定 `dell-u2725qe-us`、US、配置版 `u2725qe-us-210-bqhr`、官方来源 `src-dell-u2725qe-us-official-product` 和字段级 Evidence ID。`dell-u2723qe-cn` 定向查询只返回 CN / `dell-u2723qe-cn-v1`，没有混入 U2725QE 美国版。

组合任务“4K、USB-C 视频、至少 140W，并核验 U2725QE 美国版”完成了 Text2SQL→KB Search→Evidence Check→Constraint Checker 闭环：SQL 候选包含且只包含目标型号，3 个关键字段均为 matched，Checker 仅保留目标型号。真实 Reranker 返回正常；受控 Reranker 故障不请求错误远端服务，明确标记 degraded 并使用向量排序，目标型号仍命中。

首次使用 32 条批量输入被接口以 HTTP 400 拒绝，Provider 按规则没有重试；根据阶段 3 已知接口边界改为最多 10 条后成功。首次验收脚本还因预期 source id 少写 `-product` 而在首条查询后停止，数据和索引并无错误；修正断言后完整运行通过。这两次失败均保留在成本口径中，没有通过重跑掩盖。

成功建库与最终验收共 18 次有计量调用、28,400 input tokens；另有 1 次无用量返回的 HTTP 400 和 2 次中断验收调用。按相同查询计量估算，本轮总费用约 ¥0.0168605，低于 ¥1 上限。没有 LLM 或完整 40 条在线评测调用。

## 8. 失败矩阵与 V1 保护

| 验证 | 结果 |
|---|---:|
| Product Pack 定向测试 | 23/23（含 3 条真实 Chroma 本地事务测试） |
| 非法单位、重复型号、错误地区、缺来源、损坏 Pack 等 | 8/8 被拒绝 |
| 发布产物损坏 | 1/1 被拒绝，当前版本未改变 |
| 第二版本发布后回滚 | 1/1，数据库/事实卡/索引/Manifest 版本一致；两套本地索引指针回滚 1/1 |
| 实时索引失败门 | Provider 失败、数量错误、维度错误、Manifest 不符和未完成索引均 fail closed，当前指针不变 |
| V1 目录、评测和 Demo 关键哈希 | 5/5 不变；Demo 保存结果仍为 4/4 |
| V1 冻结索引隔离 | 原 collection `smartbuy_monitors_v1` 仍为 60 chunks，路径与 V2 索引不同 |
| V1 既有 node id | V1 94/94、V2-1C 119/119 均保留 |

一次首次定向运行曾为 15/16：非法单位已被底层 Domain Pack 正确拒绝，但异常类型没有包装成公开的 `ProductPackValidationError`。修复只增加脱敏异常边界，随后相关矩阵 6/6 通过；再增加许可越权和 V1 source id 碰撞门后，最终定向全量 20/20 通过。首次失败没有改写成首次全通过。

最终 `smartbuy/tests` 为 177/177；加入同一条上游配置脱敏 node 后，CI 等价套件为 178/178，另有 3 条既有依赖弃用警告。Ruff、Compileall、JavaScript 12/12、PowerShell AST 5/5、Markdown 相对链接 262/262 和 `git diff --check` 均通过；本轮变更敏感凭据命中 0、禁止运行产物 0、冻结/保护路径修改 0。全仓扫描仍识别 2 个 V1 既有的假凭据/示例文件，两者与 HEAD 完全一致且未输出正文。

历史阶段 6 的 92/120、阶段 7 的 34/40 与首次失败文件没有重新运行或覆盖。V1 目录、冻结结果与旧业务规则未修改；当前新增总测试数不能反向改写 V1 的历史 95 项口径。

## 9. 已知限制与 V2-3 前置条件

1. Product Pack 当前只允许 `domain_id=monitor`，证明的是显示器新增商品无需 Python 型号分支，不代表第二品类已经通用化。
2. 来源 `content_hash` 是治理捕获（ID、URL、访问时间、自制摘要）哈希，不是远端网页原始字节哈希；原文不进入 Git。
3. 真实 Chroma 已在本机仓库外构建并验证，但不会随 Git clone 分发；新环境仍需按运行说明显式重建。模型、维度、切分或数据版本变化必须创建新 collection，不能复用旧索引。
4. 请求级临时证据不会自动晋升；V2-3 若引入 Source Search，必须保留人工/确定性 Promotion 门和来源许可检查。
5. V1 与 V2 数据模型继续通过 Adapter 并存，本阶段没有删除旧 Schema 或重写 Checker/Evidence 规则。

进入 V2-3 前需要用户单独授权并确认真实搜索 Provider、允许域名、费用上限、缓存与引用边界；在此之前 Web Search 仍保持 unavailable/degraded。Product Pack 开关继续默认关闭，V1 稳定路径不变。

设计决策见 [ADR-0010](../adr/0010-versioned-product-pack-and-evidence-ledger.md)，数据边界见 [Data Card](../data_card.md)。
