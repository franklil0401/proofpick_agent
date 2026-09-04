# V2-9F Online Research 运行说明

## 状态与边界

V2-9F 是默认关闭的 Open Research 修复，不改变 V1 Trusted 默认路径。它只能从公开官方来源形成请求级临时 Open Evidence；不能写入治理 Ledger、Product Pack、长期 Memory 或 Trusted Checker。当前不具备 RC3 条件。

链路为：

```text
Source Search
→ 本地域名 / 型号 / 地区过滤
→ 静态 HTML 或受限 PDF 获取
→ JSON-LD / 表格 / definition list / 可见正文 / 不执行的内嵌状态
→ Domain Pack 字段与单位规范化
→ Open Evidence 四态检查
→ completed 或显式 degraded
```

## 开关与环境

- `PROOFPICK_SOURCE_SEARCH_ENABLED=true`：显式启用 Source Search。
- `PROOFPICK_OPEN_RESEARCH_ENABLED=true`：显式启用 Open Research。
- `ZhiPu_api_key`：从当前进程环境读取，只能检查 configured / missing，禁止输出值。
- `PROOFPICK_OPEN_EVIDENCE_ROOT`：必须指向 Git 仓库外目录。

默认关闭时不联网。当前只正式实现 Zhipu Provider；Bailian 与 BoCha 没有进入正式路径。

## 有界合同

| 项目 | 上限/规则 |
|---|---|
| 搜索 | 每任务最多 4 次；前三次 `search_pro`，仅无 usable 时进入 `search_pro_sogou` |
| 搜索结果 | 每响应只扫描前 50 条；usable 与 navigation 各最多 10 条 |
| 搜索安全 | `site:`/Provider 域名过滤不是安全边界；每条 URL 本地重新校验 |
| 页面跳转 | 最多 3 次；每跳重新做 SSRF、协议和 allowlist 校验 |
| HTML / PDF | 最多 5 MiB / 8 MiB；PDF 最多 80 页；片段最多 100 |
| 相关官方页 | 仅已确认型号页面中的规格/支持/PDF链接；最多 2 个 |
| 超时 | connect 4 s、read 9 s、单候选总计 15 s（暴露回归配置） |
| 重试 | 401/403 不重试；429/5xx/超时仅 Provider 内有界重试 |
| 浏览器渲染 | 未启用；动态页明确 degraded |

目标地区只能由 URL、页面 locale 或已验证的 hreflang/目标地区页关系建立。错误或 unknown 地区不能进入 usable。PDF/内嵌脚本只提取文本，不执行代码、不写下载文件。

## 离线开发与回归

```powershell
uv run --project vendor/youtu-rag python -m pytest `
  smartbuy/tests/unit/test_v2_9f_online_research.py `
  smartbuy/tests/unit/test_v2_open_research.py `
  smartbuy/tests/unit/test_v2_source_search.py -q

uv run --project vendor/youtu-rag ruff check smartbuy
uv run --project vendor/youtu-rag python -m compileall -q smartbuy
```

这些测试使用 Fake HTTP、最小 HTML/PDF 和未出现在评测集的虚构商品标识，不调用收费 API。

## 已暴露 Online 回归

下面的命令只能用于复核已经暴露的 V2-9D 15 条任务，不能称为新 Holdout。评测器 checkout 必须是独立 Commit `126486861e08a33a94d4c6c5ffeafc121db2ee5e` 的 detached、LF 精确工作树；运行目录必须在仓库外且满足三品类冻结 Data/Index 合同。

```powershell
$evalRoot = 'C:\ai\proofpick-v2\v2-9f-evaluator-lf'
$runtimeRoot = 'C:\ppv2rc2run'
$output = 'smartbuy/eval/results/v2_9f_exposed_online_regression_final.json'

uv run --project vendor/youtu-rag python -m smartbuy.eval.run_v2_9f_online_regression `
  --evaluator-root $evalRoot `
  --runtime-root $runtimeRoot `
  --output $output
```

输出文件是 write-once。首次有效结果为 `6/15`；不得覆盖或通过重复运行包装成更好的结果。Windows `core.autocrlf=true` 会改变 JSONL 工作树字节，评测器会在联网前 fail closed；应使用 `core.autocrlf=false` 的 detached checkout，而不是绕过 SHA-256 校验。

## 失败解释

- `no_region_matched_source`：没有可安全用于目标地区的来源；其他地区页面只能导航说明。
- `http_403` / `request_timeout`：不绕过站点限制，返回 degraded。
- `dynamic_render_required`：当前没有受控浏览器路径。
- `normalization_failed` / `requested_field_missing`：正文不能形成请求字段事实，保持 unknown。
- conflict：保留全部来源值，不静默选择。

完整指标、调用账本和事故记录见 [V2-9F 报告](v2_9f_online_research_repair_report.md)。
