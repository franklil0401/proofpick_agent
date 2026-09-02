# V2-4 Open Research 运行说明

最后更新：2026-09-02

状态：已实现，默认关闭；不改变 Trusted/V1 默认路径

## 开关与运行目录

Open Research 需要同时显式启用来源搜索和网页抽取：

```powershell
$env:PROOFPICK_SOURCE_SEARCH_ENABLED = "true"
$env:PROOFPICK_OPEN_RESEARCH_ENABLED = "true"
$env:PROOFPICK_OPEN_EVIDENCE_ROOT = "C:\ai\proofpick-v2\open-evidence"
```

还需在启动进程继承的系统环境中配置 `ZhiPu_api_key`。程序只报告 `configured/missing`，不得打印变量值。`PROOFPICK_OPEN_EVIDENCE_ROOT` 必须位于 Git 仓库外；默认是 `C:\ai\proofpick-v2\open-evidence`。

API 请求通过 `mode` 选择模式：

- `trusted`：默认，只使用已发布 Product Pack/正式 Evidence Ledger，维持 V1 Checker 和 eligible 语义。
- `open`：允许对本轮 Source Search 候选做正文抽取，输出 provisional 研究报告，永远不进入 Trusted 推荐集合。

关闭任一联网开关后无需迁移数据即可回到本地 KB + SQL 可信路径。

## 临时证据生命周期

- 默认 TTL：24 小时。
- 隔离：user/session/thread/request 均先转为不透明 SHA-256 token；Windows 路径使用 token 前缀分层，文件内保留完整 token 并在读取时再次校验。
- 写入：同一请求的记录组成版本化 envelope，经临时文件和 `os.replace` 原子落盘。
- 查看：`TemporaryEvidenceStore.read(...)`；过期、损坏、作用域不符分别返回安全状态，不回传未校验记录。
- 删除：`delete(...)`；过期清理：`cleanup_expired(...)`；全部关闭：初始化 `enabled=False` 或关闭 Open Research 开关。
- 晋升：`promotion_candidate(...)` 只生成 `review_required/auto_publish=false` 的审查清单，不发布数据。

不得把临时目录放入仓库，不得把其内容写入长期 Memory、SQLite、事实卡或 Chroma。

## 有界真实验证

```powershell
uv run --project vendor/youtu-rag python -m smartbuy.scripts.verify_v2_open_research `
  --runtime-root C:\ai\proofpick-v2\open-research-live `
  --output C:\ai\proofpick-v2\open-research-live\result.json
```

命令只打印/保存脱敏计数、状态、字段名、内容哈希和估算搜索费用，不保存完整 HTML，也不调用 qwen-plus。输出和临时证据必须在仓库外。

最终实测口径：`PD3226G/US` 完整链路成功；`P2725QE/CN` 页面字段冲突被保留；LG 中国版与 BenQ 加拿大版的地区恢复失败后明确降级。当前阶段所有已知 Source Search 调用合计估算 ¥1.08，LLM 调用 0。

## 安全与降级

- 只访问本轮 Source Search 返回、且通过官方域名/型号/地区状态门的 URL。
- `httpx` 禁止继承系统代理，连接/读取/总时间分别有上限；重定向每跳复核，最多 3 次。
- 只接受 HTML/XHTML，解压后最多 5 MiB；完整页面不写磁盘。
- 静态正文不足返回 `dynamic_render_required` 或 `extraction_incomplete`，目标字段保持 unknown。
- 错地区 canonical/hreflang 只能作为导航候选；没有成功抓取目标地区正文前不能生成 Evidence。
- Open Evidence 到 Trusted Checker 的转换入口会抛出异常；Open Report 固定没有推荐商品。

## 地区证据语义

- 目标地区只有错误地区正文时返回 `unknown`、`reason=region_mismatch_only`，错误地区记录仅作为跨地区参考。
- 目标地区与其他地区字段值不同，`cross_region_conflict=true` 并保留双方 Evidence ID；其他地区值不能覆盖目标地区事实。
- 两个地区值相同不会自动标记 conflict；但缺少目标地区证据时仍不能把其他地区值判为 matched。
- 报告分别输出 `target_region_status` 和 `cross_region_conflict`。V1 Schema、Trusted Checker 与默认关闭行为不变。

技术决策见 [ADR-0012](../adr/0012-governed-web-extraction-and-open-evidence.md)与[ADR-0013](../adr/0013-regional-evidence-comparability.md)，完整证据见 [V2-4 报告](v2_4_open_research_report.md)和[V2-4C 收尾报告](v2_4c_regional_evidence_report.md)。
