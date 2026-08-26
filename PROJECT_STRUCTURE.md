# 项目结构说明

## 文档元信息

| 项目 | 内容 |
|---|---|
| 最后更新时间 | 2026-08-26 |
| 当前阶段 | 阶段 2：百炼三模型与 Youtu-RAG Provider 适配（已完成，等待用户验收） |
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
│  ├─ config/
│  │  ├─ __init__.py
│  │  └─ bailian.py
│  ├─ docs/
│  │  ├─ adr/
│  │  │  ├─ 0001-vendor-youtu-rag.md
│  │  │  └─ 0002-bailian-provider-and-index-contract.md
│  │  ├─ runtime_manifest.md
│  │  ├─ stage1_smoke_test.md
│  │  └─ stage2_bailian_verification.md
│  ├─ observability/
│  │  ├─ __init__.py
│  │  └─ usage.py
│  ├─ providers/
│  │  ├─ __init__.py
│  │  └─ bailian.py
│  ├─ scripts/
│  │  ├─ __init__.py
│  │  ├─ start_youtu_rag.ps1
│  │  └─ verify_bailian_stage2.py
│  └─ tests/
│     ├─ fixtures/
│     │  └─ stage1_baseline.md
│     ├─ integration/
│     │  └─ test_youtu_bailian_adapters.py
│     └─ unit/
│        ├─ test_bailian_config.py
│        └─ test_bailian_provider.py
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
| `vendor/youtu-rag/frontend/` | 上游原生 WebUI 静态资源 |
| `vendor/youtu-rag/utu/` | 上游 Python 包、Agent/RAG 服务与 FastAPI；含阶段 1 配置脱敏和阶段 2 Provider/Windows 兼容补丁 |
| `vendor/youtu-rag/tests/` | 上游测试及本项目新增的配置脱敏回归测试 |
| `vendor/youtu-rag/pyproject.toml` / `uv.lock` | 上游 Python 依赖定义与固定锁文件 |
| `smartbuy/__init__.py` | 自研 SmartBuy Python 包入口 |
| `smartbuy/config/bailian.py` | 从继承进程安全加载百炼配置、派生三类端点和 Youtu 子进程映射 |
| `smartbuy/providers/bailian.py` | 普通/流式/工具 Chat、1024 维 Embedding、Rerank、有限重试与降级实现 |
| `smartbuy/observability/usage.py` | 不记录正文或凭据的内存 Token、延迟和成本账本 |
| `smartbuy/docs/adr/0001-vendor-youtu-rag.md` | 上游纳入方式、固定 Commit、修改边界和更新流程决策 |
| `smartbuy/docs/adr/0002-bailian-provider-and-index-contract.md` | 百炼 Provider、1024 维索引、重试和降级契约 |
| `smartbuy/docs/runtime_manifest.md` | 目标主机、依赖、模型状态、索引契约、运行路径和服务结果 |
| `smartbuy/docs/stage1_smoke_test.md` | 阶段 1 命令、耗时、通过/延后项、安全事件与退出结论 |
| `smartbuy/docs/stage2_bailian_verification.md` | 三模型、建库、KB Search、错误矩阵、安全处置和成本证据 |
| `smartbuy/scripts/start_youtu_rag.ps1` | 从继承进程安全映射百炼变量并在回环地址启动 Youtu-RAG |
| `smartbuy/scripts/verify_bailian_stage2.py` | 有界真实 API 验证；只输出脱敏统计，不输出模型正文或 Key |
| `smartbuy/tests/fixtures/stage1_baseline.md` | 自制、无隐私的 Markdown 上传与知识库配置冒烟夹具 |
| `smartbuy/tests/unit/` | 百炼统一配置、请求契约、重试、维度与降级单元测试 |
| `smartbuy/tests/integration/` | Youtu Embedding/Reranker 和 Toolkit 日志安全适配回归 |

## 计划结构

以下内容尚不存在，只表示后续阶段的建议落点，不构成已实现能力：

```text
smartbuy/
├─ data/
│  ├─ catalog/             # 商品与来源清单（阶段 3 计划）
│  ├─ raw/                 # 本地受限原文，仅保留可提交说明（阶段 3 计划）
│  ├─ processed/           # 可重建的清洗数据（阶段 3 计划）
│  └─ demo/                # 合规演示数据（阶段 3/7 计划）
├─ db/                     # SQLite Schema 与构建脚本（阶段 3 计划）
├─ prompts/                # 消费决策和评测提示词（阶段 4 计划）
├─ eval/                   # 用例、Runner、Scorer 和结果（阶段 4～6 计划）
└─ tests/
   └─ e2e/                 # 正式端到端业务与降级测试（阶段 4～6 计划）
```

## 维护检查清单

- [ ] 树状结构来自当前工作区，不从计划或旧文档复制。
- [ ] 计划项单独列出且明确标记“计划/不存在”。
- [ ] 缓存、模型文件、运行数据和大批样本没有逐项罗列。
- [ ] 供应商目录修改已同步第三方声明与 ADR。
- [ ] 文件职责与 [README.md](README.md) 和 [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) 一致。
- [ ] 两份原始资料仍位于根目录且文件名未改变。

## 文档导航

- [项目首页](README.md)
- [开发指南](DEVELOPMENT_GUIDE.md)
- [Runtime Manifest](smartbuy/docs/runtime_manifest.md)
- [阶段 1 冒烟记录](smartbuy/docs/stage1_smoke_test.md)
- [阶段 2 验证记录](smartbuy/docs/stage2_bailian_verification.md)
- [FINAL 开发交接文档](FINAL_多源消费决策研究Agent开发交接总文档.md)
- [阿里云百炼 API 调用说明](阿里云百炼API-Key调用与Youtu-RAG接入说明.md)
