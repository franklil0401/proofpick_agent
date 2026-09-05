# RC4 独立评测交接

仅候选冻结，**不代表发布通过**。本轮不创建/运行Holdout、收费评测、PR、Tag或Release，不合并main。

## 1. 固定身份与先验审计

- 交接分支：`release/proofpick-v2-rc4`；其文档HEAD不是生产版本。
- 生产：`99c7bccc523addc7e8904571dbe8e20a24615c66`。
- Tree：`6b6e98009cefe5aa13f64cf8fe1b24d001fbadb1`。
- Payload：`7126740e9a893a18575f829aff78ef48b346eca0f622db73c952ece4cff8eb25`。
- 先读[冻结记录](v2_release_candidate_rc4_manifest.md)、[机器Manifest](rc4_semantic_runtime_manifest.json)、[配置/成员配方](rc4_freeze_recipe.json)和[V2-9J修复报告](v2_9j_trusted_contracts_repair_report.md)。

在文档分支clone中核对，不执行任何评测器：

```powershell
git clone --branch release/proofpick-v2-rc4 https://github.com/franklil0401/proofpick_agent.git C:\pprc4
Set-Location C:\pprc4
git rev-parse '99c7bccc523addc7e8904571dbe8e20a24615c66^{tree}'
uv sync --project vendor/youtu-rag --frozen --group dev
uv run --project vendor/youtu-rag --frozen python -m smartbuy.docs.v2.rc4_freeze_manifest --check smartbuy/docs/v2/rc4_semantic_runtime_manifest.json
```

工具枚举固定Commit的`git ls-tree`，从`git cat-file blob`独立重算全部725成员、23组Aggregate和Payload，拒绝缺失或不匹配；不靠工作区CRLF字节或`git diff`证明哈希相等。独立方仍应审核配方成员集合，而不只相信工具自身通过。业务运行可在另一个worktree检出固定生产Commit；冻结文档工具留在交接分支。

## 2. 本轮修复与真实产品入口

修复了中文宽度单位丢失、部分硬要求未进入Checker、系列词误报精确身份歧义及过宽工具结果吸收。现在有Pack单位合同、输入要求完整性守卫、精确身份优先且冲突澄清，以及SQL/KB/Evidence/候选池范围约束。未修改Checker/Evidence权限、冻结数据、旧测试断言、默认开关、Prompt或依赖。

默认验证入口必须是`POST /api/smartbuy/portfolio/run`：Monitor走V1兼容ReAct；Laptop/Headphone走DomainDecisionAgent，默认Proposal provider=None。不要只测内部Runner，也不要额外启用Natural/DomainPack开关后宣称默认入口通过。WebUI初始为脱敏回放，不要将其算为在线模型结果。

使用原启动方式，运行目录在仓库外；以下实际服务命令是供获授权的评测方使用，**本次冻结没有执行它们**：

```powershell
.\smartbuy\scripts\preflight.ps1 -RuntimeRoot C:\pprc4run\v
.\smartbuy\scripts\bootstrap.ps1 -RuntimeRoot C:\pprc4run\m -V2RuntimeRoot C:\pprc4run\v
.\smartbuy\scripts\start.ps1 -SmartBuyRuntimeRoot C:\pprc4run\m -V2RuntimeRoot C:\pprc4run\v
.\smartbuy\scripts\stop.ps1
```

Python3.12、Git、uv、MinIO和已有百炼环境配置遵循[Windows说明](v2_9h_windows_reproduction.md)。Bootstrap缺索引时可能调用Embedding，必须另有预算授权；只检查本地数据可使用脚本已有`-OfflineReplay`，但这不能证明在线索引可用。不得打印Key/Workspace值或写入.env；不要更改系统环境变量。记录最终非敏感开关，若继承了未声明覆盖则在运行前停止。API对Monitor返回的版本兼容标记不能替代实际索引Manifest核验。

评测需使用隔离session，长期Memory默认关闭；固定并记录自身调用预算、冷热缓存口径及实际as_of。模型别名没有日期版本固定、默认top_p/seed未设置，需如实记录，不能把离线复现等同LLM确定性。

## 3. 验收标准与隔离

沿用RC3收敛后的联合门槛，不在冻结阶段改评分器或编题：

| 范围 | 门槛 |
|---|---|
| Trusted三品类任务 | 每品类正确率≥80%；分母分别报告 |
| 硬约束 / 推荐事实证据 | F1≥95%；Evidence覆盖≥95% |
| Trusted安全 | 错误配置、错误地区、Scope/Checker/Report越界、unknown过度声明、澄清绕过、Open Evidence进入Trusted Checker均为0 |
| Online Beta安全 | 错域名/型号/配置/地区进入usable、snippet成为Evidence、Open进入Trusted、unknown写成已核验事实、SSRF或白名单外跳转接受均为0 |
| Online效果 | 取证完成率、字段覆盖与分类覆盖单独公开；非Trusted发布阻断指标，安全unknown不算取证完成 |

禁止为修复第2题评测器兼容误报而改生产Evidence规则。第11题公开输入属于已暴露开发回归，不能称为新Holdout。类型/引用兼容事故、首次失败、重试及恢复都必须分开永久保存，不覆盖原结果。

## 4. 证据、接触范围与后续权限

- [固定Commit本地记录](../../eval/results/v2_9j_development_regression.json)：597/597、79/79、V1原始101/101；[Windows CI](https://github.com/franklil0401/proofpick_agent/actions/runs/33966853197)同Commit为597/597成功。均为离线工程证据，不是新独立模型成绩。
- V2-9J开发中只读过被授权的最终报告、`product_failure_audit.json`和`harness_incident_audit.json`三份材料，以及其中公开的已运行题/失败输入。**未读取剩余79条Trusted、15条Online任务及其金标**；本次冻结没有访问独立评测分支内容或运行独立评测器。
- 更早V2阶段已暴露的回归集不恢复盲测身份；已运行11题及报告中公开的输入也不能作为未见题。未来如何使用尚未接触的题、是否另建任务，由用户与独立评测方另行决定，本交接不代为出题或授权执行。
- 不修改main、RC3分支、V1 Tag、历史评测/金标/评分器；不merge或cherry-pick独立评测分支。下一次发布结论必须来自获授权的独立评测，不能由本次冻结推导。

本轮API调用0、费用¥0，生产逻辑变更0。审核通过后停止，等待用户对下一步独立评测的明确授权。
