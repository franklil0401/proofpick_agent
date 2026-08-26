# ADR-0001：以 Git subtree 固定纳入 Youtu-RAG

- 状态：已接受
- 日期：2026-08-26
- 决策范围：阶段 1 上游源码纳入与维护

## 背景

SmartBuy 需要复用 Youtu-RAG 的 FastAPI、WebUI、文件管理、知识库和 Agent 基础能力，同时保证公开仓库普通 `git clone` 后源码完整、版本可追溯，并把 SmartBuy 自研能力与上游代码清楚分开。

## 决策

1. 上游仓库固定为 <https://github.com/TencentCloudADP/youtu-rag>。
2. 纳入的准确上游 Commit 为 `ce5c3010ff2e2a1c3e657ebcba14481ac5a2b066`。
3. 使用只读语义远端名 `upstream-youtu-rag` 获取该 Commit；不改变 `origin`。
4. GitHub Push Protection 将上游 HiChunk 文档中的 Python 模型类名误判为 Mistral API Key。为不申请绕过安全规则，在固定上游 Commit 之上创建仅拆分相邻字符串字面量的派生 Commit `87af8dcf679f82779257c32c262d34285b6b9903`；类名运行语义不变，具体文件列入第三方差异。
5. 使用 `git subtree --squash` 从该派生 Commit 纳入 `vendor/youtu-rag/`。本次 squash 提交为 `889970d`，subtree 合并提交为 `401f746`；派生 Commit 的唯一父提交仍是固定上游 Commit，可完整追溯。
6. 保留上游 [MIT License](../../../vendor/youtu-rag/LICENSE) 和版权说明；根目录 [THIRD_PARTY_NOTICES.md](../../../THIRD_PARTY_NOTICES.md) 记录来源与差异。
7. 上游源码原则上保持原样。SmartBuy 场景层、百炼适配、硬约束复核、数据和评测代码优先放入 `smartbuy/`。
8. 确需修改供应商目录时，必须记录具体文件、原因、测试和上游差异；阶段 1 的差异以第三方声明为准。

## 备选方案

- Git submodule：仓库较小，但普通 clone 默认不含完整源码，增加演示和复现摩擦，不采用。
- 固定 Commit 源码快照：可用，但丢失 subtree 更新语义；当前 Git 已支持 subtree，无需退化。
- 直接复制或改写上游：归属和升级差异不清晰，不采用。

## 影响

- 仓库体积增加，但普通 clone 可直接获得上游源码。
- 后续上游更新必须显式 fetch、审查差异、重新运行 Windows 基线和安全测试，再执行 subtree 更新。
- `vendor/youtu-rag/` 中的本项目修改可能产生上游合并冲突；修改范围必须保持最小且有测试覆盖。
- 上游更新时若 GitHub Secret Scanning 再次误报，先判断匹配内容的真实语义；不得直接允许疑似 Secret，必须用无语义变更清理或停止并报告。
- 上游 MIT 许可不覆盖项目数据，数据许可另行记录。

## 更新流程

1. `git fetch upstream-youtu-rag main`
2. 审查目标 Commit、许可证及迁移说明。
3. 在独立分支执行 subtree 更新，不使用 force push 或历史重写。
4. 复核第三方声明中的供应商目录差异。
5. 运行依赖、配置脱敏、WebUI、文件和知识库回归测试。
6. 同步 Runtime Manifest、项目结构和 README 后再提交。
