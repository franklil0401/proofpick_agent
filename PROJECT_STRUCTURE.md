# 项目结构说明

## 文档元信息

| 项目 | 内容 |
|---|---|
| 最后更新时间 | 2026-08-26 |
| 当前阶段 | 阶段 1：上游项目基线运行与 Windows 环境验证（已完成） |
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
│  ├─ docs/
│  │  ├─ adr/
│  │  │  └─ 0001-vendor-youtu-rag.md
│  │  ├─ runtime_manifest.md
│  │  └─ stage1_smoke_test.md
│  ├─ scripts/
│  │  └─ start_youtu_rag.ps1
│  └─ tests/
│     └─ fixtures/
│        └─ stage1_baseline.md
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
| `vendor/youtu-rag/utu/` | 上游 Python 包、Agent/RAG 服务与 FastAPI；含阶段 1 配置响应脱敏补丁 |
| `vendor/youtu-rag/tests/` | 上游测试及本项目新增的配置脱敏回归测试 |
| `vendor/youtu-rag/pyproject.toml` / `uv.lock` | 上游 Python 依赖定义与固定锁文件 |
| `smartbuy/docs/adr/0001-vendor-youtu-rag.md` | 上游纳入方式、固定 Commit、修改边界和更新流程决策 |
| `smartbuy/docs/runtime_manifest.md` | 目标主机、依赖、模型状态、运行路径和服务结果 |
| `smartbuy/docs/stage1_smoke_test.md` | 阶段 1 命令、耗时、通过/延后项、安全事件与退出结论 |
| `smartbuy/scripts/start_youtu_rag.ps1` | 从 Windows 持久化环境安全映射百炼变量并在回环地址启动 Youtu-RAG |
| `smartbuy/tests/fixtures/stage1_baseline.md` | 自制、无隐私的 Markdown 上传与知识库配置冒烟夹具 |

## 计划结构

以下内容尚不存在，只表示后续阶段的建议落点，不构成已实现能力：

```text
smartbuy/
├─ config/                 # 统一百炼配置、来源策略和输出 Schema（阶段 2 计划）
├─ data/
│  ├─ catalog/             # 商品与来源清单（阶段 3 计划）
│  ├─ raw/                 # 本地受限原文，仅保留可提交说明（阶段 3 计划）
│  ├─ processed/           # 可重建的清洗数据（阶段 3 计划）
│  └─ demo/                # 合规演示数据（阶段 3/7 计划）
├─ db/                     # SQLite Schema 与构建脚本（阶段 3 计划）
├─ prompts/                # 消费决策和评测提示词（阶段 4 计划）
├─ eval/                   # 用例、Runner、Scorer 和结果（阶段 4～6 计划）
└─ tests/
   ├─ unit/                # 自研单元测试（计划）
   ├─ integration/         # Provider/工具集成测试（计划）
   └─ e2e/                 # 端到端与降级测试（计划）
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
- [FINAL 开发交接文档](FINAL_多源消费决策研究Agent开发交接总文档.md)
- [阿里云百炼 API 调用说明](阿里云百炼API-Key调用与Youtu-RAG接入说明.md)
