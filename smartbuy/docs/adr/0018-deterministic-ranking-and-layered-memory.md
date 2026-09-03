# ADR-0018：确定性排序与分层偏好 Memory

- 状态：Accepted
- 日期：2026-09-03
- 范围：ProofPick V2-7

## 背景

Checker 已能确定候选是否满足硬约束，但合规候选仍缺少按用途和软偏好的透明排序。V1 LLM 软排序可以解释顺序，却不适合作为多 Domain 的可复现决策层；旧 V2 Memory 只有单品类键值文件，且 Web Demo 共用固定用户 ID。

## 决策

1. Checker 是唯一资格所有者。Ranker 的输入/输出集合必须等于 Checker eligible 集合；报告 Schema 再做一次验证。
2. Domain Pack 拥有 Ranking Profile，通用 Ranker 不包含任何品类字段、型号或品牌规则。
3. 使用固定范围、Pack 枚举和 Evidence gate 的加权和；unknown 贡献为 0，但不能描述为负面事实。
4. 不使用 LLM 评分。LLM 不能稳定证明字段来源，也不能提供字节确定性，还可能让软偏好覆盖安全门。
5. Profile/Ranker/Memory 异常时使用稳定 ID 顺序并显式降级，不丢弃 Checker 合规候选。
6. 长期 Memory 分为 Global/Category，只有用户确认且在 Pack 白名单内的记录可写入；记录来源、确认时间、失效时间和版本。
7. 身份只以摘要映射到仓库外文件。无可靠 user_id 时长期 Memory 关闭；Web Demo 每个浏览器生成自己的匿名 ID。

## 结果

- 得分可追溯、可复现，也能安全支持 What-if。
- 新 Domain 需要提供并校验自己的 Profile，但无需修改 Ranker 代码。
- 排名只表达当前 Profile 下的相对适配度，不是客观商品质量。
- 浏览器匿名 ID 解决本地 Demo 共享身份，但不替代公网认证授权。
- V1 排序、默认 ReAct、冻结数据和历史评测不变。

## 回滚

关闭 V2 Domain Agent/Ranking 参数即可回到 V1 默认路径；Checker 数据和 Product Pack 无需迁移。若 Profile 无法加载，运行时仍保留 Checker 合规集合并按 ID 稳定排序，同时标记降级。

