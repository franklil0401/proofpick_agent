# 第三方软件声明

最后更新：2026-08-26

## Youtu-RAG

- 项目：TencentCloudADP/youtu-rag
- 上游仓库：<https://github.com/TencentCloudADP/youtu-rag>
- 固定上游 Commit：`ce5c3010ff2e2a1c3e657ebcba14481ac5a2b066`
- 纳入日期：2026-08-26
- 纳入方式：`git subtree --squash`，目录为 `vendor/youtu-rag/`
- 许可证：MIT License
- 上游许可证原文：[vendor/youtu-rag/LICENSE](vendor/youtu-rag/LICENSE)

Youtu-RAG 的版权归原权利人所有。本项目根目录 [LICENSE](LICENSE) 适用于本项目自行开发的代码；第三方目录继续受其自身许可证约束。数据不自动适用代码许可证，数据来源和再分发许可需单独记录。

### 本项目对供应商目录的阶段 1 修改

为建立 Windows 云 API 基线及修复凭据响应风险，本项目只修改/新增了下列上游目录文件：

| 文件 | 变更原因 |
|---|---|
| `vendor/youtu-rag/configs/rag/default.yaml` | Embedding 切换为 API 配置并从进程环境引用 Key；阶段 1 关闭 Reranker，避免在 Provider 适配前误调用 |
| `vendor/youtu-rag/configs/rag/file_management.yaml` | 关闭阶段 1 非必要 OCR；HiChunk 保持关闭 |
| `vendor/youtu-rag/utu/rag/api/routes/config.py` | 配置接口返回前执行递归脱敏 |
| `vendor/youtu-rag/utu/rag/api/utils/security.py` | 新增通用凭据字段脱敏函数 |
| `vendor/youtu-rag/tests/rag/api/test_config_security.py` | 使用虚构值验证递归脱敏及不修改原对象 |

其余 SmartBuy 场景代码、启动脚本、文档、数据和评测代码放在 `smartbuy/` 或仓库根目录，不与上游原生能力混写。后续若继续修改 `vendor/youtu-rag/`，必须同步更新本声明和[上游纳入 ADR](smartbuy/docs/adr/0001-vendor-youtu-rag.md)。

## 本地开发依赖

阶段 1 在本机使用 MinIO Server 作为对象存储。MinIO 二进制和运行数据位于仓库外的 `C:/ai/`，未随本仓库分发；其许可证与使用条款以 MinIO 官方发行内容为准。
