# SmartBuy Research Agent

多源消费决策研究 Agent：基于 Youtu-RAG 规划的可追踪、可评测消费决策系统。

> 当前状态：**阶段 0（文档体系初始化）**。仓库尚无业务代码、上游源码、数据集或可运行应用；本文不会把计划能力描述为已经实现。

## 项目简介

SmartBuy Research Agent 面向参数复杂、来源分散且信息可能过期的日常消费选择。MVP 聚焦显示器：用户提供预算、用途、尺寸、接口和面板等要求，系统计划通过官方资料知识库、SQLite 参数查询和公开网页补充，输出带推荐、淘汰理由、证据、冲突和未知项的决策报告。

目标用户包括不愿手工核验大量资料的普通消费者、需要严谨比较型号的数码爱好者，以及希望复用长期偏好的重复使用者。

## 当前开发状态

### 已完成

- 已确定显示器消费决策场景、Youtu-RAG/Agentic RAG 技术主线和 Windows 云 API 路线。
- 已建立根目录开发指南、项目结构事实文档和 README。
- 已记录阿里云百炼三模型接入、安全规则、阶段计划和建议验收指标。
- 已关联 Git 远端；具体分支和提交以 Git 历史为准。

### 尚未开始或待验证

- Youtu-RAG 源码纳入方式、上游 commit 固定和 Windows 基线运行。
- MinIO、Chroma、SQLite、FastAPI、WebUI 和 `/monitor`。
- 阿里云百炼 LLM、Embedding、Reranker 实际调用与 Provider 适配。
- 显示器数据采集、SQLite、知识库、评测集和向量索引。
- KB Search、Text2SQL、Web Search、Parallel Orchestrator、Memory 和 Excel Agent。
- 硬约束复核、自动化评测、前端展示和演示材料。

## 核心技术路线（计划）

```text
用户需求与偏好
      ↓
Youtu-RAG WebUI / FastAPI / SSE
      ↓
Parallel Orchestrator
      ├─ KB Search：官方文档事实
      ├─ Text2SQL：SQLite 硬约束和计算
      └─ Web Search：当前价格、库存和近期变化
      ↓
向量召回 → qwen3-rerank 二阶段重排 → 证据融合
      ↓
确定性硬约束复核
      ↓
候选、淘汰原因、证据、风险和数据缺口
```

当前主线是 Agentic RAG，不是 GraphRAG。GraphRAG 只有在 MVP 和基线评测完成后，经过单独决策才可能作为可选实验。

## 计划功能

### MVP

- Windows 原生运行 Youtu-RAG、MinIO、Chroma、SQLite 和 WebUI。
- 管理文本型官方 PDF/Markdown，构建显示器知识库。
- KB Search 完成有来源的事实核验和证据不足拒答。
- Text2SQL 完成预算、尺寸、分辨率、接口等组合筛选。
- Parallel Orchestrator 至少完成 KB + SQL，多源 Web 作为正式演示目标。
- 输出结构化决策报告，并用代码或 SQL 二次复核硬约束。
- 建立可观测轨迹和 Direct LLM / Fixed RAG / Agentic RAG 同集评测。

### 增强与可选实验

- 短期/长期偏好 Memory，或独立 Excel Agent 的稳定展示。
- 逐句引用、冲突提示、缓存、费用面板和消费决策卡片。
- Excel worker 并行、第二商品类别和 GraphRAG 对照实验均为后置可选项。

详细输入、输出、失败降级和范围边界见 [开发指南](DEVELOPMENT_GUIDE.md)。

## 技术栈（计划，待阶段 1～2 验证）

- Python 3.12、uv
- Youtu-RAG / Youtu-Agent
- FastAPI、SSE、原生 HTML/CSS/JavaScript WebUI
- MinIO、Chroma、SQLite
- 阿里云百炼：`qwen-plus`
- 阿里云百炼：`text-embedding-v4`，固定 1024 维
- 阿里云百炼：`qwen3-rerank`
- Pytest 与项目专属 Eval Runner（计划）

## 快速开始

当前仓库仍是文档阶段，**不存在已经验证的安装或启动命令**，不能启动业务应用。首次接手者应先阅读：

1. [开发指南](DEVELOPMENT_GUIDE.md)，确认阶段状态、DoD 和 Git 规则。
2. [当前项目结构](PROJECT_STRUCTURE.md)，确认真实存在的文件。
3. [FINAL 开发交接文档](FINAL_多源消费决策研究Agent开发交接总文档.md)，理解原始范围和 Windows 部署建议。
4. [阿里云百炼 API 调用说明](阿里云百炼API-Key调用与Youtu-RAG接入说明.md)，理解密钥和三模型适配规则。

阶段 1 将固定上游 commit、验证 `uv sync --frozen`、MinIO、WebUI 和最小 KB；验证后的命令才会补充到这里。

## Windows 环境

当前目标环境：

| 项目 | 配置 |
|---|---|
| 操作系统 | Windows 11 |
| Python | 3.12（当前检测 3.12.3） |
| CPU | Intel i5-10400F |
| 内存 | 32 GB |
| GPU | GTX 960 2 GB |

GTX 960 2 GB 不适合作为本地大模型或 2B Embedding 的主要在线推理设备，因此云端 API 是主方案；本地模型只能作为后续实验或明确的降级方案。开发和运行优先使用短 ASCII 路径，避免 Windows 长路径及中文路径兼容问题。

## 环境变量

项目只记录环境变量名称，不保存真实值：

| 变量名 | 用途 | 敏感性 | 当前说明 |
|---|---|---|---|
| `Qianwen_api_key` | 百炼 LLM、Embedding、Reranker 共用 API Key | 敏感 | 必须从 Windows 系统环境读取，禁止输出或写入文件 |
| `Qianwen_workspace_id` | 百炼业务空间 ID | 非密钥但需正确配置 | 当前进程尚未检测到，待用户补充，禁止猜测 |

后续可在启动进程内映射到 Youtu-RAG 所需的 `UTU_*_API_KEY`，但不得写入 `.env`。Embedding 模型或维度变化后必须重建全部向量索引。

## 测试与评测

当前尚无测试代码和实验结果。计划使用至少 30 条任务比较 Direct LLM、Fixed RAG、Agentic RAG 和 Agentic RAG + Constraint Check，覆盖 Recall@K、nDCG/MRR、硬约束满足率、证据引用、无依据结论、API 成功率、延迟、成本和降级可用性。

指标定义、建议目标、计算方法和未来验收命令见 [开发指南的验收指标](DEVELOPMENT_GUIDE.md#9-验收指标)。所有建议目标都需由真实基线校准，不代表已取得结果。

## 文档导航

- [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)：主要开发依据、数据方案、架构、阶段计划、指标和 DoD。
- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)：当前真实项目结构及明确标注的计划结构。
- [FINAL 开发交接文档](FINAL_多源消费决策研究Agent开发交接总文档.md)：原始项目规格和总体调研结论。
- [阿里云百炼 API 调用说明](阿里云百炼API-Key调用与Youtu-RAG接入说明.md)：百炼安全规则、端点和适配注意事项。

## 上游参考与致谢

项目计划基于腾讯开源 [TencentCloudADP/youtu-rag](https://github.com/TencentCloudADP/youtu-rag) 进行场景化二次开发，并参考 [TencentCloudADP/youtu-agent](https://github.com/TencentCloudADP/youtu-agent)。感谢上游项目维护者；后续纳入源码时必须固定 commit、保留原始许可证和归属，并明确区分上游原生能力与本项目贡献。

## 许可证

Youtu-RAG 上游使用 MIT License，但本仓库根目录目前尚无 `LICENSE`，本项目自身的最终许可证**待确认**。在许可证确定和数据许可核查前，不应假设所有文档、数据或未来代码均可自由再分发。

## 安全说明

- 绝不提交或展示 `Qianwen_api_key`、Authorization 请求头、`.env` 或其他凭据。
- 所有模型请求必须由后端发起，密钥不得进入前端 JavaScript。
- Python Executor 不是安全沙箱，只能本地处理可信文件，不能暴露公网。
- 不提交受限 PDF、个人隐私、登录后内容、模型权重、运行缓存或未经检查的日志。
- 如果怀疑密钥泄露，应立即停止使用并在百炼控制台轮换，不在 Issue 或对话中展示旧值。
