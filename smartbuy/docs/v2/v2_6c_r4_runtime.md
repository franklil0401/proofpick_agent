# V2-6C-R4 运行说明

本说明用于复核已暴露工程回归和本地安全测试，不会创建新 Holdout。所有命令在仓库根目录运行；真实 Open Research 输出目录必须位于仓库外。

## 离线回归

```powershell
uv run --project vendor/youtu-rag python -m smartbuy.eval.v2_6c_r3_exposed_runner `
  --output smartbuy/eval/results/v2_6c_r4_exposed_regression_iteration05.json

uv run --project vendor/youtu-rag --group dev python -m pytest `
  smartbuy/tests/unit/test_v2_decision_core_metamorphic.py `
  smartbuy/tests/integration/test_v2_laptop_agent_e2e.py -q
```

122 条任务已经全部暴露；Runner 输出不是 Holdout 或泛化评测。`test_v2_decision_core_metamorphic.py` 当前执行 1134 组变形断言。

## 数据库外 Laptop Open Research

先确认 `PROOFPICK_V2_SOURCE_SEARCH_ENABLED=1` 与 `PROOFPICK_V2_OPEN_RESEARCH_ENABLED=1`，并让当前进程继承 `ZhiPu_api_key`；检查只能输出 `configured/missing`，不得打印值。随后指定仓库外 ASCII 目录：

```powershell
uv run --project vendor/youtu-rag python smartbuy/scripts/verify_v2_6c_laptop_open_research.py `
  --output-root C:\ai\proofpick-v2\laptop-open-research-r4
```

脚本通过 Source Search 动态发现 ASUS Zenbook S 14 UX5406 / US 官方页面，不接受硬编码目标 URL，不保存网页正文；仓库外结果只包含脱敏来源元数据、字段状态、哈希、调用次数和费用。Source Candidate/Temporary Evidence 不能进入 Trusted Evidence 或 Checker。

## 回归与故障检查

```powershell
uv run --project vendor/youtu-rag --group dev python -m pytest smartbuy/tests -q
uv run --project vendor/youtu-rag --group dev python -m pytest `
  smartbuy/tests/unit/test_v2_source_search.py `
  smartbuy/tests/unit/test_v2_open_research.py `
  smartbuy/tests/integration/test_v2_laptop_toolchain.py `
  smartbuy/tests/unit/test_v2_orchestration_contract.py `
  smartbuy/tests/integration/test_v2_api_orchestration.py -q
```

V1 原始范围由 `v1.0.0-portfolio` 中跟踪的 18 个 `smartbuy/tests` 文件确定，当前应为 94/94。默认编排器仍是 ReAct；LangGraph 只用于显式对比，不在本轮切换默认值。

## 结果文件纪律

- `v2_6c_r4_exposed_regression_iteration01..05.json` 均为独立、不可覆盖的调试回归记录。
- R3 三轮冻结数据和 `*_first.json` 不得修改。
- 不在仓库中保存网页正文、临时 Evidence、Checkpoint、缓存、日志、数据库或索引。
- V2-9 之前不得把本阶段结果称为新鲜发布评测。

决策背景见 [ADR-0017](../adr/0017-deterministic-safety-gates-and-release-evaluation.md)，完整结果见 [R4 工程收尾报告](v2_6c_r4_laptop_engineering_closeout.md)。
