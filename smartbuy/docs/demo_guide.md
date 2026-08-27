# SmartBuy 五分钟演示指南

最后更新：2026-08-27

定位：基于真实本地 API 结果的可重复作品集 Demo；单个案例均可在五分钟内完成。
前置条件：先按根目录 [README](../../README.md) 执行 `preflight.ps1`、`bootstrap.ps1` 和 `start.ps1`。

> 截图中的结果卡片除 WebUI 首页外均明确标记为“脱敏结果回放”，数据来自 [`stage7_demo_results.json`](../data/processed/stage7_demo_results.json)，不是实时模型调用。现场演示应使用 WebUI 的 SmartBuy 开关或 `/api/smartbuy/chat`。

## Demo 1：单文档事实核验

- 固定输入：`Dell U2723QE 的屏幕尺寸和分辨率是多少？`
- 目标：只走 KB 事实核验，不调用 SQL 或 Web Search；展示型号、字段、来源 URL 与地区。
- 预期轨迹：`KB Search → Evidence Check → 报告`。KB Search 必须出现，`text2sql/web_search` 不应出现。
- 预期结果：返回 U2723QE 对应事实证据；不把未核验的动态价格或库存写成当前事实。
- 实测：通过；13.741 秒；有可访问证据；未调用 SQL/Web。
- 失败备用：确认 Chroma 校验为 60 chunks；若 Reranker 故障，展示向量排序降级并说明 `reranker_degraded=true`。
- 自动证据：`demo-1-fact`，见 [`stage7_demo_results.json`](../data/processed/stage7_demo_results.json)。

## Demo 2：组合筛选与依赖式多跳

- 固定输入：`中国版中找 27 英寸、4K、USB-C 视频且供电不少于 90W 的显示器。`
- 目标：展示需求解析、SQL 候选筛选、分型号 KB 补查、Evidence Check 与最终 Constraint Checker。
- 预期轨迹：`Text2SQL → KB Search（按候选）→ Evidence Check → Constraint Checker → 报告`；KB/Evidence 的父步骤应关联 SQL 候选。
- 预期结果：只推荐 Checker 判定 `eligible=true` 的候选，同时显示被淘汰候选的 failed/unknown/conflict 字段。
- 实测：通过；41.668 秒；三种工具均真实调用；存在依赖父步骤；违规推荐为 0。
- 失败备用：若 KB 不可用，只保留 SQL 候选并标记“文档事实未核验”；Checker 不能确认时 fail closed，不输出购买推荐。
- 自动证据：`demo-2-multihop`；展示字段收敛的定向回归见 [`stage7_demo_presentation_regression.json`](../data/processed/stage7_demo_presentation_regression.json)。
- 截图：[工具轨迹](assets/react-tool-trace.png)、[Constraint Checker](assets/constraint-checker.png)。

## Demo 3：短期会话与长期偏好 Memory

固定流程：

1. 同一会话输入：`预算不超过 3500 元，主要办公，想要 27 英寸 4K 显示器。`
2. 继续输入：`再便宜一点，预算改为 2500 元以内，而且不要 OLED。`
3. 由用户明确确认后，保存 `budget_max_cny=2500`、`display_size_inch=27`、`exclude_oled=true`。
4. 新会话启用长期 Memory，输入：`请按我已确认的偏好筛选 4K 显示器。`
5. 删除该演示用户的偏好并再次查看，结果应为空。

预期结果：第二轮覆盖而非叠加旧预算；新会话只按需召回已确认偏好；删除后不再使用。动态价格、库存和商品事实不进入长期记忆。

- 实测：5 项检查全部通过；三轮 Agent 总耗时 83.903 秒。
- 失败备用：直接调用 `/api/smartbuy/memory/{user_id}` 的查看、关闭与删除端点，展示显式确认门禁；不得手改运行文件伪造结果。
- 自动证据：`demo-3-memory`，另有阶段 6 Memory 5/5 回归。
- 截图：[Memory 回放](assets/memory-demo.png)。

## Demo 4：官方来源冲突时拒答

- 固定输入：`BenQ PD2705U 的官方资料对 USB-C 供电数值是否一致？`
- 目标：展示同一型号 60W/65W 冲突、双方来源、`conflict` 四态和拒答。
- 预期轨迹：`Text2SQL → KB Search → Evidence Check → 报告`。
- 预期结果：同时展示两个值与两个来源；推荐集合为空；`abstained=true`；不能让 Checker 的 passed 覆盖 Evidence conflict。
- 实测：通过；19.947 秒；冲突可见、双方来源可见、没有推荐。
- 失败备用：使用阶段 6 的 `Web Search unavailable` 或 Checker 注入异常案例；前者继续 KB+SQL，后者必须 fail closed。
- 自动证据：`demo-4-conflict` 与 `h6-015` 定向回归。
- 截图：[冲突拒答](assets/conflict-refusal.png)。

## 一键验证与停止

服务已启动后执行以下命令会产生少量百炼费用：

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run --project vendor/youtu-rag python -m smartbuy.scripts.verify_stage7_demos
```

本次真实验证为 4/4，通过 6 次 Agent 调用，`/monitor` 记录估算费用 ¥0.2202436。完成演示后执行：

```powershell
./smartbuy/scripts/stop.ps1
```

脚本只停止 `start.ps1` 在仓库外状态文件中记录的进程；不会按端口误杀其他程序。
