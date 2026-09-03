# V2-7 分层偏好 Memory 运行说明

## 1. 模型与优先级

V2 `DomainPreferenceMemoryStore` 将长期偏好分为 `global` 与 `category`。有效值合并顺序为：

```text
当前显式输入 > 当前会话已确认条件 > 品类长期偏好 > 全局长期偏好 > 系统默认
```

Session Memory 继续由 Domain Agent 在进程内按 `domain/user/session` 摘要隔离，不等同于长期 Memory；Checkpoint 仍按 user/session/thread 摘要隔离。没有可靠 `user_id` 时，长期 Memory 不召回。

## 2. 存储合同

每条长期记录包含 `key`、`value`、`scope`、`domain_id`、`source=user_confirmed`、`confirmed_at`、`expires_at`、`schema_version` 和 `domain_pack_version`。用户 ID 只用于 SHA-256 文件名，不写入 JSON 或日志；路径字符不能成为文件名。

默认运行目录应在仓库外，例如：

```text
C:\ai\proofpick-v2\memory\users\<sha256>.json
```

Domain Pack 提供：

- `allowed_keys`：可作为品类约束偏好的白名单。
- `global_allowed_keys`：确实允许跨品类的偏好；当前仅为品牌排除。
- `ranking_allowed_keys`：场景与维度权重。
- `schema_version`：不兼容时停止召回旧记录。

Category 记录仅在 `domain_pack_version` 与当前 Pack 一致且未过期时生效。损坏文件会返回空偏好和 `memory_corrupt`，Ranker 继续使用稳定 Profile 并公开 `ranking_degraded`。

## 3. 操作

Python 运行边界：

```python
store.view(user_id)
store.upsert(user_id, values, explicitly_confirmed=True, scope="category")
store.upsert(user_id, values, explicitly_confirmed=True, scope="global")
store.delete(user_id, fields, scope="category")
store.set_enabled(user_id, False)
```

`view` 返回有效全局/品类/合并值、来源，以及包含确认时间、失效时间和版本的记录。`delete` 可删除指定字段或当前层全部记录；关闭后不召回，重新开启后仅召回仍有效且兼容的记录。What-if 只把临时参数放入 `OrchestratorRequest`，不会调用 `upsert`。

HTTP 兼容端点仍为 `/api/smartbuy/memory/{user_id}`。使用 V2 Domain Memory 时必须同时提供 `domain_id` 和 `X-ProofPick-Identity`；后者必须与该浏览器持有的匿名主体 ID 一致，否则返回 403。没有 `domain_id` 的旧请求继续走 V1 Memory，不改变 V1 API。

排序请求字段包括：

- `ranking_scenario`
- `ranking_preferences`
- `ranking_weight_overrides`
- `ranking_use_memory`
- `ranking_what_if`

ReAct 与 LangGraph 只在 Agent 声明支持 V2 Ranker 时转发这些字段，V1 Agent 调用面保持不变。

## 4. 禁止写入

服务端仅接受 Domain Pack 白名单内、用户明确确认的有限标量/列表；排名权重只接受已声明维度。下列数据无法通过写入门：动态价格、库存、优惠、网页商品事实、Open Evidence、工具完整结果、未经确认 Proposal、unsupported 字段、指令型文本、隐藏推理、凭据或模型推测规格。

预算上限属于用户偏好，不是商品价格观察；它仍可按 Pack 白名单保存。实际商品价格、库存和促销值不在长期 Memory Schema 中。

## 5. 本地 Web Demo 身份

供应商 WebUI 不再发送共享 `local-demo-user`。每个浏览器在 `localStorage` 生成独立随机匿名 ID；如果安全随机数或存储不可用，请求不发送 `user_id`，长期 Memory 开关即使被勾选也保持关闭。新的页面会话仍生成独立 `session_id`。

这提供本地作品集 MVP 的隔离，不等同于公网认证或授权系统；`X-ProofPick-Identity` 是本地匿名主体绑定，不是登录凭据。公网部署前必须增加真实登录、主体绑定与服务端授权，不能依赖客户端 UUID 防止恶意越权。

## 6. 故障与隐私

- Memory 关闭、过期、不兼容、损坏或无 user_id：只使用当前显式输入和当前会话状态。
- 不记录明文 user/session/thread；公开排序事件不包含原问题、偏好值或文件路径。
- 用户、会话和品类使用不同摘要键；Monitor Category Preference 不会进入 Laptop，反之亦然。
- Global Preference 只在两个 Pack 都显式允许该 key 时才生效。
- 运行文件、缓存和日志不得提交 Git。
