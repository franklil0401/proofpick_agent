# ProofPick / SmartBuy 显示器场景数据卡（v1）

- 数据版本：`monitor-cn-2026-08-26-v1`
- Schema 版本：`1.0.0`
- 生成日期：2026-08-26
- 场景：中国大陆显示器选购的检索与数据质量验证
- 许可边界：代码采用 MIT License；数据和第三方来源不自动继承代码许可证

## 数据集结论

当前版本包含 12 个显示器型号、4 个品牌、16 份公开资料、4 条追加式价格观察、180 条字段级证据和 12 份自制事实卡。它足以建立第一版检索基线，但不是完整商品库，也不能代表实时价格、库存或全部地区版本。

## 范围与粒度

`products` 的粒度是“型号 + 地区/版本”，不同地区不会只因型号名相同而合并。数据覆盖 Dell、ASUS、LG 和 BenQ，特意保留以下差异：

- 26.5/27 英寸、QHD/4K/5K、60/120/144/165/240Hz；
- IPS、IPS Black、Fast IPS、OLED/WOLED；
- 无 USB-C、有 USB-C 但无视频、USB-C 视频输入，以及 15/65/90/96W 的不同供电语义；
- 中国、美国和加拿大版本标签；
- 在售、缺货、停售和价格未知；
- 官方内部 60W/65W 冲突，以及零售标题与官方接口规格冲突。

## 来源与采集方式

来源优先使用官方手册、支持入口和产品规格页；另保留 1 个公开零售页面作为低置信冲突样本。所有页面均为无需登录的公开 URL，不绕过验证码、付费墙或访问限制，不采集用户评论、Cookie、Token 或个人信息。

公开仓库只提交：

- 来源 URL、标题、地区、访问时间和治理摘要；
- 自行整理的结构化事实、字段级证据和自制 Markdown 事实卡；
- 可重复生成数据的脚本与哈希。

不提交网页/PDF 全文、页面快照、大量评论或运行缓存。`source_records.content_hash` 是“来源 URL + 访问时间 + 自制治理摘要”的 SHA-256，不声称是会变化的远端响应字节哈希；事实卡文件另有独立 SHA-256。

## Schema 与规范化

四个核心实体是 `products`、`price_observations`、`source_records` 和 `evidence_records`。单位固定为 inch、Hz、W、mm、kg 和 CNY；布尔值只允许 `true/false/null`；未知值使用 `null` 而不是 0。价格观察只能追加并必须保留 `observed_at`、地区、卖家、库存状态和 URL。

每个已知产品事实都映射到 `source_id` 和确定性的 `evidence_id`。`normalized_value` 保留机器可用类型，`original_value` 保留带单位的人类可读表达。来源冲突使用 `conflict_group` 并列保存，不静默覆盖。

## 已知缺失与质量边界

自动校验没有发现阻断错误，核心检索字段缺失率为 0%。非核心缺失仍真实保留：

| 字段 | 缺失数 / 12 | 说明 |
|---|---:|---|
| `release_date` | 12 | 本阶段没有足够稳定的发布日期证据 |
| `warranty` | 6 | 不跨地区推断保修 |
| `weight_kg` | 4 | 不能确认净重/含支架口径时留空 |
| `width_mm` | 1 | 未核验时留空 |
| `usb_c_power_delivery_w` | 4 | 这些型号明确无 USB-C，W 值使用 `null`，不是 0 |

价格只有 4 条且均为一次观察，不能用于实时购买决策。美国/加拿大型号用于地区差异检索，不代表中国可购或中国保修。型号名、端口方向、线材和物理接口必须结合证据解释。

## 质量检查与人工抽查

自动检查覆盖唯一性、URL、类型/单位、布尔三态、价格时间、外键、重复 URL/治理内容、地区边界、生成文件哈希、数据库完整性和幂等性。2026-08-26 人工抽查 3/12 个型号（25%）：

- `dell-u2724d-cn`：确认 15W 下行端口不能解释为 USB-C 视频/笔记本充电；
- `asus-pa27jcv-cn`：确认中国手册为主来源，美国规格只作明确地区的交叉核验；
- `benq-pd2705u-us`：确认 60W/65W 与零售 Thunderbolt 标题冲突没有被静默覆盖。

人工抽查不是第三方审计；后续新增数据应按相同或更高比例复核。

## 可复现构建

```powershell
python -m smartbuy.scripts.build_stage3_data
python -m smartbuy.scripts.validate_stage3_data
python -m smartbuy.db.build_database --output C:\ai\smartbuy-stage3\smartbuy_monitors_v1.sqlite
```

SQLite 是工作区外的运行产物，不进入 Git。连续重建必须保持相同行数、0 外键违规、`integrity=ok` 和相同逻辑哈希。

## 合规与使用建议

第三方网页和手册仍受各自权利人与条款约束；`redistribution_status=metadata_and_summary_only` 表示本仓库只再分发元数据与自制短摘要。任何扩充、商用或重新分发原文的行为都需要重新核验许可。模型或脚本不得用猜测补齐未知值，动态价格必须新增观察而非覆盖历史。

数据决策见 [ADR-0003](adr/0003-governed-monitor-data-and-index.md)，实测质量与检索指标见[阶段 3 报告](stage3_data_and_retrieval_report.md)。

## V2-2 可选 Product Pack 扩展

V1 数据版本、12 个型号和以上质量统计保持冻结不变。V2-2 另提供一个默认关闭的可选数据版本 `monitor-multi-region-2026-08-31-v2`，由 Product Pack 在仓库外构建完整快照：13 个型号、4 个品牌、17 个来源、4 条价格观察、196 条字段证据、13 份自制事实卡和 65 份向量文档。

新增型号为美国版 Dell UltraSharp U2725QE（稳定 ID `dell-u2725qe-us`，配置版 `u2725qe-us-210-bqhr`），来源是 [Dell 美国官方产品页](https://www.dell.com/en-us/shop/u2725qe-monitor/apd/210-bqhr/monitors-monitor-accessories)。仓库仅提交 URL、访问时间、自制短摘要和 16 条结构化字段证据，标记为 `metadata_and_summary_only`，不提交网页原文；发布日期无法核验时保留 `null`。该美国版本不自动映射为中国可购或中国保修。

统一 Evidence Ledger 把 V1 证据经 Adapter 与新 Pack 证据映射到同一字段契约，每条记录绑定 source、snippet、market、variant、source version、observed_at 和再分发状态。请求级临时证据固定为 `temporary/not_reviewed`，不自动进入正式数据。完整版本、许可、幂等和回滚证据见 [V2-2 报告](v2/v2_2_product_pack_report.md)与 [ADR-0010](adr/0010-versioned-product-pack-and-evidence-ledger.md)。
