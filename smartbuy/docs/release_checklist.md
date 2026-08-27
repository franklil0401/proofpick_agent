# Stage 7 发布检查清单

最后更新：2026-08-27

规则：只有真实证据存在才勾选；阶段 6 历史结果不得覆盖。

## 评测与 Demo

- [x] 冻结 40 条增强组首次发布候选已保存：34/40。
- [x] regression 16/16；`s4-004/s4-007/s4-012/s4-014` 通过。
- [x] 分辨率比较 `h6-007` 通过。
- [x] 违规候选推荐 0/56；Checker 安全门未被绕过。
- [x] 首次失败与定向修复分开记录。
- [x] 四个 Demo 真实本地 API 验证 4/4。
- [x] 截图均脱敏；结果回放明确标记非实时。

## Windows 与运行

- [x] preflight 只输出 configured/missing。
- [x] bootstrap 在开发仓库幂等通过。
- [x] MinIO、FastAPI、WebUI、health、monitor 通过。
- [x] stop 只停止 SmartBuy 记录的进程并释放端口。
- [x] 第三个全新短 ASCII clone 完成冻结依赖、SQLite、Chroma、服务与 Demo 4/4；前两次失败已保留。

## 数据、许可与安全

- [x] 12 份事实卡是自制总结；原始受限内容未提交。
- [x] 16 来源与 4 条价格观察包含必要溯源/时间字段。
- [x] MIT LICENSE、THIRD_PARTY_NOTICES 与 vendor 上游 LICENSE 保留。
- [x] 当前候选文件和 Git 历史敏感扫描通过；不输出匹配正文或环境变量值。
- [x] `.env`、私钥、运行数据库、索引、MinIO 数据、缓存、日志、私人路径和个人信息扫描通过。
- [x] 唯一数据库白名单是固定上游 subtree 的测试夹具，不是 SmartBuy 运行数据。

## 工程质量与文档

- [x] 完整 Pytest 95/95 通过，3 条已知上游依赖弃用警告。
- [x] Ruff、compileall、JavaScript 和 PowerShell 5/5 语法检查通过。
- [x] 21 份维护 Markdown 相对链接检查通过，失效 0。
- [x] README、DEVELOPMENT_GUIDE、PROJECT_STRUCTURE、Runtime Manifest 已同步最终状态。
- [x] `git diff`、暂存区与待推送 Commit 已复核，未发现无关文件。
- [ ] origin/main 推送是阶段提交后的最后一步，实际结果以最终交付报告为准。
