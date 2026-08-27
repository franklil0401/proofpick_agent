# 阶段 7：演示与发布整理报告

最后更新：2026-08-27

发布定位：**基于 Agentic RAG 的多源显示器消费决策 Agent；可复现的作品集/MVP 原型**。

历史基线：阶段 6 Commit `5fcb05fa5e9fda7a2b9d7b1c4c9df507301081af`。

## 1. 结论先行

阶段 7 使用阶段 6 冻结的 40 条自然任务，只运行最终增强组 D。首次发布候选为 **34/40（85.0%）**：regression **16/16**，holdout **18/24**。字段级硬约束判断 **183/183**，违规候选推荐 **0/56**，`s4-004/s4-007/s4-012/s4-014` 与 `h6-007` 分辨率比较均通过。

该结果不替换阶段 6 的首次 31/40 或三次聚合 92/120。首次发布候选仍有 6 条 holdout 未完成，unknown/conflict 只有 2/5；因此发布状态保持“实验性作品集/MVP 原型”，不是生产 SLA。

输出层随后定向修复了动态信息 unknown、60W/65W 冲突被 Checker 覆盖、含糊尺寸提示和无关字段堆叠。修复后只运行对应回归，不重跑 40 条美化主结果。

## 2. 发布候选配置与结果

- 自然集：40 条（regression 16 + holdout 24），SHA-256 `6082ac83d72441fedf7ac3083a3c53f31d538ca54216f2cf99d3a9de5068e0ef`。
- 配置哈希：`c5001c9707c5cb7302c26745407cf989676e832b6984109604dec829754ab096`。
- 数据/索引：`monitor-cn-2026-08-26-v1` / `monitor-fact-card-h2-v1`。
- 模型：`qwen-plus`、`text-embedding-v4` 1024 维、`qwen3-rerank`。
- 公平条件：temperature 0、max output 800、as_of `2026-08-27T00:00:00Z`、cold/no-cache、无真实 Web Search。
- 结果文件：[`stage7_release_candidate_results.json`](../data/processed/stage7_release_candidate_results.json)；统一账本见同目录 ledger。

| 指标 | 首次发布候选 |
|---|---:|
| E2E | 34/40 |
| regression / holdout | 16/16 / 18/24 |
| 正确候选召回 | 37/41 |
| 推荐候选精度 | 37/57 |
| 字段级硬约束 | 183/183 |
| 任务级硬约束 | 28/30 |
| 违规候选推荐 | 0/56 |
| unknown/conflict | 2/5 |
| unsupported 识别 | 3/3 |
| 工具选择 | 36/40 |
| 依赖式多跳 / 工具顺序 | 23/23 / 23/23 |
| 越权或越序拦截 | 58/58 |
| 平均 / P50 / P95 | 27.413s / 28.485s / 46.085s |
| Token / 估算成本 | 1,733,476 input + 42,874 output / ¥1.4525602 |

首次失败：`h6-001`、`h6-002`、`h6-015`、`h6-016`、`h6-017`、`h6-020`。其中 `h6-015` 是确定性安全门与 Evidence conflict 的展示合并错误；其余体现单事实路由、跨地区比较、未支持偏好和候选集合边界。

## 3. 定向修复与审计

- `s4-011`：动态价格/库存缺失明确为 unknown，1/1，¥0.0147804。
- `h6-015`：60W/65W 同时显示，双方来源保留，推荐为空，1/1，¥0.0243322。
- `h6-018`：模糊“27 英寸左右”显示 unsupported/unknown，不静默成为硬约束，1/1，¥0.0125480。
- 筛选报告收敛：仅展示用户原话概念与 provenance-gated 约束，复杂筛选与 Memory 两例 2/2，¥0.1332785。
- 单元测试覆盖：Evidence conflict 不得被 passed Checker 覆盖；缺失动态字段显式 unknown；证据按用户字段/型号收敛；内部排序字段不进入公开报告。

审计说明：第一次定向命令误复用了阶段 6 默认 checkpoint，没有发生新调用；识别后丢弃该无效输出，使用独立 Stage 7 checkpoint 重新运行。无效输出未计入结果或费用。首次发布候选文件未覆盖。

阶段 7 可审计在线估算费用当前合计 **¥1.8577429**，包括 40 条发布候选、三条定向修复、首次 4 Demo 验证和两条展示回归，低于 ¥5 上限。

## 4. 四个真实 Demo

固定输入、轨迹、预期、备用步骤和截图见 [Demo 指南](demo_guide.md)。首次本地 API 验证 **4/4**，6 次 Agent 调用成本 ¥0.2202436；复杂筛选与 Memory 展示收敛另行定向回归 2/2。

| Demo | 结果 | 实测耗时 |
|---|---:|---:|
| 单文档事实核验 | 通过 | 13.741s |
| 组合筛选与多跳 | 通过 | 41.668s |
| 会话与长期 Memory | 5/5 检查通过 | 83.903s（三轮总计） |
| 60W/65W 冲突拒答 | 4/4 检查通过 | 19.947s |

## 5. 前端与演示材料

- 实际 WebUI 首页：[webui-home.png](assets/webui-home.png)。
- 脱敏真实结果回放：[工具轨迹](assets/react-tool-trace.png)、[Checker](assets/constraint-checker.png)、[Memory](assets/memory-demo.png)、[冲突拒答](assets/conflict-refusal.png)。
- 回放源文件：[demo_replay.html](assets/demo_replay.html)，页面显式说明“不是实时调用”。
- WebUI 结构化候选卡展示硬/软约束、工具状态、父步骤、SQL 摘要、证据、Checker 四态、价格观察时间、Memory、降级和停止原因；DOM 使用 `textContent`，不渲染隐藏 Prompt、密钥、私人路径或调试堆栈。

## 6. Windows 发布脚本

- `preflight.ps1`：检查 Windows、Python 3.12、uv、Git、vendor、MinIO、四个环境变量与仓库外运行目录；变量只输出 configured/missing。
- `bootstrap.ps1`：`uv sync --frozen`、治理数据校验、SQLite 幂等重建、Chroma 校验或重建。
- `start.ps1`：仅绑定回环地址，启动 MinIO/FastAPI，验证 `/health`、WebUI、`/monitor`，状态文件只保存 PID。
- `stop.ps1`：只递归停止状态文件记录的进程树，不按端口误杀其他进程。

当前开发仓库实测：`uv sync --frozen` 成功；数据为 12/4/16/180；SQLite `integrity=ok`、外键 0；Chroma 60 chunks；三页面 HTTP 200；停止后 8000/9000/9001 均未监听。

## 7. 干净 Windows 复现

待从阶段 7 本地提交创建全新短 ASCII 路径 clone 后补充。此处不会用当前开发目录冒充干净复现。

## 8. 数据、许可与安全边界

- 12 份事实卡为自制总结；16 个来源记录 URL、访问时间与再分发边界；4 条价格均含 `observed_at`。
- 原始 PDF、网页全文、Cookie、运行 SQLite、Chroma、MinIO、缓存、日志和真实 `.env` 不进入 Git。
- 本项目代码 MIT；Youtu-RAG 固定 subtree 保留上游 MIT 与第三方说明。
- Web Search 只有 unavailable/degraded 接口；价格不实时；GraphRAG、Neo4j、第二品类、公网多租户与生产 SLA 未实现。

## 9. 尚待最终提交前完成

- 全新短 ASCII 路径 clone、bootstrap、服务、4 Demo 核心步骤与 stop 复现。
- 完整自动化、Ruff、compileall、JavaScript、PowerShell、文档链接、禁止文件和敏感历史扫描。
- 同步 README、开发指南、结构、Runtime Manifest，记录最终 Commit 和 origin/main 状态。
