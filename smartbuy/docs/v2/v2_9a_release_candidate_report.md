# V2-9A Release Candidate 报告

## 阶段结论

V2-9A 完成统一三品类产品首页、Trusted/Open 可视化、五个可重复 Demo、仓库外 Windows 启停与干净克隆验证，并准备 RC Manifest。该结论只说明作品集级 RC 可交给独立 Agent 评测；本轮没有创建 90 条最终集、没有运行最终 Holdout、没有 PR/main 合并/Tag/Release。

## 产品 UI

- 根页面为 ProofPick 产品首页；Youtu-RAG 经典页保留为 `/classic.html#/chat`。
- 首屏可切换 Monitor、Laptop、Headphone，选择 Trusted/Open、在线/回放和固定 Demo，并显示数据/索引版本。
- 结果展示 intent、硬/软约束、澄清、输入/Memory 来源、完整候选池、Checker、淘汰原因、Ranker 维度/权重/贡献、Evidence、地区/配置/时间、冲突与降级。
- 工具轨迹按 Router、Constraint、Scope、Product Query、KB/Reranker、Source/Extractor、Evidence、Checker、Ranker、Memory、Report 分类，仅含脱敏参数和结果摘要，不含隐藏思维链。
- Memory 按浏览器匿名 ID 隔离；无可靠身份默认关闭，支持 Global/Category 的确认、修改、删除、关闭和开启。价格、事实、Open Evidence 与 pending Proposal 不写入。
- Open 在线研究继续通过独立有界脚本；UI 不会静默触发公网或把失败伪装为回放。

桌面视觉检查覆盖 1440×1200 的 Trusted/Open 页面；无明显横向溢出、遮挡或不可点击控件。架构图通过 Archify showcase 9/9 校验，并在 1440×900、1600×1000、1920×1080、2048×1320 的明暗主题检查中无容器越界。

## 五个 Demo

`verify_v2_9a_demos` 以 0 次 API 调用验证 5/5：

1. Trusted Headphone 筛选绑定已保存的真实回归：推荐与淘汰、Checker 和 Ranker 贡献齐全。
2. AirPods Max 2 Open Research 绑定已保存的真实智谱搜索/Apple IE 抽取结果：5 个字段，`trusted_eligible=false`，Checker 0。
3. 动态价格读取治理观察并执行 TTL/hash/currency/URL 校验；因过期返回 unknown。
4. PD2705U 60W/65W 双边冲突从 180 条 Evidence 中现场复核，Checker fail closed。
5. Laptop Memory 现场执行确认、32→64 覆盖、便携场景与删除，删除后召回为空。

完整输入、在线方法、回放 URL 和失败备用步骤见 [Demo Guide](v2_demo_guide.md)。

## 动态事实边界

Demo 3 不是实时价格服务。只接受 HTTP(S)、目标商品/地区、CNY、有效时间、TTL 和内容 SHA-256 完整的观察；不跨币种换算，不保存网页摘要为事实，不写长期 Memory/稳定规格，不进入 Trusted Checker。观察超过 24 小时后价格和库存字段会清空为 unknown。

## Windows 与成本

[干净克隆报告](v2_9a_windows_reproduction.md)记录了新的 `C:\ppv2rc`、冻结依赖、三份 SQLite、三个 1024 维索引、HTTP 200、五 Demo、回放和端口释放。首次构建可精确计量的 Embedding 成本为 ¥0.015586；另有两次最小 Trusted 查询（2 Embedding + 2 Reranker），保守阶段新增总成本低于 ¥0.03，远低于 ¥5 上限。未调用 qwen-plus、Source Search 或 Open Research 新请求。

## 历史与能力边界

- `main`、`origin/main` 与 `v1.0.0-portfolio` 保持 V1；V1 数据、40 条冻结任务、首次失败与阶段 3–7 指标未改写。
- Monitor 公开在线路径仍通过 V1 兼容适配，Laptop/Headphone 通过显式 V2 runtime；三个 Domain Pack 复用通用契约和安全不变量，但不宣称所有历史路径已重写。
- Headphone 30/30 和 Laptop 116/122 属于 exposed engineering regression，不作为发布泛化指标。
- LangGraph 仍需显式开启且是兼容外壳；默认 ReAct 未切换。
- 数据规模为每品类 12 个当前 UI 可查询配置；Open Research、地区网页、价格/库存与本地 SQLite Checkpoint 均有已知限制。

## 质量门与 RC 冻结

最终测试、静态检查、链接、安全、禁止产物、Git refs 和端口结果在同一阶段收尾后固化到 [RC Manifest](v2_release_candidate_manifest.md)。Manifest 中 `production_commit` 指向冻结前最后一个业务/脚本 Commit；Manifest Commit 之后不得静默修改生产代码。任何修复都必须生成新的 RC 编号与哈希。

## V2-9B 交接

独立评测 Agent 必须先读取 [RC Manifest](v2_release_candidate_manifest.md)、[Demo Guide](v2_demo_guide.md)、[Windows 报告](v2_9a_windows_reproduction.md)、[V2-8 三品类验证](v2_8_three_domain_evaluation.md)与[开发流程](V2_DEVELOPMENT_PROCESS.md)。它应在冻结 Commit 上独立创建和哈希最终任务，区分首次 Holdout、exposed regression 与工程不变量；不得由本开发 Agent 继续出题并调参。
