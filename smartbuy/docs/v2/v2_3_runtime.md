# V2-3 Source Search 运行说明

最后更新：2026-09-01

适用分支：`feature/proofpick-v2`

默认状态：关闭；V1 `web_search` unavailable 占位工具仍保留

## 配置

程序只从当前进程继承的环境变量读取配置：

- `PROOFPICK_SOURCE_SEARCH_ENABLED=true`：显式把 `source_search` 加入 Agent 工具白名单。
- `ZhiPu_api_key`：智谱 Web Search 凭据。只报告 `configured/missing`，禁止打印值。

PowerShell 可用以下方式只检查状态：

```powershell
if ([string]::IsNullOrWhiteSpace($env:ZhiPu_api_key)) { "missing" } else { "configured" }
$env:PROOFPICK_SOURCE_SEARCH_ENABLED = "true"
```

关闭开关或移除当前进程开关后，重新启动服务即可无数据迁移地恢复原有 V1 工具集合。不得把真实 Key 写入 `.env`、命令历史、日志或仓库文件。

## 行为

1. Agent 只能显式选择 `source_search`；缺少本地证据作为触发理由时，必须先执行本地 KB/Evidence 检查。
2. 本地目标字段已被证据覆盖时，工具返回 `LOCAL_EVIDENCE_SUFFICIENT` 且不联网。
3. `search_pro` 没有目标地区候选时才执行 `search_pro_sogou`。
4. 返回结果分成 `usable_candidates`、`navigation_candidates` 和 `rejected_candidates`。只有 `region_matched` 能进入第一组。
5. V2-3 不下载网页、不保存摘要正文、不生成 Evidence、不调用 Checker，也不宣称核验了页面中的规格。
6. Monitor/SSE 只展示 Provider、状态、计数、缓存、降级、费用和错误类别；不展示 Key、查询正文、URL 列表或 request ID。

## 有界参数

| 项目 | 默认值 |
|---|---:|
| 请求 `count` | 10（Provider 可能忽略） |
| 原始元数据扫描 | 最多 50 条 |
| 可用 / 导航候选 | 各最多 10 条 |
| 每请求网络调用 | 最多 4 次（含重试） |
| 每个 Agent 任务的 Source Search 工具调用 | 最多 2 次 |
| 单引擎重试 | 最多 1 次 |
| HTTP / 总超时 | 10 / 20 秒 |
| RPS | 5 |
| 单请求费用门 | ¥0.20 |
| TTL / 容量 | 900 秒 / 256 项 |

401/403 不重试；429、5xx、超时有限退避。错误、空结果和不完整结果不会写入正常缓存。

## 验证

离线、零费用测试：

```powershell
uv run --project vendor/youtu-rag --group dev python -m pytest smartbuy/tests/unit/test_v2_source_search.py smartbuy/tests/integration/test_v2_source_search_agent.py -q
```

8 条真实官方来源覆盖测试（会产生费用，执行前确认预算）：

```powershell
uv run --project vendor/youtu-rag python -m smartbuy.scripts.verify_v2_source_search
```

脚本只输出 URL 元数据、状态、计数、延迟和估算费用；不输出 Key 或网页正文。搜索结果具有概率性，必须保留首次结果，不得通过放宽地区规则或反复调用包装覆盖率。

## 当前边界

- 固定 8 条任务最终为 6 条 `success`、2 条 `no_region_matched_source`；这不是搜索准确率 100%。
- `navigation_candidates` 只解释“找到其他/未知地区页面”，不能支持任何商品事实。
- V2-4 的 canonical、hreflang、地区跳转、正文抽取、字段核验与 Evidence Promotion 均未实现。
- 搜索失败不会影响本地可信推荐；数据库外型号在 V2-3 只能获得来源导航，不能形成购买推荐。

决策见 [ADR-0011](../adr/0011-auditable-zhipu-source-search.md)，实测证据见 [V2-3 报告](v2_3_source_search_report.md)。
