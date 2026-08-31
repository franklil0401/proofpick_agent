# ProofPick V2-2 Product Pack 与字段级证据账本报告

最后更新：2026-08-31

状态：**离线实现与验收完成；Product Pack 正式运行路径仍默认关闭**

基线：V1 `d51b6668a6a45c1b01ef4e64da3c4b9ac84ed10c`；V2-1D `6b80a0c53728ccd9b68e17472eb20a67ba2f2a47`

## 1. 结论与范围

V2-2 把新增显示器从 Python 代码改动收敛为受版本控制的数据导入：严格 JSON Schema、字段级 Evidence Ledger、外部 staging、校验、原子发布、版本查看和指针回滚已经落地。示例 Pack 仅新增 1 个美国版显示器，V1 的 12 个型号、SQLite、事实卡、Chroma、40 条冻结任务、Checker 规则与历史评测文件均未修改。

本阶段没有 Source Search、Web Extractor、第二品类、在线价格、Product Pack 自动联网导入或 V2-3 能力。测试全部使用本地夹具与 Fake Provider；百炼 API 调用、Token 和费用均为 **0**。

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
  -> SQLite / fact cards / vector documents / ledgers / manifests
  -> artifact SHA-256 + SQLite + index contract 再校验
  -> staging/<data_version>
  -> versions/<data_version>（原子移动）
  -> current.json（原子指针更新）
```

- `stage` 在临时目录完整构建，任一步失败都会删除临时目录，当前版本指针不变。
- `publish` 只接受已校验 staging；同一版本内容不同会被拒绝，不覆盖已发布版本。
- `rollback` 只把指针切回已校验的不可变版本；SQLite、13 份事实卡、65 份向量文档、索引元数据和 Manifest 都随版本目录一起切换。
- 运行根目录必须位于 Git 工作区外。`PROOFPICK_PRODUCT_PACK_ENABLED` 默认 `false`；关闭时不会访问 Product Pack 文件系统，也无需迁移 V1 数据。显式开启时若真实索引还只是 `documents_ready`，运行选择器会 fail closed，不会用空索引伪装成功。

CLI 支持 `import`、`validate`、`publish`、`versions`、`current` 和 `rollback`，详见 [运行说明](v2_2_runtime.md)。

## 7. 幂等、数据与工具验收

两次独立构建得到相同结果：

| 项目 | 结果 |
|---|---|
| Manifest SHA-256（build 1 / build 2） | `555cc472cabb04d71b9e58da5e5a984fcf9e3859b0a6cf40a6b37d57611479d2` / 相同 |
| 规范化逻辑数据 SHA-256 | `21d565cb3d664e9de39f3006bb160d5b6ac71a57a55ccb66d95bed4455387fac` |
| SQLite 逻辑 SHA-256 | `375f3b317074bf6ea824179f8866f49527e273b47946cdcba0f4d0608a73c326` |
| SQLite | products 13、prices 4、sources 17、evidence 196；`integrity_check=ok`；外键违规 0 |
| 生成内容 | 13 份事实卡、65 份向量文档、196 条 Ledger |
| 索引契约 | `text-embedding-v4`、1024 维、独立 collection、`documents_ready` |

第 13 个型号的离线主链验证：

- Text2SQL：用 `model_id` 与 `usb_c_power_delivery_w >= 140` 返回且只返回 `dell-u2725qe-us`。
- Evidence Check：尺寸、分辨率、USB-C 视频和供电 4/4 为 matched。
- Constraint Checker：美国版 27 英寸、4K、非 OLED、USB-C 视频和至少 140 W 的候选资格通过。
- KB Search：使用真实生成的 5 份 U2725QE 向量文档、现有 KB Search 代码和 Fake 1024 维 Provider/Store，命中正确 model_id 并绑定字段证据。

KB 验收证明生成文档、元数据、型号过滤和 Evidence 绑定可被现有工具消费，不是一次云端性能测试。为保持 0 费用，本阶段没有调用百炼构建真实 Chroma；索引状态诚实记录为 `documents_ready`，不能描述为在线索引 `completed`。真实建库前仍必须显式调用固定 1024 维 Embedding，并将整个版本的新 collection 构建成功后再投入运行。

## 8. 失败矩阵与 V1 保护

| 验证 | 结果 |
|---|---:|
| Product Pack 定向测试 | 20/20 |
| 非法单位、重复型号、错误地区、缺来源、损坏 Pack 等 | 8/8 被拒绝 |
| 发布产物损坏 | 1/1 被拒绝，当前版本未改变 |
| 第二版本发布后回滚 | 1/1，数据库/事实卡/索引/Manifest 版本一致 |
| V1 目录、评测和 Demo 关键哈希 | 5/5 不变；Demo 保存结果仍为 4/4 |
| V1 既有 node id | V1 94/94、V2-1C 119/119 均保留 |

一次首次定向运行曾为 15/16：非法单位已被底层 Domain Pack 正确拒绝，但异常类型没有包装成公开的 `ProductPackValidationError`。修复只增加脱敏异常边界，随后相关矩阵 6/6 通过；再增加许可越权和 V1 source id 碰撞门后，最终定向全量 20/20 通过。首次失败没有改写成首次全通过。

最终 `smartbuy/tests` 为 174/174；加入同一条上游配置脱敏 node 后，CI 等价套件为 175/175，另有 3 条既有依赖弃用警告。Ruff、Compileall、JavaScript 12/12、PowerShell AST 5/5、Markdown 相对链接 260/260 和 `git diff --check` 均通过；本轮变更敏感凭据命中 0、禁止运行产物 0、冻结/保护路径修改 0。全仓扫描仍识别 2 个 V1 既有的假凭据/示例文件，两者与 HEAD 完全一致且未输出正文。

历史阶段 6 的 92/120、阶段 7 的 34/40 与首次失败文件没有重新运行或覆盖。V1 目录、冻结结果与旧业务规则未修改；当前新增总测试数不能反向改写 V1 的历史 95 项口径。

## 9. 已知限制与 V2-3 前置条件

1. Product Pack 当前只允许 `domain_id=monitor`，证明的是显示器新增商品无需 Python 型号分支，不代表第二品类已经通用化。
2. 来源 `content_hash` 是治理捕获（ID、URL、访问时间、自制摘要）哈希，不是远端网页原始字节哈希；原文不进入 Git。
3. 真实 Chroma 仍是显式的后续运行步骤；模型、维度、切分或数据版本变化必须创建新 collection，不能复用旧索引。
4. 请求级临时证据不会自动晋升；V2-3 若引入 Source Search，必须保留人工/确定性 Promotion 门和来源许可检查。
5. V1 与 V2 数据模型继续通过 Adapter 并存，本阶段没有删除旧 Schema 或重写 Checker/Evidence 规则。

进入 V2-3 前需要用户单独授权并确认真实搜索 Provider、允许域名、费用上限、缓存与引用边界；在此之前 Web Search 仍保持 unavailable/degraded。Product Pack 开关继续默认关闭，V1 稳定路径不变。

设计决策见 [ADR-0010](../adr/0010-versioned-product-pack-and-evidence-ledger.md)，数据边界见 [Data Card](../data_card.md)。
