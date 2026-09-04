# V2-9C RC2 独立评测交接

## 交接结论

`proofpick-v2-9c-rc2` 只冻结 V2-9C 修复后的生产代码与运行契约，不代表 V2 已通过独立评测。生产 Commit 为 `2d41773981c69b815efa21c0bf21675d095b920d`，Tree 为 `9273e9f41a3ad62ac6712a02a6ee6a4486a90f24`；完整成员与哈希见 [RC2 Manifest](v2_release_candidate_rc2_manifest.md)。

## 必须保留的历史

| 结果 | 不可覆盖口径 |
|---|---|
| V2-9B Trusted 首次 | 64/90，独立首次，结论 `Needs revision` |
| V2-9B Online | 安全终态 15/15，实际网页 Evidence 2/15 |
| V2-9C 同题回归 | 86/90，只能称 exposed regression |
| Online harness 事故 | 保留独立分支中的脱敏事故文件，不删除、不改名 |

90 条 Trusted 和 15 条 Online 已经暴露。它们可以作为回归输入，但不能再成为未见 Holdout、独立首次或新发布结论。

## RC2 复现结果

- 无 Key CI 等价 Pytest：479/479。
- V1 Tag 所含 18 个原始测试文件：当前 98/98；历史 94 个 node 保持通过，额外 4 个为 V2-9C 新断言。
- Ruff、Compileall：通过；JavaScript 13/13；PowerShell AST 6/6。
- Windows preflight 11/11；Monitor/Laptop/Headphone 各 12 个治理配置。
- 三套 SQLite `integrity_check=ok`、外键违规 0；Monitor 索引 60 chunks，Laptop/Headphone 各 12 documents，Embedding 均为 1024 维。
- 首页、health、monitor、capabilities 和 MinIO health 均为 HTTP 200。
- 五个固定 Demo 5/5，API 调用与费用为 0；离线回放 HTTP 200 且脱敏声明存在。
- stop 后 8000、8088、9000、9001 全部释放。

上述 Demo 是合同/已保存脱敏结果验证，不是新的在线发布评测。Windows 本次使用仓库外既有可信索引，未重新向量化。

## 独立评测方进入条件

1. 校验 RC2 的生产 Commit、Tree、Manifest Payload Hash 与每组成员列表。
2. 校验 Data/Index Version、Collection、外部 pointer/manifest 哈希一致。
3. 在看到结果前由独立评测方创建、冻结并哈希新任务和评分规则。
4. 新任务不得从 V2-9B 或 V2-9C 题目改写后冒充未见数据。
5. 首次运行失败、Checkpoint 恢复和评测器事故必须永久保存。
6. 开发分支不得预览未来题目，不得调整未来评分规则。

## 禁止操作

- 不把 RC2 合并进 `main`，不创建 PR、Tag 或 Release。
- 不修改 `v1.0.0-portfolio`、独立评测分支、冻结题集、金标、评分器或首次结果。
- 不把 `86/90` 写成独立泛化指标。
- 不让 Open Evidence 进入 Trusted Checker，不放宽 unknown/conflict fail-closed。

新的独立结果出来前，公开状态继续是 `Needs revision / 尚未发布`。
