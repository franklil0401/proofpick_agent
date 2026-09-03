# ProofPick V2 详细开发流程

## 1. 文档信息

| 项目 | 内容 |
|---|---|
| 文档用途 | 作为 ProofPick V2 开发、测试、提交、推送和验收的执行依据 |
| 主要读者 | 项目负责人、后续开发智能体、代码评审者 |
| V1 代码仓库 | `franklil0401/proofpick_agent` |
| V1 稳定分支 | `main` |
| V2 推荐分支 | `feature/proofpick-v2` |
| 当前状态 | **V2-6C-R4 已完成 Laptop E2E 工程收尾；新的独立 Release Candidate 评测推迟到 V2-9** |
| 目标环境 | Windows 11、Python 3.12、`uv`、Git、阿里云百炼 |
| 最后更新 | 2026-09-03 |

关联文档：

- [V2 产品目标、能力边界与实现路径](ProofPick_V2_目标与实现路径.md)
- [V1 发布报告](../release_report.md)
- [公开 V1 仓库](https://github.com/franklil0401/proofpick_agent)

## 2. 开发结论

### 2.1 必须建立独立 V2 分支

V2 涉及通用数据契约、Domain Pack、Product Pack、联网搜索、网页提取、自然约束理解和可能的 LangGraph 编排迁移，改动范围大，不能直接在 V1 `main` 上开发。

推荐策略：

1. 将当前 V1 `main` 作为稳定作品集版本。
2. 用 Tag/Release 冻结 V1 的准确代码位置。
3. 从确认后的 V1 `main` 新建 `feature/proofpick-v2`。
4. V2-0～V2-9 的开发全部在该分支完成。
5. 每个阶段形成独立提交并推送到同名远端分支。
6. V2 全部验收前不合并回 `main`。
7. V2 最终通过 PR 合并，禁止 force push 和历史重写。

### 2.2 V1 必须被当作不可破坏的回归基线

“不破坏 V1”不是只要求代码能启动，还包括：

- 现有 95 项自动化测试不能无理由减少或跳过。
- V1 四个固定 Demo 必须持续可运行。
- 40 条冻结任务和阶段 3～7 历史结果不能被覆盖。
- 12 个显示器及其治理数据不能被静默修改。
- 现有 README 指标、作品集指标和失败记录不能被重新解释。
- 现有 Windows 启停脚本、百炼三模型和 Constraint Checker 必须保留兼容性。
- V2 新能力默认通过适配层接入，不允许为了重构删除 V1 安全门。

任何阶段只要 V1 回归失败，就不能提交“阶段完成”，更不能推送后继续下一阶段。

### 2.3 LangGraph 是候选编排框架，不是预先决定的答案

V1 使用自研有界 ReAct 循环。V2 的分支、并行、联网、澄清和恢复需求与 LangGraph 匹配，但项目负责人尚未使用过该技术栈，因此采用“先设计状态、再做 PoC、最后决策”的方式。

PoC 通过后：使用 LangGraph 管理 State、Node、Conditional Edge、并行和 Checkpoint，保留现有工具、Evidence Check、Memory 和 Constraint Checker。

PoC 未通过：继续使用自研循环，但必须将大循环拆成可测试的状态节点和路由函数，并在 ADR 中记录放弃 LangGraph 的原因。

不能为了在简历中出现 LangGraph 而牺牲 V1 正确性或掩盖项目真实实现。

## 3. V1 冻结基线

V2-0 开始前，开发智能体必须从仓库真实状态重新确认以下基线，不能只复制本文数字：

| 基线项 | 当前已知值 | V2-0 要求 |
|---|---:|---|
| 自动化测试 | 95 passed | 重新运行并记录 |
| 显示器商品 | 12 个型号 | 数据哈希和数量不变 |
| 品牌 | 4 个 | 数据哈希和数量不变 |
| 来源记录 | 16 个来源 | 许可边界不变 |
| 字段级证据 | 180 条 | 不覆盖原记录 |
| 知识库 | 60 documents / 60 chunks | 索引契约不变 |
| 冻结任务 | 40 条 | 文件哈希不变 |
| 四个 Demo | 4/4 | 重新运行或按既有离线方式验证 |
| 阶段 6 增强组 | 92/120 | 保留历史结果，不重跑覆盖 |
| 阶段 7 发布候选 | 34/40 | 保留首次结果和失败样本 |
| V1 违规候选推荐指标 | 0/43、0/56 等对应口径 | 不合并不同分母，不改写历史 |

若仓库当前真实值与本文不同，应停止并报告差异，不自行选择一个数字作为新基线。

## 4. 全程强制规则

### 4.1 Git 规则

- V2 开发期间禁止直接向 `main` 提交业务代码。
- 禁止 `git reset --hard`、`git checkout --`、force push 和重写远端历史。
- 不修改远端地址，不替换 V1 Tag 指向。
- 每阶段只包含本阶段范围，不能多个阶段混在一个提交。
- 每阶段完成后必须推送 `feature/proofpick-v2` 并停止。
- 推送前检查 `git status`、`git diff`、`git diff --cached` 和敏感信息。
- 未经用户确认，不创建最终 Release、不合并 PR、不删除备份分支。

### 4.2 V1 保护规则

- 不删除或改名 V1 公开入口，除非提供兼容入口和迁移说明。
- 不修改 V1 冻结评测结果文件。
- 不用 V2 新结果覆盖 V1 指标。
- 不删除 Constraint Checker、Evidence 四态或 fail-closed 行为。
- 不将开放搜索结果直接写入 V1 正式商品库。
- 不以“代码更简洁”为理由删除失败处理、脱敏或预算门禁。
- 所有数据库和索引迁移都必须可回滚到 V1 数据版本。

### 4.3 安全规则

- API Key 只从环境变量读取，不输出值。
- 不提交 `.env`、Authorization、Cookie、运行数据库、向量索引、缓存、日志和模型文件。
- 网页工具禁止访问回环地址、私网地址、文件协议和非 HTTP(S) 协议。
- 不登录网站、不绕过验证码、不抓取受限内容。
- 动态网页只保存必要片段、元数据和哈希；版权不明的完整页面不进入仓库。
- Checker 异常必须 fail closed。

### 4.4 成本规则

- 每个调用云 API 的阶段先运行 3～5 条 smoke test。
- 运行完整评测前估算搜索次数、模型次数和 Token 上限。
- 每阶段设置用户确认的费用上限；预计超限立即停止。
- 记录成功和失败调用；无法精确计量时报告下界或上界，不伪造精确总成本。
- 缓存不能用于掩盖主实验真实延迟，冷/热结果必须分开。

### 4.5 文档规则

- 每阶段更新阶段报告、运行清单、项目结构和 README 的真实能力边界。
- 计划能力明确标注“计划/未实现”。
- 首次失败、定向修复和修复后回归分别保存。
- 所有简历指标必须能追溯到数据版本、评测文件、运行结果和 Commit。

## 5. 分支与发布策略

### 5.1 推荐分支结构

```text
main                         # V1 稳定作品集，V2 完成前不承载 V2 业务开发
feature/proofpick-v2         # V2 主开发分支
feature/v2-<stage>-<topic>   # 只有阶段需要多人/并行评审时才临时创建
hotfix/v1-<issue>            # V1 紧急修复；完成后再同步到 V2
```

不建议额外创建长期 `v1` 分支。V1 的不可变定位应由 Tag/Release 完成，长期分支容易与 `main` 产生两个不清楚的 V1 真相源。

### 5.2 V2-0 推荐 Git 操作

执行前先确认仓库干净、远端正确且 `main` 与 `origin/main` 一致。示例命令仅供后续开发智能体参考：

```powershell
git switch main
git pull --ff-only origin main
git status --short --branch
git tag --list v1.0.0-portfolio
git switch -c feature/proofpick-v2
git push -u origin feature/proofpick-v2
```

如果 `v1.0.0-portfolio` 尚不存在，应先由用户确认后创建并推送；如果已存在，必须核对它是否指向预期 Commit，禁止移动已有 Tag。

### 5.3 V1 Hotfix 同步规则

如果 V2 开发期间 V1 需要紧急修复：

1. 从 `main` 创建 `hotfix/v1-<issue>`。
2. 只修复 V1 问题并运行 V1 全量回归。
3. 通过 PR 合并回 `main`。
4. 在 V2 分支通过 merge 或明确的 cherry-pick 同步。
5. 同步后再次运行 V1 回归。

不得直接在 V2 分支修复后假设 V1 已同步。

## 6. V2 目标架构与实现原则

```text
用户请求
  ↓
需求解析 / 品类路由 / Trusted 或 Open 模式判断
  ↓
有界编排层（自研 ReAct 或 LangGraph，经 PoC 决定）
  ├─ Product Query / Text2SQL
  ├─ KB Search + Reranker
  ├─ Source Search
  ├─ Web Extractor
  ├─ Evidence Normalizer
  ├─ Evidence Check
  ├─ Compatibility Check
  └─ Memory
  ↓
完整候选池 + 字段级证据账本
  ↓
Constraint Checker
  ↓
Decision Ranker
  ↓
带来源、时间、冲突、淘汰原因和降级状态的报告
```

实现原则：

- 编排框架不拥有商品事实。
- LLM 不拥有硬约束最终解释权。
- Source Search 只负责发现来源，不负责判定候选合格。
- 搜索摘要不能直接进入 Checker。
- Checker 的通过集合是最终推荐集合上界。
- Domain Pack 描述品类差异，通用内核不写死商品字段。
- Product Pack 描述商品数据，新商品不要求修改业务代码。

## 7. 阶段总览

| 阶段 | 核心目标 | 主要可见能力 | 是否调用付费 API |
|---|---|---|---|
| V2-0 | 冻结 V1、建立 V2 分支 | V1 可回退、V2 与 `main` 隔离 | 否，Demo 可用离线回放 |
| V2-1 | 通用契约、Monitor Pack、LangGraph PoC | 编排和品类解耦决策 | PoC 默认使用 Fake Provider |
| V2-2 | Product Pack 与证据账本 | 不改代码导入新商品 | 索引验证少量调用 |
| V2-3 | 真实 Source Search | Agent 能发现官方网络来源 | 是，先 smoke |
| V2-4 | Web Extractor 与 Open 模式 | 数据库外商品研究 | 是，受预算限制 |
| V2-5 | 自然约束与主动澄清 | 支持口语、歧义、覆盖和取消 | 是，离线优先 |
| V2-6 | Laptop Domain Pack | 6A/6B 完成；6C 首次失败已保留，R1 身份/Scope 已修复，待新 Holdout | R1 为 0；后续需单独预算 |
| V2-7 | Ranker 与 Memory 升级 | 个性化且可解释的合规排序 | 是，主逻辑可离线测 |
| V2-8 | Headphone Pack 与跨品类评测 | 第三品类与隔离验证 | 是，冻结评测受预算限制 |
| V2-9 | UI、完整评测和发布 | 五分钟可理解的 V2 作品集 | 是，发布候选单次运行 |

## 8. V2-0：冻结 V1 并建立 V2 分支

### 8.1 目标

建立不可混淆的 V1 基线和独立 V2 开发空间。该阶段不得修改任何业务功能。

### 8.2 任务

1. 检查当前分支、远端、HEAD、工作区和未跟踪文件。
2. 确认 `main` 与 `origin/main` 一致。
3. 运行 V1 离线测试、静态检查和文档链接检查。
4. 核对 12 个商品、40 条冻结任务、历史结果和 Demo 资源哈希。
5. 确认 V1 Release/Tag 状态；缺少 Tag 时请求用户确认。
6. 创建并推送 `feature/proofpick-v2`。
7. 新建 V2 开发状态文档和迁移清单。
8. 记录禁止修改的 V1 路径和结果文件。

### 8.3 实现功能

- 没有新增业务功能。
- 获得稳定 V1 回退点。
- 获得独立 V2 远端分支。
- 获得可机器检查的 V1 基线 Manifest。

### 8.4 验收指标

- `main`、`origin/main` 与 V1 基线 Commit 一致。
- V1 工作区干净。
- 95 项或仓库当时真实全量测试全部通过。
- 四个 V1 Demo 4/4，或按发布说明完成等价离线验证。
- 冻结任务、历史结果和数据文件哈希已保存。
- `feature/proofpick-v2` 已推送并设置 upstream。
- V2-0 提交不包含业务代码变化。
- 敏感信息扫描命中 0。

### 8.5 禁止事项

- 不修改 README 指标。
- 不重跑并覆盖 V1 在线历史结果。
- 不创建新数据库 Schema。
- 不开始 LangGraph、Web Search 或 Domain Pack 开发。

### 8.6 提交与停止

建议提交信息：

```text
chore(v2): freeze v1 baseline and initialize v2 branch
```

推送后报告 V1 Commit、Tag、V2 分支、测试、哈希和风险，然后停止。

## 9. V2-1：通用契约、Monitor Domain Pack 与 LangGraph PoC

### 9.1 目标

先定义稳定状态和工具契约，再判断是否使用 LangGraph，最后迁移显示器领域逻辑。不能先引入框架后再寻找使用场景。

### 9.2 子阶段 A：实现级设计

任务：

- 盘点 `smartbuy/agent/react.py`、约束解析、工具和报告中的显示器硬编码。
- 标记重复解析、未进入主链的逻辑和隐式全局状态。
- 定义通用 `Product`、`FieldDefinition`、`Constraint`、`EvidenceRecord`、`SourceRecord`、`Candidate`、`AgentState`。
- 定义 Domain Pack Loader、Schema 版本和兼容策略。
- 定义 Tool Input/Output、错误码、重试性、费用和可继续状态。
- 定义 Trusted/Open 模式字段和报告契约。
- 设计 V1 适配层，保证旧 API 和 Demo 输入仍可工作。

交付物：

- V2 架构设计。
- 当前硬编码迁移表。
- Domain Pack 示例 Schema。
- Agent State 字段表。
- V1 兼容和回滚方案。
- LangGraph PoC 测试计划。

设计验收：

- 每个 V1 显示器字段都有明确迁移目标。
- 通用契约中不出现 `refresh_rate_hz` 等品类专属字段。
- Evidence、Checker、Memory 和报告之间的数据所有权明确。
- 设计评审通过前不写迁移代码。

### 9.3 子阶段 B：LangGraph PoC

PoC 只实现最小流程，不替换 V1 主链：

```text
parse_requirements
  ↓
route_task
  ├─ text2sql
  └─ kb_search
  ↓
evidence_check
  ↓
constraint_checker
  ↓
report
```

任务：

- 使用 `StateGraph` 或经评审选择的 LangGraph API 定义最小状态图。
- 复用现有 Fake Provider 和工具夹具，默认不调用付费 API。
- 实现一个条件路由。
- 实现一次 KB + SQL 并行 fan-out/fan-in。
- 实现最大步骤和最大工具调用限制。
- 实现一个 Checkpoint 恢复案例。
- 实现一个 `interrupt` 澄清案例。
- 验证中断节点副作用幂等。
- 输出可脱敏的节点轨迹。

PoC 验收：

- 至少 10 条代表性 V1 用例候选集合与 Checker 结果一致。
- 16 条 V1 regression 中不得出现新的违规推荐；完整回归可在迁移后执行。
- SQL 与 KB 并行结果完整合并，无覆盖和重复。
- 一个工具失败后按预期降级。
- 一个任务可从 Checkpoint 恢复且不重复计费工具调用。
- 一个澄清任务可以暂停并恢复。
- Fake Provider 下结果可重复。
- PoC 代码与 V1 生产路径隔离，可以整体删除。

### 9.4 LangGraph 决策门

只有同时满足以下条件才正式采用 LangGraph：

- PoC 验收全部通过。
- 没有绕过 Constraint Checker。
- 现有 SSE/Monitor 可以映射到节点事件。
- 状态序列化不包含密钥或不可序列化运行对象。
- 学习和迁移成本没有阻塞秋招作品交付。
- 相比自研循环，至少实质改善路由、并行、恢复或可测试性中的两项。

如果不满足，保留自研 ReAct，并将节点边界、路由和状态契约应用到自研实现。两种结论都必须形成 ADR。

### 9.5 子阶段 C：Monitor Domain Pack 迁移

任务：

- 建立 Monitor Domain Pack。
- 迁移字段 Schema、别名、单位、约束操作符和来源优先级。
- 迁移 Checker 规则和场景评分占位配置。
- Text2SQL 白名单由 Pack 生成。
- Evidence Check 根据 Pack 字段运行。
- 保留 V1 API 和报告兼容层。
- 移除确认无调用的重复解析逻辑。

### 9.6 阶段验收指标

- V1 全量测试全部通过，数量不得减少。
- V1 四个 Demo 4/4。
- 通用内核源文件不包含显示器专属字段常量。
- Monitor Pack 能完整描述 V1 已支持字段。
- V1 40 条任务的 Checker 合规集合无退化。
- LangGraph 采用/不采用结论有 ADR 和证据。
- 无新增真实 API 成本，除非用户另行批准少量 smoke。

### 9.7 提交与停止

建议提交信息：

```text
refactor(v2): introduce domain contracts and monitor pack
```

PoC 可以使用独立前置提交：

```text
test(v2): evaluate langgraph orchestration feasibility
```

阶段报告必须明确 LangGraph 结论，不得只写“已接入框架”。推送后停止。

## 10. V2-2：Product Pack 与字段级证据账本

### 10.1 目标

让新增商品成为数据操作，并让本地和联网证据使用同一契约。

### 10.2 任务

- 定义 Product Pack JSON Schema 和版本字段。
- 提供显示器示例 Pack。
- 实现型号、品牌、地区版、配置版和别名对齐。
- 实现单位规范化和未知值语义。
- 每个字段关联来源、片段、地区、版本和时间。
- 实现 staging、validate、publish 和 rollback。
- 幂等生成 SQLite、事实卡、向量文档和 Manifest。
- 建立当前请求临时证据区，预留联网证据写入接口。
- 增加数据许可和可再分发检查。

### 10.3 实现功能

- CLI 导入、校验、发布和回滚 Product Pack。
- 新增商品不修改业务代码。
- 错误数据不会污染当前正式版本。
- 数据版本可追溯到 Pack、Schema 和索引配置。

### 10.4 验收指标

- 不修改 Python 业务代码导入第 13 个显示器。
- 新商品可被 Text2SQL、KB Search、Evidence Check 和 Checker 使用。
- 同一 Pack 重复构建的规范化数据和 Manifest 哈希一致。
- 外键违规 0，SQLite `integrity_check=ok`。
- 非法单位、重复型号、错误地区和缺来源测试全部被拒绝。
- 构建失败后旧数据版本仍可查询。
- V1 数据和 40 条任务回归全部通过。
- Embedding 维度继续严格为 1024；模型或维度变化必须重建新索引。

### 10.5 提交与停止

```text
feat(v2): add versioned product pack ingestion
```

推送后报告第 13 个商品、幂等哈希、失败回滚和 V1 回归，然后停止。

## 11. V2-3：受控 Source Search MVP

### 11.1 目标

在保留 V1 unavailable Web 工具的同时，增加真实、显式、可审计的来源搜索工具，但不让网页结果直接进入证据或推荐。

### 11.2 任务

- 实现可插拔 `SourceSearchProvider` 与 `ZhipuSourceSearchProvider`。
- 使用 `ZhiPu_api_key`，不得输出或持久化值；特性开关默认关闭。
- 先调用 `search_pro`；无精确地区来源时有界回退 `search_pro_sogou`。
- 实现 `SourceSearchRequest`、`SourceSearchResult`、`SourceCandidate` 与状态枚举。
- 支持查询、品类、目标字段、地区、freshness 和站点白名单。
- 首批只允许 Dell、ASUS、LG、BenQ 官方域名。
- 确定性区分 `region_matched`、`region_mismatch`、`region_unknown`、`model_mismatch`、`domain_rejected` 和 `invalid_url`。
- 记录调用原因、是否真实搜索、requested/raw/scanned/usable 数量、URL 元数据、延迟、费用和错误。
- 实现最大搜索次数、RPS、超时、有限重试和 TTL 缓存。
- 未真实触发搜索时返回明确降级，不使用模型常识补结果。

### 11.3 实现功能

- Agent 可以在显式开关下调用 Source Search。
- 能区分静态充分证据任务和必须联网任务。
- `usable_candidates` 只含精确地区来源；其他/未知地区只能进入有界导航列表。
- 搜索结果只进入来源候选列表，进入 Evidence Ledger 和 Checker 的数量必须为 0。
- 网络不可用时仍能走 V1 本地主链。

### 11.4 测试集

至少覆盖：

- 4 个品牌各 2 条官方规格查询，允许安全返回“没有目标地区来源”。
- 2 条数据库外型号查询。
- 2 条不应联网的稳定规格查询。
- 401、403、429、5xx、超时、空结果和搜索未触发。
- 缓存冷/热一致性。
- 站点白名单和恶意域名拒绝。

### 11.5 验收指标

- 强制联网用例真实搜索检测 100%。
- 8 条任务状态判断正确 8/8：6 条 `region_matched`，2 条 `no_region_matched_source`。
- 精确地区页面覆盖率如实报告为 6/8，禁止包装为 8/8。
- 返回可用结果中的 URL、域名和搜索时间完整率 100%。
- 站点白名单违规来源进入可用结果 0。
- 错误地区、地区 unknown 和错误型号进入可用结果均为 0。
- 静态充分证据任务无效联网率不高于 5%。
- 401/403 不重试；429/5xx/超时符合有限重试策略。
- Source Search 结果进入 Checker 的数量为 0。
- 关闭网络后 V1 四个 Demo 仍为 4/4。
- 阶段 API 成本低于用户确认上限。

### 11.6 提交与停止

```text
feat(v2): add auditable zhipu source search
```

推送后必须使用以下真实口径：8 条官方来源任务均安全处理，6 条找到目标地区官方页面，2 条明确降级，错误地区误接受为 0。不得写“官方来源搜索准确率 100%”或“官方页面覆盖率 8/8”。

## 12. V2-4：Web Extractor、临时证据与开放研究模式

### 12.1 目标

让数据库外商品形成可追溯研究结果，而不是只获得搜索标题和摘要。

### 12.2 任务

- 实现 URL 规范化和 SSRF 防护。
- 只允许 HTTP(S)，拒绝私网、回环、文件协议和异常重定向。
- 实现页面提取 Provider/Adapter。
- 保存必要正文片段、标题、发布日期、抓取时间和内容哈希。
- 实现 Evidence Normalizer，将网页字段映射到 Domain Pack。
- 联网证据默认写入仓库外临时证据区。
- Evidence Check 比较本地和联网证据。
- 实现 Trusted/Open 模式状态和 API 字段。
- UI/报告明确展示来源、时间、未知和冲突。
- 实现断网、页面变化、动态渲染和抽取失败降级。

### 12.3 实现功能

- 本地不存在的新型号可以生成开放研究报告。
- 搜索摘要不能直接成为硬事实。
- 字段级证据可以绑定页面片段。
- 仅可生成待人工审查的 promotion candidate；本阶段没有实现 Evidence Promotion，也不会自动写库。

### 12.4 验收指标

- 至少 1 个数据库外显示器完成 Source Search → Extract → Normalize → Evidence Check。
- 开放研究报告中的动态事实来源、地区和观察时间完整率 100%。
- 搜索摘要直接进入 Checker 为 0。
- 无正文证据的关键字段状态为 `unknown`，不能标记 `matched`。
- 至少 4 类来源冲突正确保留双方证据。
- SSRF、重定向、超大页面、非 HTML 和超时测试全部按契约处理。
- 断网时本地可信模式仍可运行。
- 临时证据没有进入 Git 提交。

### 12.5 提交与停止

```text
feat(v2): add governed web extraction and open research mode
```

推送后展示一个新商品研究案例、一个失败降级案例和安全测试，然后停止。

## 13. V2-5：自然约束理解与主动澄清

### 13.1 目标

解决固定词表只能识别明确表达的问题，同时保持硬约束安全。

### 13.2 任务

- LLM 输出带原句 span 的类型化 Constraint Proposal。
- Schema 校验字段、类型、单位、操作符和范围。
- 规则层处理中文数字、同义词、否定、覆盖和取消。
- 建立 `supported`、`unsupported`、`ambiguous`、`needs_confirmation` 状态。
- 影响候选集合的模糊条件触发澄清。
- 若采用 LangGraph，使用 interrupt/checkpoint 暂停恢复。
- 若保留自研循环，实现等价可恢复澄清状态。
- 将澄清前后条件变化展示给用户。

### 13.3 评测集

至少 50 条未见表达，覆盖：

- “三千以内”“两三千”。
- “27 寸左右”“不要太大”。
- “Type-C 一线通”“可以给笔记本充电”。
- 中英文混合和单位省略。
- 否定、双重否定、覆盖和取消。
- 软偏好和硬要求区分。
- 未支持字段和互相冲突条件。

### 13.4 验收指标

- 清晰硬约束字段级 F1 不低于 90%。
- 歧义条件未经确认进入 Checker 为 0。
- 未支持字段静默变成硬约束为 0。
- 覆盖、取消和否定专项全部通过。
- 至少 5 条澄清任务可暂停并恢复。
- 恢复后不重复执行已完成的付费工具。
- V1 明确表达用例无退化。

### 13.5 提交与停止

```text
feat(v2): add schema-validated constraints and clarification
```

推送后报告字段级指标、歧义案例、失败样本和恢复行为，然后停止。

## 14. V2-6：Laptop Domain Pack

### 14.1 目标

用复杂参数品类验证通用内核、Product Pack、联网证据和 Checker 不依赖显示器。

V2-6 拆分为三个独立验收阶段：

- **V2-6A（已完成）**：Laptop Domain Pack、治理数据、离线派生产物和冻结任务。
- **V2-6B（已完成）**：独立 SQLite/Chroma、Product Query、KB Search、Reranker、Evidence Check 与 Checker 工具闭环。
- **V2-6C（阻断中）**：R2B 首测失败与 R3 三轮验证均已保留；第三轮仍有 Scope 越界和充分证据下错误空推荐，已按三轮上限硬停止。

### 14.2 数据范围

- 至少 12 个治理型号，建议 12～20 个。
- 优先官方产品页、规格页和支持文档。
- 明确地区和配置版，不把不同 CPU/GPU 配置错误合并。
- 动态价格与稳定规格分开保存。

### 14.3 字段范围

- CPU、GPU、内存、存储。
- 重量、机身尺寸和电池容量。
- 屏幕尺寸、分辨率、刷新率和色域。
- 接口、充电、视频输出和扩展性。
- 可升级性、操作系统和保修。
- 续航、性能、噪声等测评字段必须标记来源类型。

### 14.4 V2-6A 已实现

- 配置驱动的 49 字段 Laptop Domain Pack、42 个 Checker 支持字段和独立 Memory/报告白名单。
- 12 个精确配置、4 个品牌、12 个官方来源和 406 条字段级 Evidence；地区/配置身份完整。
- standalone Product Pack、仓库外 staging/publish/current/versions/rollback，以及 EAV SQLite、事实卡和待索引文档派生。
- 两次构建 Manifest 与逻辑数据哈希一致，SQLite integrity 为 `ok`、外键为 0。
- 30 条 Laptop 任务在首次正式评测前冻结，SHA-256 为 `3dfcc0f442bda2b6b4d2e96814a8973b415b3d8c8b9b33235924982fa1758d34`。
- 10 条自然表达通过现有 Proposal/QuoteSpan 的离线 Pack 驱动验证；本阶段真实模型调用为 0。

V2-6A 没有实现笔记本结构化查询、真实 KB、正式 Evidence/Checker 工具闭环、开放研究或 Agent E2E。索引状态仅为 `documents_ready`，误启用必须 fail closed。

### 14.4.1 V2-6B 已实现

- 由 Domain Pack 驱动的只读 EAV Product Query；预算缺少价格观察时保持 unknown。
- 仓库外独立 Laptop Chroma：12 documents/chunks、`text-embedding-v4`/1024 维，Data/Index/Collection 显式绑定。
- KB Search 与 `qwen3-rerank` 正常/向量降级路径，以及通用 Evidence Check/Constraint Checker 完整候选池安全门。
- 在在线调参前冻结的 30 条独立检索集，首次 Vector/Reranker Recall@5 均为 30/30；nDCG@5 为 0.9766/0.9973，精确绑定与跨品类错误为 0。
- 10 条工具组合任务、两品类字段/索引/Memory/Checkpoint 隔离；没有运行 V2-6A 的 Agent Holdout。

V2-6B 不等于 Laptop Agent E2E。完整 30 条冻结 Agent 任务、自然语言规划、开放研究与端到端报告属于 V2-6C，必须再次授权。

### 14.4.2 V2-6C 首次失败与 R1 修复

- Regression 历史 `4/10 → 5/10 → 10/10`，原 Holdout 首次 `3/10`、推荐证据覆盖 `3/9`；全部原始结果永久保留。
- 原 Holdout 已暴露并分类为 `exposed_holdout_regression_v1`，不能再作为未见测试。
- 30 条任务中的 21～30 已审阅金标但未运行，只能标为 `unrun_exposed_specialist`。
- R1 以 Product Pack Registry 精确解析 `ResolvedProductScope`，同一 Scope 贯穿 Product Query、KB、Evidence、Checker、报告与 Checkpoint。
- R1 仅离线重放暴露的 20 条：Regression `10/10`、已暴露 Holdout `10/10`、推荐事实证据 `75/75`，越界为 0，API 调用为 0。

R1 结果只能证明已知失败得到回归修复，不得当作新 Holdout 泛化结论。详情见[失败链路审计](v2_6c_identity_scope_failure_audit.md)、[修复报告](v2_6c_identity_scope_repair_report.md)和 [ADR-0016](../adr/0016-deterministic-product-identity-and-candidate-scope.md)。

### 14.4.3 V2-6C-R3 通用决策内核与硬停止

- 将 Intent、Reference、Candidate Scope 和 Purchase Constraint 分离，并以 Product Pack Registry、Scope 单调收窄、Canonical Value 与 Constraint Delta 建立品类无关契约。
- 最终暴露回归：历史 50 条为 `48/50`、F1 `95.83%`、证据 `158/163`；合并前两轮后 98 条为 `93/98`、F1 `96.00%`、证据 `343/352`，相关安全越界均为 0。
- 三套验证均在代码冻结后生成、冻结并单次运行：轮 1 `17/24`，轮 2 `16/24`，轮 3 `21/24`。
- 第三轮硬约束 F1 `97.56%`、证据 `93/93`，错误配置/地区/Checker 越界均为 0；但 Candidate Scope 越界为 1，充分证据下错误空推荐为 `1/8`，联合门槛未通过。
- 三轮共调用 Embedding 61 次、Reranker 61 次、LLM 0 次，估算成本 `¥0.204552`；没有 Source Search、Open Research 或重复收费任务。
- 已达到允许的三轮验证上限，不得在本阶段继续修复、生成第四轮或进入 V2-7。完整证据见 [V2-6C-R3 报告](v2_6c_r3_generic_decision_core_report.md)。

### 14.4.4 V2-6C-R4 Laptop E2E 工程收尾

- R3 三轮冻结首测及失败结论原样保留；没有生成第四套验证集，也没有追溯修改门槛。
- 原始 30 条、R2 20 条和 R3 三轮各 24 条合计 122 条永久作为 exposed/diagnostic regression。最终工程回归为 `116/122`，硬约束 F1 `96.60%`，推荐事实证据 `436/445`。
- Checker 前、Checker 后和 Reporting 前建立通用候选集合不变量；Scope/Checker/Report 越界、错误配置/地区、unknown 误报、澄清绕过和充分证据下空推荐均为 0。
- 1134 组变形断言通过；Laptop Open Research 验证了数据库外 ASUS UX5406/US 的 6 个 matched 字段并安全保留 1 个 conflict，所有 Open Evidence 均不能进入 Trusted Checker。
- Memory 隔离、V1 控制故障矩阵 13/13、V2 扩展故障路径和 10 条 ReAct/LangGraph 语义一致性通过；默认编排器没有切换。
- R4 结果只能称为工程收尾，不能称为新 Holdout 泛化结论。新的 RC 评测必须在 V2-9 由独立流程重新冻结和单次运行。详情见 [R4 报告](v2_6c_r4_laptop_engineering_closeout.md)与 [ADR-0017](../adr/0017-deterministic-safety-gates-and-release-evaluation.md)。

### 14.5 验收指标

- 至少 12 个精确配置、4 个品牌、30 条冻结任务。
- 新品类接入不修改通用 Agent 主流程。
- 通用内核不新增笔记本专属字段常量。
- 每个关键推荐事实证据覆盖率不低于 95%。
- 相似配置版和地区版困难用例全部不串型。
- 显示器 V1/V2 回归全部通过。
- 两品类字段、Memory 和索引无交叉污染。

可信模式违规推荐、真实工具闭环和跨品类 E2E 属于 V2-6B/6C，不能用 V2-6A 的离线 evaluator 代替。

### 14.6 提交与停止

```text
feat(v2): add laptop domain pack and governed dataset
```

V2-6A 推送后报告数据卡、字段缺失、评测分母、成本和跨品类回归，然后停止；V2-6B 必须再次获得用户授权。

## 15. V2-7：Decision Ranker 与 Memory 升级

### 15.1 目标

从“满足条件的型号列表”升级为“为什么该候选更适合用户”的可解释决策，同时不改变 Checker 资格。

### 15.2 任务

- 为每个 Domain Pack 定义使用场景评分维度。
- 评分权重透明、可配置、可追溯。
- Ranker 输入只能是 Checker 合规集合。
- 展示每个维度的证据覆盖和权重贡献。
- 支持用户调整用途和偏好后的 what-if。
- 长期 Memory 分为全局偏好和品类偏好。
- Memory 记录来源、确认时间、版本和失效时间。
- 禁止保存价格、库存和模型生成商品事实。
- 移除公开 Demo 的共享硬编码用户身份。

### 15.3 实现功能

- 相同硬约束下根据用途调整候选顺序。
- 用户可查看、修改、删除、关闭和失效长期偏好。
- 报告说明哪些排序受到 Memory 影响。
- Memory 关闭时回到显式输入。

### 15.4 验收指标

- Ranker 输出集合严格等于或小于 Checker 合规集合，越权候选为 0。
- 改变软偏好不会恢复被 Checker 淘汰的候选。
- 至少 12 条 what-if 用例全部解释排序变化。
- Memory 查看、覆盖、删除、关闭和过期测试全部通过。
- 不同用户和会话交叉污染为 0。
- 长期 Memory 中动态价格、库存和商品事实数量为 0。
- Checker 额外模型调用仍为 0。

### 15.5 提交与停止

```text
feat(v2): add explainable ranking and isolated preference memory
```

推送后展示用途变化、Memory 删除和 Checker 不越权案例，然后停止。

## 16. V2-8：Headphone Domain Pack 与跨品类验证

### 16.1 目标

用主观体验比例更高的品类检验来源权限、软偏好和兼容性设计。

### 16.2 数据和字段

- 至少 12 个治理型号，建议 12～20 个。
- 佩戴形态、连接方式、编码、降噪、通话、续航、重量和延迟。
- 区分官方规格、专业测量和主观评价。
- 主观评价不能覆盖官方硬事实。

### 16.3 实现功能

- 通勤、会议、游戏和音乐场景排序。
- 蓝牙编码、平台和有线/无线兼容性检查。
- 专业实测只影响证据允许的软评分。
- 未治理型号进入开放研究模式。

### 16.4 验收指标

- 至少 12 个型号、30 条冻结任务。
- 三个 Domain Pack 共用同一内核。
- 主观证据覆盖硬事实为 0。
- 品类 A 的字段、规则、索引和 Memory 污染品类 B 为 0。
- 三品类可信模式违规候选推荐为 0。
- 每品类 E2E 任务正确率目标不低于 80%。
- 证据不足/困难负例正确拒答率目标不低于 90%。
- 显示器和笔记本回归全部通过。

### 16.5 提交与停止

```text
feat(v2): add headphone domain pack and cross-domain evaluation
```

推送后报告三品类对比、主观证据边界和交叉污染测试，然后停止。

## 17. V2-9：产品 UI、完整评测和发布

### 17.1 目标

形成招聘者五分钟可理解、普通用户可以操作、Windows 可以复现的 V2 作品集。

### 17.2 UI 任务

- 展示当前品类和 Trusted/Open 模式。
- 展示硬约束、软偏好和待澄清项。
- 展示本地/联网工具轨迹。
- 展示候选对比、淘汰理由和 Checker 状态。
- 展示来源、地区、版本、时间、新鲜度和冲突。
- 提供 Memory 查看、修改、删除和关闭入口。
- 提供网络关闭时的离线回放。

### 17.3 最终五个 Demo

1. 本地 SQL + KB + Evidence + Checker 筛选。
2. 数据库外新商品的官方来源搜索和开放研究。
3. 当前价格/库存查询及时间标记。
4. 本地与网页来源冲突及 fail-closed。
5. 连续追问、条件覆盖和长期偏好删除。

### 17.4 最终评测

- 三个品类至少 90 条冻结任务，每品类不少于 30 条。
- 至少 15 条联网专项任务。
- 约束理解、工具路由、检索、搜索、提取、证据、Checker、排序和 Memory 分项评分。
- Direct LLM、Fixed RAG、V1 Agentic RAG、V2 增强组按同一数据版本比较。
- 冷缓存主实验，热缓存单独报告。
- 故障注入覆盖网络、模型、数据库、索引、Checker 和 Memory。

### 17.5 发布门槛

- 可信模式违规候选进入推荐为 0。
- Checker 故障 fail closed 为 100%。
- 搜索摘要直接作为硬事实为 0。
- 动态事实来源、地区和观察时间完整率为 100%。
- 开放研究伪装为治理结论为 0。
- 强制联网任务真实搜索检测为 100%。
- 关键推荐事实证据覆盖率不低于 95%。
- 每品类 E2E 正确率目标不低于 80%。
- 证据不足/困难负例拒答率不低于 90%。
- Windows 干净克隆构建、启动、五个 Demo 和停止全部通过。
- 自动化测试、Ruff、编译、前端语法、PowerShell AST、文档链接和敏感扫描全部通过。
- V1 全量回归仍通过。

### 17.6 发布动作

- 准备 V2 README、Demo 指南、数据卡、指标说明、发布报告和 Release Notes。
- 创建 PR：`feature/proofpick-v2` → `main`。
- PR 中分开说明 V1 保留能力、V2 新增能力、迁移风险和回滚方式。
- 用户确认后合并。
- 合并后运行一次干净克隆发布验证。
- 用户确认后创建 V2 Tag/Release。

### 17.7 提交与停止

```text
release(v2): prepare multi-domain research agent portfolio
```

推送后等待用户确认 PR、合并和 Release，智能体不得自行完成外部发布动作。

## 18. 跨阶段评测体系

### 18.1 分层指标

| 层级 | 主要指标 |
|---|---|
| 约束理解 | 字段级 Precision/Recall/F1、歧义拦截、覆盖/取消正确率 |
| 工具路由 | 必要工具命中、无效工具调用、路径正确率 |
| 本地检索 | Recall@K、nDCG@K、相似型号错误率 |
| 联网搜索 | 真实触发率、来源完整率、白名单违规率、无效联网率 |
| 网页提取 | 页面成功率、字段抽取正确率、时间/地区完整率 |
| Evidence | matched/unknown/conflict 正确率、关键事实覆盖率 |
| Checker | 字段级、任务级、违规拦截、误杀、确定性和延迟 |
| Ranker | 合规集合不越权、偏好变化一致性、解释完整性 |
| Memory | 继承、覆盖、删除、关闭、过期、用户隔离 |
| E2E | 任务正确率、拒答率、违规推荐、延迟、成本和稳定性 |

### 18.2 数据集划分

- Regression：V1 和已修复用例，防止功能回退。
- Holdout：开发过程中不用于调 Prompt 或规则。
- New Expression：从未见过的自然表达。
- New Product：Product Pack 或本地库外型号。
- Cross-domain：同名字段、不同单位和品类污染测试。
- Dynamic：价格、库存、发布时间和页面变化。
- Failure：401/403/429/5xx、超时、空结果、索引损坏和 Checker 异常。

### 18.3 结果保存规则

- 首次完整运行只保存一次，禁止覆盖。
- 修复后只运行相关失败和固定回归。
- 如果需要再次完整运行，使用新 run ID 和新文件。
- 指标必须记录分子、分母、数据哈希、配置、模型、Commit 和时间。
- LLM 无 seed 时明确说明波动，不宣称完全确定。

## 19. 每阶段统一 Definition of Done

一个阶段只有同时满足以下条件才算完成：

- [ ] 阶段范围内的功能已经实现。
- [ ] 计划能力没有伪装成已实现。
- [ ] 阶段自动化、静态和必要人工测试通过。
- [ ] V1 全量回归通过，或有用户明确批准的等价门禁。
- [ ] 首次失败和修复后回归均被保留。
- [ ] 阶段指标有明确分母。
- [ ] API 成本低于用户确认上限。
- [ ] 没有真实 Key、Cookie、私钥和运行产物进入提交。
- [ ] README、开发流程、项目结构、数据卡或运行清单按影响同步。
- [ ] `git diff --check` 和暂存区检查通过。
- [ ] 提交只包含本阶段内容。
- [ ] 提交已推送到 `feature/proofpick-v2`。
- [ ] 本地 HEAD 与远端 V2 分支一致。
- [ ] 工作区干净，相关本地服务已停止。
- [ ] 已向用户报告 Commit、测试、指标、成本、失败、限制和下一阶段条件。
- [ ] 已停止，未自动进入下一阶段。

## 20. 阶段报告模板

每阶段完成后按以下格式回复用户：

```text
阶段：V2-X
状态：完成 / 未完成 / 阻塞
分支：feature/proofpick-v2
Commit：<hash>
推送：成功 / 失败
工作区：干净 / 存在未提交内容

实现功能：
- ...

V1 保护结果：
- V1 全量测试：...
- V1 Demo：...
- 冻结文件哈希：...

本阶段测试：
- 自动化：...
- 静态检查：...
- 敏感扫描：...

量化验收：
- 指标、分子、分母：...

API 与成本：
- 调用次数：...
- Token：...
- 成本：...

首次失败与修复：
- ...

已知限制：
- ...

下一阶段前置条件：
- ...

当前已停止，等待用户确认。
```

## 21. 遇到问题时的停止条件

以下任一情况出现时，智能体应停止并报告，不能擅自扩大范围：

- V1 回归出现无法在本阶段范围内修复的失败。
- 需要修改 V1 历史评测或指标口径才能让 V2 通过。
- 需要新的付费 API、网站凭据或超出费用上限。
- 数据许可、抓取条款或再分发权限不明确。
- LangGraph PoC 需要大规模重写 V1 才能验证。
- Product Pack Schema 无法同时表达本地和联网证据。
- 网页工具需要绕过登录、验证码或访问限制。
- Git 工作区包含无法判断归属的用户修改。
- 推送保护发现疑似凭据。
- 目标和用户最新指令发生实质冲突。

## 22. 下一步只允许执行的工作

V2-6C-R4 已完成 Laptop E2E 工程收尾。三轮冻结验证首测仍是失败，122 条结果只属于已暴露回归；V2-5B/5C、V2-6C-R2B 和 R3 全部历史首测继续原样保留。

下一步只能等待用户另行授权。不得自动进入 V2-7，不得创建新的 Laptop Holdout，不得切换默认编排器，也不得修改 V1 冻结数据与历史结果。新的独立 Release Candidate 评测只能在 V2-9 按预先冻结、单次运行和尽量独立复核的纪律执行。
