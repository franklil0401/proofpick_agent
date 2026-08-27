# 项目结构说明

## 文档元信息

| 项目 | 内容 |
|---|---|
| 最后更新时间 | 2026-08-27 |
| 当前阶段 | 阶段 4：核心消费决策 Agent 工作流（已完成，等待用户验收） |
| 结构生成范围 | 根目录、自研 `smartbuy/`、供应商目录的维护入口与关键子目录 |
| 排除目录 | `.git`、`.venv`、`__pycache__`、`node_modules`、模型缓存、构建产物、运行数据库、向量索引、MinIO 数据和临时文件 |
| 更新规则 | 新增、删除、移动、重命名文件，或文件职责/入口/配置明显变化时，必须在同一 Commit 中更新本文 |

本文是项目结构的事实来源，不承担技术架构设计职责。技术路线、阶段计划和验收要求见 [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)。

## 当前真实结构

```text
proofpick_agent/
├─ .gitignore
├─ DEVELOPMENT_GUIDE.md
├─ FINAL_多源消费决策研究Agent开发交接总文档.md
├─ LICENSE
├─ PROJECT_STRUCTURE.md
├─ README.md
├─ THIRD_PARTY_NOTICES.md
├─ 阿里云百炼API-Key调用与Youtu-RAG接入说明.md
├─ smartbuy/
│  ├─ __init__.py
│  ├─ agent/
│  │  ├─ react.py
│  │  └─ reporting.py
│  ├─ api/
│  │  └─ router.py
│  ├─ config/
│  │  ├─ __init__.py
│  │  └─ bailian.py
│  ├─ data/
│  │  ├─ catalog/
│  │  │  └─ monitors_v1.json
│  │  ├─ demo/
│  │  │  ├─ fact_cards/        # 12 份自制型号事实卡
│  │  │  └─ manifest.json
│  │  ├─ processed/
│  │  │  ├─ products.jsonl
│  │  │  ├─ price_observations.jsonl
│  │  │  ├─ source_records.jsonl
│  │  │  ├─ evidence_records.jsonl
│  │  │  ├─ index_manifest.json
│  │  │  ├─ stage3_retrieval_results.json
│  │  │  ├─ stage4_dry_run_results.json
│  │  │  ├─ stage4_e2e_results.json
│  │  │  └─ stage4_postfix_s4_014_results.json
│  │  ├─ raw/
│  │  │  └─ README.md
│  │  ├─ __init__.py
│  │  ├─ derive.py
│  │  ├─ loader.py
│  │  └─ quality.py
│  ├─ db/
│  │  ├─ __init__.py
│  │  ├─ build_database.py
│  │  └─ schema_v1.sql
│  ├─ docs/
│  │  ├─ adr/
│  │  │  ├─ 0001-vendor-youtu-rag.md
│  │  │  ├─ 0002-bailian-provider-and-index-contract.md
│  │  │  ├─ 0003-governed-monitor-data-and-index.md
│  │  │  └─ 0004-bounded-react-evidence-and-memory.md
│  │  ├─ data_card.md
│  │  ├─ runtime_manifest.md
│  │  ├─ stage1_smoke_test.md
│  │  ├─ stage2_bailian_verification.md
│  │  ├─ stage3_data_and_retrieval_report.md
│  │  └─ stage4_agent_workflow_report.md
│  ├─ domain/
│  │  └─ models.py
│  ├─ eval/
│  │  ├─ __init__.py
│  │  ├─ cases.jsonl
│  │  ├─ run_retrieval_eval.py
│  │  ├─ stage4_cases.jsonl
│  │  └─ run_stage4_eval.py
│  ├─ memory/
│  │  └─ store.py
│  ├─ observability/
│  │  ├─ __init__.py
│  │  ├─ agent_events.py
│  │  └─ usage.py
│  ├─ providers/
│  │  ├─ __init__.py
│  │  └─ bailian.py
│  ├─ retrieval/
│  │  ├─ __init__.py
│  │  └─ knowledge_base.py
│  ├─ tools/
│  │  ├─ base.py
│  │  ├─ evidence_check.py
│  │  ├─ kb_search.py
│  │  ├─ text2sql.py
│  │  └─ web_search.py
│  ├─ scripts/
│  │  ├─ __init__.py
│  │  ├─ build_stage3_data.py
│  │  ├─ build_stage3_index.py
│  │  ├─ start_youtu_rag.ps1
│  │  ├─ validate_stage3_data.py
│  │  ├─ verify_bailian_stage2.py
│  │  └─ verify_stage3_index.py
│  └─ tests/
│     ├─ fixtures/
│     │  └─ stage1_baseline.md
│     ├─ integration/
│     │  ├─ test_stage4_api.py
│     │  └─ test_youtu_bailian_adapters.py
│     └─ unit/
│        ├─ test_bailian_config.py
│        ├─ test_bailian_provider.py
│        ├─ test_stage3_data.py
│        ├─ test_stage3_database.py
│        ├─ test_stage3_retrieval_contract.py
│        ├─ test_stage4_agent.py
│        ├─ test_stage4_evidence.py
│        ├─ test_stage4_kb_search.py
│        ├─ test_stage4_memory.py
│        └─ test_stage4_text2sql.py
└─ vendor/
   └─ youtu-rag/
      ├─ configs/
      ├─ frontend/
      ├─ tests/
      ├─ utu/
      ├─ LICENSE
      ├─ README.md
      ├─ pyproject.toml
      └─ uv.lock
```

`vendor/youtu-rag/` 包含完整固定上游源码，树中只展开维护入口，未逐项列出所有上游文件。上游固定 Commit、版本和差异见 [Runtime Manifest](smartbuy/docs/runtime_manifest.md) 与 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 文件与目录职责

| 路径 | 职责 |
|---|---|
| `.gitignore` | 排除凭据文件、虚拟环境、缓存、日志、运行数据库、向量索引和模型文件 |
| `README.md` | 面向首次访问者的真实状态、快速开始、安全边界与文档入口 |
| `DEVELOPMENT_GUIDE.md` | 项目范围、架构、数据、模型、指标、阶段计划、DoD 和 Git 工作流的主要依据 |
| `PROJECT_STRUCTURE.md` | 当前真实结构和职责的事实来源 |
| `FINAL_多源消费决策研究Agent开发交接总文档.md` | 原始规格、调研和总体完成定义；保持原名与原内容 |
| `阿里云百炼API-Key调用与Youtu-RAG接入说明.md` | 百炼 API 安全、端点、模型和 Youtu-RAG 适配说明；阶段 1 纳入版本控制且未修改 |
| `LICENSE` | 本项目自行开发代码的 MIT License |
| `THIRD_PARTY_NOTICES.md` | 第三方来源、固定版本、许可和供应商目录差异 |
| `vendor/youtu-rag/` | 以 Git subtree 固定纳入的完整 Youtu-RAG 上游源码 |
| `vendor/youtu-rag/configs/` | 上游 Agent/RAG 配置；阶段 1 关闭非必要能力并设置 API Embedding 配置骨架 |
| `vendor/youtu-rag/frontend/` | 上游 WebUI 静态资源；含阶段 4 SmartBuy 模式开关和 SSE 工具卡接线 |
| `vendor/youtu-rag/utu/` | 上游 Python 包、Agent/RAG 服务与 FastAPI；含阶段 1 配置脱敏、阶段 2 Provider/Windows 兼容补丁和阶段 4 独立路由/Monitor 接线 |
| `vendor/youtu-rag/tests/` | 上游测试及本项目新增的配置脱敏回归测试 |
| `vendor/youtu-rag/pyproject.toml` / `uv.lock` | 上游 Python 依赖定义与固定锁文件 |
| `smartbuy/__init__.py` | 自研 SmartBuy Python 包入口 |
| `smartbuy/agent/react.py` | qwen-plus 有界 Tool Calling、结构化状态、依赖门禁、预算与停止循环 |
| `smartbuy/agent/reporting.py` | 从工具观察确定性组装并渲染 Schema 校验报告 |
| `smartbuy/api/router.py` | `/api/smartbuy` HTTP/SSE、Monitor JSON 和长期偏好管理接口 |
| `smartbuy/domain/models.py` | 需求、约束、四态证据、轨迹、候选和最终报告 Pydantic 契约 |
| `smartbuy/memory/store.py` | 进程内会话状态及仓库外、显式确认的长期偏好生命周期 |
| `smartbuy/tools/` | KB、只读 Text2SQL、Evidence Check、Web unavailable 和统一结果契约 |
| `smartbuy/config/bailian.py` | 从继承进程安全加载百炼配置、派生三类端点和 Youtu 子进程映射 |
| `smartbuy/providers/bailian.py` | 普通/流式/工具 Chat、1024 维 Embedding、Rerank、有限重试与降级实现 |
| `smartbuy/observability/usage.py` | 不记录正文或凭据的内存 Token、延迟和成本账本 |
| `smartbuy/observability/agent_events.py` | 有界、脱敏的 Agent 运行摘要和 Monitor 聚合 |
| `smartbuy/data/catalog/monitors_v1.json` | 12 个型号、来源、追加式价格和冲突证据的唯一 canonical 源数据 |
| `smartbuy/data/loader.py` / `derive.py` / `quality.py` | 加载、派生证据/事实卡和执行确定性数据质量门 |
| `smartbuy/data/demo/` | Clone 后可用的 12 份自制事实卡及文件哈希清单 |
| `smartbuy/data/processed/` | 可由 canonical 数据或真实评测重建的 JSONL、索引清单和脱敏指标结果 |
| `smartbuy/data/raw/README.md` | 本地受限原文目录规则；除说明外的内容均被 Git 忽略 |
| `smartbuy/db/schema_v1.sql` / `build_database.py` | 四实体 SQLite Schema、工作区外原子重建、完整性摘要和可选 CSV 导出 |
| `smartbuy/retrieval/knowledge_base.py` | H2 事实卡切分、必需 chunk 元数据和 Youtu/Chroma 正式建库契约 |
| `smartbuy/eval/cases.jsonl` | 40 条固定检索、冲突、拒答和降级金标任务 |
| `smartbuy/eval/run_retrieval_eval.py` | Vector-only/Reranker 检索、Recall/nDCG/拒答/延迟/成本评测 |
| `smartbuy/eval/stage4_cases.jsonl` / `run_stage4_eval.py` | 16 条 Agent 金标、4 条 dry run、真实 E2E 指标与成本 Runner |
| `smartbuy/docs/adr/0001-vendor-youtu-rag.md` | 上游纳入方式、固定 Commit、修改边界和更新流程决策 |
| `smartbuy/docs/adr/0002-bailian-provider-and-index-contract.md` | 百炼 Provider、1024 维索引、重试和降级契约 |
| `smartbuy/docs/adr/0003-governed-monitor-data-and-index.md` | 数据许可边界、四实体 Schema、事实卡和索引版本决策 |
| `smartbuy/docs/adr/0004-bounded-react-evidence-and-memory.md` | ReAct、SQL/Evidence、公开轨迹、停止和 Memory 决策 |
| `smartbuy/docs/data_card.md` | 数据范围、来源、缺失、哈希语义、人工抽查和合规说明 |
| `smartbuy/docs/runtime_manifest.md` | 目标主机、依赖、模型状态、索引契约、运行路径和服务结果 |
| `smartbuy/docs/stage1_smoke_test.md` | 阶段 1 命令、耗时、通过/延后项、安全事件与退出结论 |
| `smartbuy/docs/stage2_bailian_verification.md` | 三模型、建库、KB Search、错误矩阵、安全处置和成本证据 |
| `smartbuy/docs/stage3_data_and_retrieval_report.md` | 数据质量、SQLite、正式索引、40 条检索指标、成本和失败案例 |
| `smartbuy/docs/stage4_agent_workflow_report.md` | Agent 工具链、E2E、Memory、成本、失败修复和真实服务冒烟 |
| `smartbuy/scripts/start_youtu_rag.ps1` | 从继承进程安全映射百炼变量并在回环地址启动 Youtu-RAG |
| `smartbuy/scripts/verify_bailian_stage2.py` | 有界真实 API 验证；只输出脱敏统计，不输出模型正文或 Key |
| `smartbuy/scripts/build_stage3_data.py` / `validate_stage3_data.py` | 生成并核验 processed 数据、事实卡和哈希清单 |
| `smartbuy/scripts/build_stage3_index.py` / `verify_stage3_index.py` | 有界真实建库和不调用模型的 Chroma 契约复核 |
| `smartbuy/tests/fixtures/stage1_baseline.md` | 自制、无隐私的 Markdown 上传与知识库配置冒烟夹具 |
| `smartbuy/tests/unit/` | 百炼统一配置、请求契约、重试、维度与降级单元测试 |
| `smartbuy/tests/integration/` | Youtu Embedding/Reranker 和 Toolkit 日志安全适配回归 |
| `smartbuy/tests/unit/test_stage3_*` | 数据质量、评测集、SQLite 幂等和 chunk 元数据契约测试 |
| `smartbuy/tests/unit/test_stage4_*` | SQL 安全/金标、Evidence 四态、Memory、Agent 上限和降级测试 |
| `smartbuy/tests/integration/test_stage4_api.py` | SmartBuy HTTP/SSE、偏好生命周期和 WebUI 接线回归 |

## 计划结构

以下内容尚不存在，只表示后续阶段的建议落点，不构成已实现能力：

```text
smartbuy/
├─ constraints/            # 确定性硬约束复核（阶段 5 计划）
└─ eval/
   └─ baselines/           # 阶段 6 四组消融与重复运行（计划）
```

## 维护检查清单

- [x] 树状结构来自当前工作区，不从计划或旧文档复制。
- [x] 计划项单独列出且明确标记“计划/不存在”。
- [x] 缓存、模型文件、运行数据和大批样本没有逐项罗列。
- [x] 供应商目录修改已同步第三方声明与 ADR。
- [x] 文件职责与 [README.md](README.md) 和 [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) 一致。
- [x] 两份原始资料仍位于根目录且文件名未改变。

## 文档导航

- [项目首页](README.md)
- [开发指南](DEVELOPMENT_GUIDE.md)
- [Runtime Manifest](smartbuy/docs/runtime_manifest.md)
- [阶段 1 冒烟记录](smartbuy/docs/stage1_smoke_test.md)
- [阶段 2 验证记录](smartbuy/docs/stage2_bailian_verification.md)
- [阶段 3 数据卡](smartbuy/docs/data_card.md)
- [阶段 3 数据与检索报告](smartbuy/docs/stage3_data_and_retrieval_report.md)
- [阶段 4 技术报告](smartbuy/docs/stage4_agent_workflow_report.md)
- [ADR-0004](smartbuy/docs/adr/0004-bounded-react-evidence-and-memory.md)
- [FINAL 开发交接文档](FINAL_多源消费决策研究Agent开发交接总文档.md)
- [阿里云百炼 API 调用说明](阿里云百炼API-Key调用与Youtu-RAG接入说明.md)
