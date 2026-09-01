# V2-3 受控 Source Search 技术报告

最后更新：2026-09-01

分支：`feature/proofpick-v2`

范围：官方来源 URL 发现；不含网页抽取、Evidence Promotion 或开放研究报告

## 结论

V2-3 已完成默认关闭、可审计的智谱 Source Search：8 条官方来源任务均得到安全处理，其中 6 条找到目标地区官方页面，2 条因缺少目标地区来源而明确降级；错误地区来源误接受为 0。

该结论不是“官方页面覆盖率 8/8”或“搜索准确率 100%”。精确地区覆盖率是 6/8；Source Candidate 进入 Evidence Ledger 和 Constraint Checker 均为 0。

## Provider 只读选型历史

历史结果保持原样，没有因最终实现而覆盖：

| Provider / 组合 | 精确地区覆盖 | 说明 |
|---|---:|---|
| 百炼 | 4/8 | 具备结构化 URL 能力，但官方页覆盖不足 |
| 智谱 | 6/8 | 单 Provider 最佳；预选实验中搜狗回退恢复 3 条 |
| 博查 | 1/8 | `site:` 不是安全边界，且没有增加组合覆盖 |
| 百炼 + 智谱 | 7/8 | 仍缺 1 条 |
| 智谱 + 博查 | 6/8 | 博查无增益 |
| 三 Provider | 7/8 | 增加复杂度后仍不是 8/8 |

因此正式路径只实现 `ZhipuSourceSearchProvider`，保留通用 Provider 接口，不实现三家聚合。决策详见 [ADR-0011](../adr/0011-auditable-zhipu-source-search.md)。

## 实现

- `SourceSearchRequest/Result/Candidate`：严格 Pydantic 契约和显式状态。
- `DeterministicSourceValidator`：HTTP(S)、IDNA hostname、合法子域、完整型号 token 和地区逐层过滤。
- `search_pro → search_pro_sogou`：仅在没有 `region_matched` 时有界回退。
- TTL 缓存：只缓存完整、公开且非失败的 URL 元数据；键包含 Provider/版本/引擎/查询/型号/地区/域名/freshness。
- 账本和事件：记录调用、固定单价估算、延迟、重试、缓存、结果计数和降级，不记录凭据或正文。
- Agent 工具：只有显式特性开关开启时注册；搜索前有本地证据充分性门。
- 隔离：候选固定 `usable_for_evidence=false`、`usable_for_checker=false`，转换尝试抛出异常。

原有 `web_search` unavailable 工具仍保留，用于动态价格/库存的 V1 降级语义；`source_search` 是独立的官方来源发现工具，不能替代动态事实核验。

## 真实 8 条覆盖结果

最终复测复用了原始实验的精确官方站点过滤值。`search_pro` 直接命中 4 条，`search_pro_sogou` 恢复 2 条；共 12 次实际调用，估算 ¥0.44。平均任务延迟 1,780.551 ms；小样本 P95 按最大观测值报告为 4,337.367 ms，不能外推生产 SLA。

| 用例 | 目标地区 | 最终状态 | 命中引擎 |
|---|---|---|---|
| Dell U2723QE | CN | success | search_pro_sogou |
| Dell S2722QC | CN | success | search_pro |
| ASUS PA279CRV | CN | success | search_pro |
| ASUS PG27AQDM | CN | success | search_pro_sogou |
| LG 27UP850K-W | CN | success | search_pro |
| LG 27GS95QE-B | CN | no_region_matched_source | 两引擎均无目标地区页 |
| BenQ PD2705U | US | success | search_pro |
| BenQ PD2725U | CA | no_region_matched_source | 两引擎均无目标地区页 |

6 个成功任务产生 7 条可用 URL；URL、标题、hostname、本地 request ID 和查询时间完整 7/7。错误地区、地区 unknown、错误型号、白名单外域和非法 URL进入 `usable_candidates` 均为 0。

### 首次实现期结果保留

首次脚本误用了根域过滤值而不是原实验的精确 `www` 站点值，真实结果为 4/8 success、2/8 `no_region_matched_source`、2/8 `no_official_source`，14 次调用、估算 ¥0.54。该结果未覆盖；修正的是测试输入一致性，不是地区规则或金标。两次收尾调用合计估算 ¥0.98。

把此前已授权的百炼/智谱/博查只读诊断计入后，已知估算仍低于 V2-3 ¥2 上限；博查控制台实际费用不可从 API 响应获得，因此不虚构精确账单值。

## 状态与安全验收

| 指标 | 结果 |
|---|---:|
| 强制搜索 `search_executed` | 8/8 |
| 安全状态判断 | 8/8 |
| 精确地区命中 | 6/8 |
| `no_region_matched_source` | 2/2 |
| 错误地区 / unknown 进入 usable | 0 / 0 |
| 白名单外 / 错误型号进入 usable | 0 / 0 |
| Source Candidate 进入 Evidence / Checker | 0 / 0 |
| 必要元数据完整 | 7/7 |
| 本地证据充分任务无效联网 | 0/2 |

`navigation_candidates` 只保留有界 URL、状态和观察地区，用于说明“找到其他地区页面但不能核验目标地区”；不保存搜索摘要正文。

## 错误、缓存与 Agent 接线

离线测试覆盖 401/403 单次调用且不重试；429、503 和超时最多重试 1 次；主引擎失败后可有界进入搜狗；空结果不缓存、不补造；原始结果只扫描前 50 条，可用结果最多 10 条。冷/热缓存候选一致，热命中额外费用为 0。

两条本地证据充分任务均被联网门阻断。一个目录外型号集成用例真实走过 Agent 的 `source_search_started/completed` 脱敏事件；返回 URL 没有进入最终报告、Evidence 或 Checker。开关关闭时工具不注册，显式 disabled 工具测试也保持本地路径可用。

## 自动化与回归

- V2-3 定向离线测试：24/24（零网络、零模型费用）。
- `smartbuy/tests`：201/201；加入上游配置安全 node 的 CI 等价套件 202/202，3 条既有依赖弃用警告。
- Ruff、Compileall、JavaScript 12/12、PowerShell AST 5/5、Markdown 相对链接 277/277 和 `git diff --check` 通过。
- 本轮变更敏感凭据不安全命中 0、禁止运行产物 0、冻结 data/eval 路径变化 0、依赖与锁文件变化 0。
- 未修改 V1 Catalog、40 条冻结任务、历史实验结果、V1 Tag 或 `main`。

## 已知限制与 V2-4 前置条件

- 搜索 API 具有概率性；同一问题的返回数量与排序可能变化。
- V2-3 不读取页面正文，因而不能确认 USB-C 功率、分辨率等规格，也不能为数据库外型号生成推荐。
- 价格和库存仍不是实时可信事实。
- V2-4 若获授权，需要对 navigation candidate 做 canonical/hreflang/地区跳转发现、SSRF 安全正文提取、字段规范化和证据核验；只有目标地区正文通过这些门后才能形成 EvidenceRecord。
