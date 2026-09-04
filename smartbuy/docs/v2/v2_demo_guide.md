# ProofPick V2 五分钟 Demo

## 使用边界

产品首页提供五个固定场景。离线页面始终显示“这是固定的脱敏结果回放，不是实时模型调用。”；回放数据来自已保存的公开测试结果或当前治理数据，不包含 Prompt、凭据、私人路径和隐藏思维链。在线失败会显示 `online_unavailable`，不会偷偷切换或伪装成功。

```powershell
# 零 API 验证五个 Demo 背后的数据/代码合同
uv run --project vendor/youtu-rag python -m smartbuy.scripts.verify_v2_9a_demos

# 无 Key、MinIO 时启动脱敏回放
.\smartbuy\scripts\replay.ps1 -Port 8088 -ServiceRuntimeRoot C:\ppv2run\replay
```

访问 `http://127.0.0.1:8088/app.html`。在线 Trusted 模式需先按 [Windows 复现说明](v2_9a_windows_reproduction.md)启动完整服务；Open Research 使用下表中的显式有界脚本，不从 UI 静默调用公网。

## 五个场景

| Demo | 固定输入与路径 | 预期结果 | 真实运行 / 回放与备用 |
|---|---|---|---|
| 1 本地可信筛选 | “需要主动降噪、重量不超过 250 克的通勤耳机。”；Product Query → KB/Reranker → Evidence → Checker → Ranker | Sony WH-1000XM5 进入推荐；339g 的 SteelSeries 被淘汰；显示得分贡献和 Evidence | 完整服务中选 Headphone/Trusted 后在线运行；回放 `?demo=trusted-headphone-filter`。在线不可用时保留 `online_unavailable` 并切回回放 |
| 2 数据库外开放研究 | “研究治理库外 AirPods Max 2 爱尔兰官方页面的形态、降噪、通透、空间音频和续航。”；Source Search → Extractor → Temporary Evidence → Open Report | 5 个字段来自已保存的真实 Apple IE 页面验证；`trusted_eligible=false`，进入 Checker 为 0 | 显式运行 `python -m smartbuy.scripts.verify_v2_8_headphone_open_research`（会调用智谱搜索）；回放 `?demo=open-airpods-max`。搜索/页面失败时只输出 degraded/unknown |
| 3 动态价格观察 | 检查 Dell U2724D 的一条中国区离线价格观察 | 展示 URL、CNY、`observed_at`、24h TTL 和内容哈希；当前已过期，因此价格/库存为 unknown | `verify_v2_9a_demos --demo dynamic-price-expired`；回放 `?demo=dynamic-price-expired`。不跨币种、不写 Memory/稳定规格、不进入 Trusted Checker |
| 4 冲突与 fail closed | “PD2705U 美国版 USB-C 供电到底是 60W 还是 65W？” | 两个官方来源和两条 Evidence 均保留，字段为 conflict，Checker 阻断，LLM 不能覆盖 | `verify_v2_9a_demos --demo conflict-fail-closed`；回放 `?demo=conflict-fail-closed`。来源缺失时输出 unknown，不挑一个好看的值 |
| 5 连续追问与 Memory | 32GB → 覆盖为 64GB → 便携 What-if → 明确保存 → 删除 | 当前输入覆盖旧条件；What-if 只改变排序、不改变 Checker 集合；删除后不再召回 | `verify_v2_9a_demos --demo memory-follow-up`；回放 `?demo=memory-follow-up`。无可靠身份时长期 Memory 默认关闭 |

## 展示顺序

1. 用 Demo 1 说明“完整候选池先由结构化查询产生，LLM 不负责资格”。
2. 展开工具轨迹与 Evidence，说明页面只展示公开输入/输出摘要，不展示隐藏思维链。
3. 切到 Demo 2，强调 Open Evidence 与治理证据隔离。
4. 用 Demo 4 展示冲突双方与 fail closed。
5. 用 Demo 5 打开 Memory 抽屉，演示 Global/Category、确认、覆盖、删除和关闭。

## 截图

- [Trusted 结果](../assets/proofpick-v2-trusted.png)
- [Open Research 结果](../assets/proofpick-v2-open.png)
- [统一架构可交互版](../assets/proofpick-v2-architecture.html)

截图均由本地离线回放生成并经过人工检查；不含账号、Workspace、Windows 用户名、绝对私人路径、Cookie、Token 或密钥。
