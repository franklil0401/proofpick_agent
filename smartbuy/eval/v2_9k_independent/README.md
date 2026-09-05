# RC4 独立续评计划

生产固定为 `99c7bccc523addc7e8904571dbe8e20a24615c66`，Manifest Payload 为 `7126740e9a893a18575f829aff78ef48b346eca0f622db73c952ece4cff8eb25`。

本目录只添加评测器、冻结记录和结果，不修改生产代码。独立分支基于旧评测分支合入 RC4 交接；旧评测分支不移动。运行的每个生产成员必须与 RC4 Git blob 一致（工作区换行差异仅在执行字节核对时归一化，冻结哈希仍使用原始 Git blob）。

## 顺序与门槛

1. 独立复算23组Manifest、725个唯一成员和Payload；检查三套本地索引、数据版本与1024维。运行597项离线测试和既有评测器类型兼容测试。
2. 原 RC3 的001、005、007、011四个已暴露失败案例，各运行一次真实默认 Portfolio API。全部通过且无安全异常，才进入下一步；否则停止并只读归因。
3. 余下79条原冻结题分别为 Monitor 19、Laptop 30、Headphone 30；只运行从未执行的题，各一次。开发方未接触这些题的声明见 RC4 Handoff；不能证明语义重叠完全不存在。保留各品类和任务类型分母，不将其称为新的均衡90题。
4. Trusted 安全门通过后，才能进行原15条未运行 Online Beta 探测；Beta 安全和效果分开报告。本文不提前宣称其完成。

旧题、金标和 `score.py`、`score_v2.py` 原样复用；V1引用格式兼容仅使用之前获授权且已冻结的 `score_v2`。原始结果永久保留，RC4新结果分目录，不替换RC3结果。旧 scorer 的 `release_gate_passed` 要求90条，不能用于79条分母；本次按每品类≥80%、硬约束F1≥95%、推荐事实证据≥95%、所有安全违规0分别报告，不据此伪造均衡90条发布结论。

四条暴露回归通过才继续79条；任何安全命中先停止、保留原始响应并人工检查是产品还是评测器错误。若需修改评分兼容逻辑，必须另记事故，不改变生产、题目或金标。没有自动重跑、Checkpoint恢复或热缓存包装。长期Memory关闭，每题独立session。

## 真实入口与预算

通过 FastAPI 路由挂载和 HTTPX ASGITransport 发送 `POST /api/smartbuy/portfolio/run`，保留HTTP状态与生产JSON响应。不替换Provider、不直接调用专用Domain Runner、不打开隐藏功能开关。网络模型仍真实调用，ASGI仅省略本机TCP层；不是完整WebUI/MinIO演示或新的干净克隆验证。

复用已验证的仓库外只读数据/向量索引，重新检查当前合同；新会话不读取旧偏好。发现任何继承的PROOFPICK/SMARTBUY覆盖先停止，不静默启用。只在评测子进程设置文档启动所需路径与 `PROOFPICK_DOMAIN_AGENT_ENABLED=true`。

本轮总预算沿用¥5上限；Trusted（含四条回归）最多¥2，Online最多¥3。Trusted每题启动前预留¥0.25、180秒超时；正常Provider重试按生产配置计入用量，评测器不重跑任务。成本为API用量估算，不是账户实际账单。模型使用供应商别名，未固定seed/top_p，实际时间独立记录。

## 可复现命令

从仓库根目录设置 `PYTHONPATH` 后：

```powershell
uv run --project vendor/youtu-rag --frozen python -m smartbuy.eval.v2_9k_independent.run exposed
uv run --project vendor/youtu-rag --frozen python -m smartbuy.eval.v2_9k_independent.run unseen
```

两个阶段的首测输出使用排他创建，已有结果时拒绝覆盖。冻结文件须先生成、提交，再运行。完整冻结配方与结果见同目录后续审计记录。
