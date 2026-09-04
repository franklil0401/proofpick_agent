# ADR-0020：分离查询意图、商品范围与购买约束

- 状态：Accepted
- 日期：2026-09-04
- 阶段：V2-9C（独立评测修复）

## 背景

V2-9B 独立发布评测首次结果为 Trusted `64/90`，结论是 `Needs revision`。主要失效不是 Checker 被绕过，而是 Checker 上游把事实查询或比较字段误当成购买硬约束、商品引用范围收窄不完整、含糊身份未在收费工具前澄清，以及比较任务没有形成“所有点名商品 × 所有请求字段”的证据闭包。Checker 对收到的 `ConstraintSet` 正确执行，仍无法补回用户语义中已经丢失的约束或商品。

## 决策

1. `QueryIntent`、`ResolvedProductScope`、`requested_fields` 与 `ConstraintSet` 是四个独立对象：
   - 事实查询和显式比较中的字段进入 `requested_fields`，不自动进入购买硬约束；
   - 只有明确筛选、推荐或动态购买要求可以激活当前输入的硬约束；
   - 型号、家族、配置和地区引用只定义 Candidate Scope，不能由后续工具扩大。
2. 商品身份只由 Product Pack Registry 和声明式别名解析。型号前缀、家族、配置号、地区和可枚举限定词使用通用算法，不增加评测 case 或具体型号分支。
3. 身份多义或缺少可执行数值阈值时，在 LLM、Embedding、Reranker 和 Checker 之前返回 `needs_clarification`；工具调用数和模型调用数必须为 0。
4. 显式比较必须保留全部点名商品，并为每个商品闭合全部请求字段的 Evidence；比较结果是事实分析，不发布购买推荐 ID。
5. Domain Pack 中 `constraint_enabled=true` 的字段属于确定性 Checker 的可执行集合；重复的策略列表不能把一个合法字段静默降为 unsupported。
6. 中文“无线”不得被裸 `无` 否定规则解释为 `false`。
7. 数据中存在冲突时继续 fail closed。独立金标与治理数据冲突不能通过放宽 Checker、修改数据或修改评分器解决。

## 安全不变量

- Checker 仍是推荐路径的强制终态，LLM 不能修改其结果。
- `unknown`、`conflict` 和 unsupported 不能变成 matched。
- Candidate Scope、Checker 和公开推荐集合均不得越界。
- Open Evidence 不进入 Trusted Ledger 或 Checker。
- V1 默认 ReAct、冻结数据、历史题集和历史结果不变。

## 结果

在已经暴露的同一套 90 条 Trusted 任务上，通用修复后的审计运行由独立首次 `64/90` 提升到 `86/90`；硬约束字段 F1 从 `75.49%` 提升到 `94.44%`，证据覆盖从 `276/297` 提升到 `297/297`，困难负例从 `11/18` 提升到 `18/18`。错误配置/地区、Scope 越界、Checker 越界、unknown 过度声明和澄清绕过均为 0。

该结果是 **exposed regression**，不能替代新的独立发布集，也不能推翻 V2-9B 的 `Needs revision`。最终本地收尾又修正了比较报告分类和无候选早停，但没有再次运行 90 条收费评测，因此不能把它们包装进 `86/90` 指标。

## 备选方案与否决理由

- 针对 26 条失败逐题加关键字或型号补丁：会污染通用内核并对暴露题过拟合，否决。
- 放宽 Checker 或把冲突候选当作 eligible：破坏 fail-closed，否决。
- 修改独立题集、金标或评分器：破坏首次结果不可覆盖性，否决。
- 直接合并独立评测器：开发与评测职责混合，否决。

## 后续

新的发布结论必须由独立评测方基于新的 RC Commit 和未见任务产生。本阶段不创建新 Holdout，不合并 `main`，不创建 Tag 或 Release。
