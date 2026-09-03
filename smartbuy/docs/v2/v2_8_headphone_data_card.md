# V2-8 Headphone 治理数据卡

## 范围与版本

| 项目 | 值 |
|---|---|
| Domain Pack | `headphone` / `1.0.0` |
| Data Version | `headphone-governed-2026-09-03-v1` |
| Product Pack | `headphone-governed-v1` / `1.0.0` |
| 产品 / 品牌 / 地区 | 12 / 4 / US、CA |
| 来源 | 20：official 12、measurement 4、subjective 4 |
| Evidence | 336：official 316、measurement 8、subjective 12 |
| 字段 / Checker 字段 | 38 / 30 |

12 个精确配置覆盖 Sony、Bose、SteelSeries、Logitech，包含真无线、头戴式和游戏耳机。Sony WH-1000XM5 区分 US/CA；SteelSeries Arctis Nova Pro Wireless 区分 PlayStation/Xbox 配置。不同代际、地区和连接配置不合并。

## 来源与权限

- `official_spec`：公开无需登录的官方产品/支持页；只提交 URL、访问时间、内容哈希、自制短摘要和字段事实。
- `professional_measurement`：记录测试机构、方法 URL、测试时间、地区及可得的固件信息；只支持授权的实测字段。
- `subjective_review`：只支持 `comfort_observation`、`sound_signature`、`call_quality_observation`，不能进入 Checker 或覆盖官方事实。
- 未提交网页全文、付费内容、Cookie、用户评论集合或运行缓存。数据许可不自动沿用代码 MIT License。

## 完整性与缺失

- 408 个属性槽位中 120 个为 `null`，缺失率 `120/408 = 29.41%`；没有以 0 替代未知。
- 299 个非空 Checker 事实全部绑定 Evidence，覆盖 `299/299`。
- 当前没有价格观察；所有预算约束为 `unknown`，不能判定预算内。
- SQLite `integrity_check=ok`，外键违规 0。

## 可复现性

两次独立仓库外构建结果一致：

- Manifest SHA-256：`36c0bf08ce945a67e7ecd0e485a9a269e7ad942788d428f2cb8af925208e8018`
- Logical data SHA-256：`c1edf981e00f6ad15b409d1d4ea37b2c8e2dc6dd36b95ce4be99ac57693fc40a`
- Vector document SHA-256：`b17cdf6175b64077e5e19cc50e441612f21e9edcd4dcdd3c0954c4256c13b783`
- 生成物：12 份事实卡、12 份向量文档、EAV SQLite、Source/Evidence JSONL 与 Manifest。

构建命令与运行边界见 [V2-8 运行说明](v2_8_headphone_runtime.md)。
