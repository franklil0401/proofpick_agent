# V2-6A Laptop 治理数据卡

最后更新：2026-09-02
数据版本：`laptop-governed-2026-09-02-v1`

## 用途与范围

本数据集用于验证 ProofPick 的 Domain/Product Pack 能否承载第二品类。它包含 12 个笔记本精确配置，不代表市场覆盖、实时在售情况或完整选购知识库；V2-6A 不提供笔记本购买推荐。

## 规模

| 项目 | 数量 |
|---|---:|
| 品牌 | 4（Dell、ASUS、HP、Lenovo） |
| 精确配置 / product_id | 12 / 12 |
| 地区标识 | 7（US、CA、CN、IL、GLOBAL、DE、PH） |
| 官方来源 | 12 |
| 字段级 Evidence | 406 |
| 属性字段位 | 540（45 × 12） |
| 已知 / unknown | 358 / 182 |
| 缺失率 | 182/540（33.70%） |
| 价格观察 | 0 |

关键事实定义为商品、品牌、型号、地区、配置、料号、CPU、GPU、内存和存储身份，共 132 个非空事实，证据覆盖 `132/132（100%）`。

## 来源和许可边界

数据来源是品牌公开官方产品页、配置页或产品规格 PDF：Dell `dell.com`、ASUS `asus.com.cn`、HP `hp.com`/`pcb.inc.hp.com`、Lenovo `psref.lenovo.com`。完整 URL、标题、语言、访问时间和内容哈希保存在 Product Pack。

仓库只提交自行整理的结构化事实、自制短摘要和来源元数据，不再分发官方网页/PDF 全文。代码采用 MIT License；数据事实、页面内容和品牌资料的权利仍归各来源方，数据许可不自动继承代码许可证。

来源权限：

- 官方产品、支持与手册：稳定硬件规格、地区和精确配置。
- 专业评测：仅允许续航实测、性能、温度和噪声等观察字段；当前数据集没有此类记录。
- 零售来源：本阶段不能写稳定规格；价格必须单独保存地区和 `observed_at`，当前为 0 条。
- 搜索摘要、用户评论和论坛：不能进入本治理 Evidence Ledger。

## 结构与语义

商品身份由 `product_id + region + configuration_id/part_number` 唯一确定。相同系列的不同配置和不同地区不得合并。字段定义、单位、别名、枚举、操作符、Memory/报告白名单和来源权限位于 `smartbuy/domain_packs/laptop/`。

`null` 表示当前治理资料不足，绝不以 0、False 或常识猜测代替。缺值或缺 Evidence 时 Checker 状态为 unknown；Pack 缺失、损坏或版本不兼容时 fail closed。动态价格与稳定规格分离。

## 质量与局限

- Product Pack Schema、Domain Pack Manifest/Schema 和来源权限校验通过。
- SQLite `integrity_check=ok`，外键违规 0；两次构建 Manifest 与逻辑数据哈希一致。
- 每个非空 Checker 字段都有字段级 Evidence。
- 数据特意保留 33.70% unknown，主要集中在价格、接口、尺寸、电池和实测指标；不能据此判定满足相关约束。
- 官方配置页可能更新；`source_version` 和访问时间用于复核，不表示页面永久不变。
- `GLOBAL` 只表示来源未提供更窄的市场标识，不能当作任意地区版本。

冻结评测集为 `smartbuy/eval/v2_6a_laptop_cases.jsonl`，SHA-256 `3dfcc0f442bda2b6b4d2e96814a8973b415b3d8c8b9b33235924982fa1758d34`；首次正式评测前不得修改金标。
