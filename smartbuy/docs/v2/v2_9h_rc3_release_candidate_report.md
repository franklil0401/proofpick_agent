# V2-9H RC3 范围收敛与冻结报告

## 结论

RC3 已按 ADR-0023 收敛为 **Trusted Multi-domain Decision Core + Experimental/Beta Online Research**。Trusted 是默认模式；进入 Online 前 UI 会显示实验能力提示并要求显式确认。本阶段没有创建或运行 Holdout、独立发布评测、Tag、Release、PR，也没有合并 `main`。

生产对象固定为 Commit `ba6606ae249bafc89c18b320935c767a3f756c34` / Tree `84766c5d8840b50a27c612e24379b6dd63736741`。完整冻结合同和 Payload Hash 见 [RC3 Manifest](v2_release_candidate_rc3_manifest.md)。

## 产品范围

| 状态 | 能力 |
|---|---|
| Trusted Mode · Stable | Monitor、Laptop、Headphone；Domain/Product Pack；有界工具编排；Product Query/Text2SQL；KB/Embedding/Reranker；多跳 Evidence；四态判断；Constraint Checker；确定性 Ranker；分层 Memory；主动澄清；单调 Candidate Scope；Windows 本地复现 |
| Online Research · Experimental | 受控 Source Search、静态 Web Extractor、请求级 Open Evidence、失败降级与安全隔离 |

Online 不保证稳定发现目标地区官方页或抓取所有网站，不保证实时价格、库存或全市场覆盖。网页搜索或提取失败时返回 unknown；Open Evidence 不授予 Trusted 资格，也不能进入 Trusted Checker。

## 发布门槛

Trusted Core 的后续独立评测必须同时满足：三品类各至少 80%，硬约束 F1 至少 95%，推荐事实 Evidence 覆盖至少 95%，错误配置/地区推荐、Scope/Checker/Report 越界、unknown 过度声明、澄清绕过以及 Open→Trusted Checker 均为 0。

Online Beta 只把安全边界作为强制门：错误域名/型号/配置/地区进入 usable、snippet→Evidence、Open→Trusted Checker、unknown→已核验、SSRF/白名单外跳转均为 0。实际取证、字段核验与分品类覆盖必须公开，但不再阻断 Trusted Core RC3。

## 不可覆盖历史

| 记录 | 真实结果 | 分类 |
|---|---|---|
| V2-9B | Trusted `64/90`；Online 实际取证 `2/15` | 独立首次，`Needs revision` |
| V2-9D / RC2 | Trusted `72/90`；Online 实际取证 `0/15` | 第二次独立首次，`Needs revision` |
| V2-9C | Trusted `86/90` | 同题 exposed regression |
| V2-9E | Trusted `86/90`；Online `2→5→5/15` | exposed regression |
| V2-9F | Online 实际取证 `6/15`，字段 `11/18` | exposed regression |
| V2-9G | Playwright 保守投影 `7/15`，字段 `15/21` | 有限 PoC，未接入生产、未运行完整回归 |

安全终态 `15/15` 不能代替实际网页取证数字。以上结果、首次失败和评测器事故均原样保留，RC3 不产生新的发布结论。

## 验证结果

- CI 等价 Pytest：`516/516`；V1 原始测试文件：`101/101`。
- Trusted 代表回归：`113/113`；Online 安全边界：`71/71`。
- Ruff、Compileall、JavaScript `13/13`、PowerShell AST `6/6`、Markdown 相对链接 `475/475`、敏感信息和禁止产物检查通过。
- 新短 ASCII 路径 clone、`uv sync --frozen`、preflight `11/11`、bootstrap、三 SQLite/三索引、HTTP 端点、五 Demo 和 stop 端口释放均通过。
- Windows 验证 API 调用 `0`、模型费用 `¥0`；没有重建收费索引。

详细 Windows 证据见 [复现记录](v2_9h_windows_reproduction.md)。这些 Demo 是代码/数据合同与脱敏回放验证，不是新的独立发布评测。

## 变更边界

生产提交仅增加 RC3 状态说明、Trusted 默认提示、Online Experimental 标签和进入 Open 模式前的显式确认；没有改写 Agent、检索、Evidence、Checker、Ranker、Memory、数据、索引或历史评分逻辑。文档提交只保存 Manifest、报告、验证证据与交接。

## 当前决策

RC3 已具备交给独立评测方的技术条件，但**尚未通过新的独立评测，也不是已发布 V2**。下一步只能按 [RC3 Handoff](v2_9h_rc3_handoff.md)由独立评测方在冻结后创建新任务并单次运行。
