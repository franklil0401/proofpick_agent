# V2-6C-R：Laptop Holdout 失败现场冻结审计

最后更新：2026-09-03
阶段状态：阻断，V2-6C 未完成
API 调用：本审计提交为 0

## 结论

V2-6C 的唯一一次原 Holdout 首测为 **3/10**，低于 8/10 阻断门槛。该组任务已暴露，从本提交开始永久分类为 `exposed_holdout_regression_v1`，不再作为未见 Holdout 使用。原始结果文件、首次运行元数据、任务明细和失败轨迹保持原样；旁路分类记录见 [`v2_6c_exposed_holdout_classification.json`](../../eval/results/v2_6c_exposed_holdout_classification.json)。

本提交只保存失败现场，不代表 V2-6C 完成；没有继续执行 Open Research、Memory 专项、故障矩阵或 V2-7。

## 不可覆盖的运行轨迹

| 运行 | 任务结果 | 字段 F1 | 推荐事实证据覆盖 | SHA-256 |
|---|---:|---:|---:|---|
| Regression 首次 | 4/10 | 71.11% | 34/36 | `c344a9a30428ca75e0fab653c893f9650154175d463184ede200000dddb4e1d0` |
| Regression Fix1 | 5/10 | 55.00% | 47/47 | `70f38b8a92aeb50b3223b5d67c93333e72ac79ca80a41793b299b134168f85d8` |
| Regression Fix2 | 10/10 | 80.85% | 75/75 | `f89c83fa2be3abe816748435399d0bc44838f5c553ee0c9a40abd466901e9bd5` |
| Regression Fix3 | 10/10 | 100% | 75/75 | `99aaf41ff49c73cdca6eaf5d1475c975d6b70c4a03bbb5fbcef5b55e04add0b5` |
| Regression 冻结前最终回归 | 10/10 | 100% | 75/75 | `f44bd1b2a3af33e880d157c5c273c6be26ed81aa1633a1c46a9a18f161ae929a` |
| 原 Holdout 首次，现分类为 exposed regression | 3/10 | 100% | 3/9 | `5d7009f7c262547a41d63727e5e2e70037cbca01f7d836c2bc10c2a28826aebc` |

冻结任务文件仍为 30 条，SHA-256 为 `3dfcc0f442bda2b6b4d2e96814a8973b415b3d8c8b9b33235924982fa1758d34`。发布候选配置哈希为 `a0e137b03c5ee3cb614d69d201b78391e3a60684a292ce9b78a619782dfe7cda`。

## 暴露组失败摘要

原 Holdout 中 `laptop-014`、`laptop-018`、`laptop-020` 通过，其余 7 条失败：

- `laptop-011`：相似配置目标绑定过宽，错误包含 H7606WI。
- `laptop-012`：事实查询被误分类为筛选，XPS 13 家族中混入错误地区和错误配置。
- `laptop-013`：16GB FHD 与 32GB OLED 配置没有形成完整字段证据集合。
- `laptop-015`：H7606WI/H7606WX 配置对比缺少可审计字段绑定。
- `laptop-016`：加拿大配置的地区与配置证据未形成完成结果。
- `laptop-017`：美国配置与加拿大版本隔离查询未形成完成结果。
- `laptop-019`：US/DE/PH ThinkPad 筛选没有绑定到目标 US 配置。

安全门没有被绕过：Checker 边界违规为 0，unknown 被描述为完全满足为 0。但可用性与精确身份绑定不足，因此不能以 fail-closed 结果宣称阶段通过。

## API 与费用快照

截至阻断点，Regression 五次运行与原 Holdout 一次运行合计：

- qwen-plus 约束回退：42 次。
- 全部模型接口调用：158 次。
- 输入/输出计量：948,431 / 8,590 tokens。
- 估算费用：约 ¥0.521。
- Source Search：0 次。

这些数值是调试与首测累计开销，不是单次请求性能或生产 SLA。

## 后续约束

- 本组只能作为已暴露回归集使用。
- 后续修复不得覆盖或删除上述六份原始结果。
- 若要重新声明未见测试，必须另建、预先冻结并只运行一次的新 Holdout。
- 未经新的授权，不执行修复、收费调用、Open Research、Memory、故障矩阵或 V2-7。
