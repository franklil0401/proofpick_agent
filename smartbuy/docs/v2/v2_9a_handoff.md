# V2-9A 发布、回滚与独立评测交接

## PR 草案（本轮不创建）

**标题：** `feat(v2): prepare multi-domain ProofPick release candidate`

**摘要：**

- 新增 Monitor/Laptop/Headphone 统一产品 UI 与五个固定脱敏 Demo。
- 展示 Trusted/Open 隔离、完整候选池、Checker、Ranker、Evidence、Memory 和公开工具轨迹。
- 增加仓库外三品类 Windows bootstrap、完整服务与无 Key Offline Replay。
- 在新短 ASCII 路径完成 clone、冻结依赖、索引、HTTP、Demo 和 stop 验证。
- 保留 V1 `main`/Tag/历史结果；未运行 V2 最终独立评测，未宣称生产 SLA。

**审阅重点：** RC Manifest Hash、全量测试、三索引 1024 维、Open Evidence 进入 Trusted Checker 为 0、动态事实 unknown 路径、敏感扫描与禁止产物检查。

## V1 / V2 能力边界

- V1：`main` + `v1.0.0-portfolio`，显示器稳定作品集、V1 四组评测与经典 WebUI。
- V2：仅 `feature/proofpick-v2`，三 Domain Pack、Product Pack/Evidence Ledger、自然约束/澄清、Laptop/Headphone、Open Research、确定性 Ranker、分层 Memory 和统一产品 UI。
- 不变安全门：治理 Evidence、完整候选池、Checker fail closed、Open/Trusted 隔离、无 Key/Prompt/隐藏思维链输出。
- 尚未承诺：生产 SLA、全市场覆盖、实时价格、动态图形编排生产迁移或公网多租户。

## 回滚

1. 公开稳定版始终可回到 `main` 或 `v1.0.0-portfolio`，不移动 Tag。
2. V2 在线能力由 `PROOFPICK_DOMAIN_AGENT_ENABLED` 显式开启；关闭后不迁移或删除 V1 数据。
3. Product Pack/Data/Index 使用版本化外部指针；版本校验失败时 fail closed，不切换未完成资产。
4. UI 仍可用 `classic.html#/chat` 访问固定上游界面；无服务时可运行只读 Offline Replay。
5. RC 冻结后如果生产文件变化，创建新 RC Manifest，不覆盖本次 Hash 或首次评测。

## Release Notes 草案

正式草案见 [`../release/v2_portfolio_release_notes_draft.md`](../release/v2_portfolio_release_notes_draft.md)。本轮不创建 PR、Tag、GitHub Release，也不修改默认分支。

## 独立评测约束

- 以 RC Manifest 的 Commit、lock、数据、索引、Prompt、工具、Checker、Ranker 与 Memory 哈希为唯一输入。
- 在首次运行前冻结新任务、Schema、评分器、分母和 SHA-256。
- 首次失败不可删除、覆盖或回跑成“首次通过”；修复只能进入新 RC。
- 不把历史 30/30、116/122 或五 Demo 5/5 当作独立泛化指标。
- 最终报告必须同时给出准确性、安全门、Evidence 覆盖、延迟、Token/费用、降级和跨品类污染。
