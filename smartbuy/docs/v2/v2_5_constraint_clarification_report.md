# V2-5 自然约束理解与主动澄清报告

## 1. 结论与边界

V2-5 已在 `feature/proofpick-v2` 落地默认关闭的“确定性优先、LLM 只提案”约束入口。中文数字、金额、范围、单位、否定、双重否定、覆盖和取消先由规则解析；规则确实没有结果且命中特定约束语气时，才允许 `qwen-plus` 通过 Function Calling 提交候选。任何候选必须通过 Domain Pack 字段、类型、单位、操作符、范围和逐字符原文 span 校验，才能进入现有 `ConstraintSet`。LLM 不能修改 Evidence 四态或 Checker 结果。

本阶段没有切换默认编排器、没有修改 V1 冻结数据/任务/历史结果、没有进入 Laptop Domain Pack，也没有运行收费 API。现有 ReAct 仍为默认；LangGraph 仍是显式开启的兼容路径。

## 2. 契约与数据所有权

- `ConstraintProposal`：字段、操作符、规范值、单位、hard/soft、动作、状态、来源、原文 span、turn、置信度、active 和理由均受 Pydantic Schema 约束。
- 状态：`supported`、`unsupported`、`ambiguous`、`needs_confirmation`、`invalid`。只有 `supported` 可激活；cancel 本身不成为有效约束。
- 动作：add、override、cancel、confirm。`ConstraintDiff` 保存变更前后，系统默认被替换不会伪装成用户主动覆盖。
- `ConstraintResolution`：承载 Proposal、有效 `ConstraintSet`、澄清状态、pending ID、diff 和 Provider 用量。
- LLM 所有权仅限 Proposal；确定性代码拥有字段合法性、归一化、激活状态、优先级、取消、Memory 隔离和 Checker 输入。

优先级保持：当前输入 > 会话已确认条件 > 已启用长期偏好 > 系统默认。pending/unsupported/invalid 不进入 Checker；pending 不写长期 Memory。

## 3. 解析与 LLM 回退

规则覆盖首批 Monitor Pack 字段：价格、尺寸、分辨率、刷新率、OLED、USB-C、USB-C 视频/供电、宽度、品牌、支架和地区。中文数字支持“三千”“两千五”“九十”，单位统一到 CNY/inch/Hz/W/mm。近似尺寸、缺少阈值的“不要太大/高刷/可以充电”和口语价格范围触发澄清。

规则无结果时，`QwenConstraintProposalProvider` 固定 `qwen-plus`、`temperature=0`、强制 `submit_constraint_proposals` Function Calling，每轮最多 1 次、最多 12 个候选。模型返回不是事实；精确 span 不匹配、非 Pack 字段、非法 Operator/单位/范围均变为 inactive invalid。本阶段只用 Fake Provider 验证该边界，真实调用 0。

## 4. 暂停、恢复与可观测性

- ReAct：在调用 Agent/工具前返回 `interrupted`，仓库外严格 JSON 保存 pending；恢复后仅执行一次正式 Agent。
- LangGraph：沿用 interrupt/checkpoint；恢复请求携带同一份确定性 Resolution，图的 Checker 强制终态不变。
- 两条路径使用同一 `ClarificationCoordinator`、同一 Engine 和同一报告字段；没有复制业务 Checker/Memory 规则。
- pending 文件按 user/session/thread 哈希隔离，拒绝仓库内目录，不使用 Pickle；完成后原子清除。
- SSE/Monitor 只显示字段、Operator、状态、动作、计数、澄清状态和 diff；不记录隐藏 Prompt、思维链或密钥。

自由文本补值采用确定性二次解析，例如“屏幕不要太大”暂停后回答“32 英寸以下”；恢复不再次调用 Proposal Provider，更不会重放已完成的收费工具。

## 5. 冻结评测与首次失败

评测集见 [说明](v2_5_expression_eval.md)，在实现前冻结 50 条：Regression 30、Holdout 20；SHA-256 为 `9c03937ba7897b9e390f2e73099d394f331bfd696ea763cfc1c3b4b27741eb75`。

| 运行 | TP/FP/FN | Precision | Recall | F1 | 任务全对 |
|---|---:|---:|---:|---:|---:|
| 旧解析器冻结基线 | 13/8/26 | 61.90% | 33.33% | 43.33% | 27/50 |
| V2-5 首次实现 | 53/4/2 | 92.98% | 96.36% | 94.64% | 46/50 |
| 修复后冻结全集 | 55/0/0 | 100% | 100% | 100% | 50/50 |

首次实现失败被保留在 `v2_stage5_initial_implementation_results.json`：两条供电表达被额外推导 `has_usb_c`，两条地区表达把替换系统默认错误标成用户 override。修复只调整代码，没有改金标。最终清晰硬约束为 TP/FP/FN 39/0/0，Precision/Recall/F1 均为 100%；全部状态/动作 Proposal 为 55/55。Regression 30/30、Holdout 20/20；规则平均/P95 0.457/0.703 ms（本机小样本，不是 SLA）。

专项结果：歧义安全 5/5，unsupported 安全 4/4；虚构 span 接受 0，非 Domain Pack 字段激活 0；否定、双重否定、覆盖、取消和当前输入覆盖长期偏好全部通过。

## 6. 编排、Memory 与回归

- 5 类澄清任务在 ReAct 与 LangGraph 各执行一次，10/10 均先暂停再恢复；暂停前 Agent 调用为 0，恢复后为 1，收费工具重复执行 0。
- 明确补值恢复 1/1；ReAct/LangGraph 确认后的 `ConstraintSet` 一致。
- pending 长期 Memory 写入 0；关闭特性开关时直接走 V1 路径。
- V1 原始 94 个 node 首次独立运行 92/94：默认关闭包装器发现 `OrchestratorSelector.kind` 契约属性缺失，两个旧 API 用例失败。增加只读属性后修复为 94/94；未改变路由默认值或 V1 业务规则。Checker/Memory/阶段 4 代表组合 30/30。首次失败与修复结果保存在 `v2_stage5_v1_regression_results.json`，没有通过全量套件的测试顺序掩盖。
- V2-5 两个定向文件 23/23；`smartbuy/tests` 最终 251/251；加入上游配置脱敏 node 的 CI 等价套件 252/252，均只有 3 条既有依赖弃用警告。
- Ruff、Compileall、JavaScript 12/12、PowerShell AST 5/5、Markdown 相对链接 312/312 均通过。

## 7. 成本、风险与限制

- API 调用 0；input/output token 0/0；费用 ¥0；在线 Provider 延迟 N/A。
- 当前规则有意只覆盖 Monitor Pack 首批字段，不追求任意自然语言；规则空缺才允许 Schema Provider。
- 澄清文件是 Windows 本地 MVP JSON 状态，不是生产级多租户存储；LangGraph SQLite 同样不是生产 HA。
- 结构化“确认/拒绝”和可由规则解析的补值已支持；复杂多轮自由文本改写仍应在后续独立评测中扩充，不能绕过 span/Pack 校验。
- 当前阶段不构成切换 LangGraph 默认值或进入多品类的证据。

## 8. 可复现命令

```powershell
uv run --project vendor/youtu-rag python -m smartbuy.eval.run_v2_constraint_eval
uv run --project vendor/youtu-rag python -m pytest smartbuy/tests/unit/test_v2_constraint_proposals.py smartbuy/tests/integration/test_v2_clarification_orchestration.py -q
uv run --project vendor/youtu-rag --group dev python -m pytest smartbuy/tests -q
```

配置和回滚见 [V2-5 运行说明](v2_5_runtime.md)，设计决策见 [ADR-0014](../adr/0014-validated-constraint-proposals-and-clarification.md)。
