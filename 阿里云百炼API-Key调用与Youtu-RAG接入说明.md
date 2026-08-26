# 阿里云百炼 API Key 调用与 Youtu-RAG 接入说明

> 文档日期：2026-08-26  
> 适用项目：多源消费决策研究 Agent / Youtu-RAG 二次开发  
> 目标读者：后续接手开发的智能体或开发者

## 1. 核心结论

本机 Windows 系统已经保存了一个阿里云百炼 API Key，环境变量名称固定为：

```text
Qianwen_api_key
```

后续代码必须从该环境变量读取 Key，不得要求用户把真实 Key 写进源码、Markdown、Git 配置文件或提交记录，也不得在终端、日志、异常信息和智能体回复中输出 Key。

同一个百炼 API Key 可以用于以下三类标准模型：

| 能力 | 当前建议模型 | 用途 |
|---|---|---|
| LLM | `qwen-plus` | Agent 推理、工具调用、报告生成 |
| Embedding | `text-embedding-v4`，固定 1024 维 | 文档与查询向量化 |
| Reranker | `qwen3-rerank` | 对召回证据进行二次排序 |

同一个 Key 可以共用，但三个模型具有不同的模型 ID、HTTP 路径、限流和计费记录。API Key 的权限由其归属业务空间决定；默认业务空间的 Key 通常可以调用全部标准模型，子业务空间或自定义权限 Key 只能调用已授权模型。参考：[百炼 API Key 官方说明](https://help.aliyun.com/zh/model-studio/get-api-key/)。

## 2. 智能体处理密钥时必须遵守的规则

### 2.1 允许的操作

- 使用 `os.getenv("Qianwen_api_key")` 或 `os.environ["Qianwen_api_key"]` 读取 Key。
- 只检查变量是否存在，不显示变量内容。
- 在当前进程内将该值映射到项目所需的其他环境变量。
- 将 Key 放入 HTTP `Authorization: Bearer ...` 请求头。
- 在 Key 缺失时给出明确错误，要求用户重新打开终端或检查系统环境变量。

### 2.2 禁止的操作

- 禁止执行会列出所有环境变量及其值的命令，例如 `Get-ChildItem Env:`。
- 禁止执行 `echo $env:Qianwen_api_key`、`print(api_key)` 或任何等价操作。
- 禁止把真实 Key 写入 `.env`、源码、测试快照、Markdown、日志或 Git 提交。
- 禁止在捕获异常时把完整请求头打印出来。
- 禁止把 Key 作为 URL 查询参数传输。
- 禁止将 Key 发给非阿里云百炼域名。
- 禁止把 Key 复制到前端 JavaScript；所有模型请求必须由后端发起。

如果怀疑 Key 已经泄露，应停止继续使用并提醒用户前往百炼控制台重置 Key；不要尝试在对话中展示或确认旧 Key。

## 3. Windows 环境变量读取

### 3.1 PowerShell 安全检查

只检查变量是否存在：

```powershell
if ([string]::IsNullOrWhiteSpace($env:Qianwen_api_key)) {
    throw "缺少系统环境变量 Qianwen_api_key，请检查配置并重新打开终端。"
}

Write-Host "Qianwen_api_key 已配置。"
```

不要输出变量值。

Windows 在设置系统环境变量后，已经打开的 PowerShell、IDE、VS Code 和后台服务通常不会自动获得新值。若程序读取不到变量，应先关闭并重新打开终端或 IDE，再进行测试。

需要额外注意：

- 普通 Windows 子进程通常继承父进程环境变量。
- WSL、Docker 容器、远程服务器不会自动继承 Windows 系统变量，必须显式传入。
- Windows 环境变量名通常不区分大小写，但代码仍应严格使用约定名称 `Qianwen_api_key`，避免迁移到 Linux 后出错。

### 3.2 Python 安全读取函数

```python
import os


def require_qianwen_api_key() -> str:
    api_key = os.getenv("Qianwen_api_key")
    if not api_key or not api_key.strip():
        raise RuntimeError(
            "缺少环境变量 Qianwen_api_key。"
            "请确认已配置系统环境变量，并重新启动终端或 IDE。"
        )
    return api_key.strip()
```

调用该函数后，变量只能用于客户端初始化或请求头，不得打印：

```python
api_key = require_qianwen_api_key()
```

## 4. 还必须准备 Workspace ID

`Qianwen_api_key` 只保存 API Key，不包含百炼业务空间 ID。调用当前 Workspace 专属端点还需要一个形如下面的业务空间 ID：

```text
llm-xxxxxxxxxxxxxxxx
```

建议把它另存为非敏感环境变量：

```text
Qianwen_workspace_id
```

PowerShell 当前会话示例：

```powershell
$env:Qianwen_workspace_id="llm-xxxxxxxxxxxxxxxx"
```

如果该变量不存在，接手智能体不得猜测 Workspace ID，应提示用户从百炼控制台的业务空间管理页面获取。Key、Workspace 和调用地域必须匹配。

本文默认使用中国大陆华北 2（北京）地域。对应的基础地址为：

```text
OpenAI 兼容基础地址：
https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1

Qwen3 Rerank 完整地址：
https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-api/v1/reranks
```

不得使用北京地域的 Key 调用新加坡端点，也不要把默认公共地址、Workspace 专属地址和其他地域地址混用。

## 5. 安装测试依赖

在项目虚拟环境中安装：

```powershell
python -m pip install --upgrade openai requests
```

以下示例均直接读取 `Qianwen_api_key`，不会把 Key 写入文件。

## 6. LLM 调用

### 6.1 推荐配置

```text
模型：qwen-plus
接口：{BASE_URL}/chat/completions
```

`qwen-plus` 支持 Function Calling，适合作为 Agent 主模型。参考：[qwen-plus 模型说明](https://help.aliyun.com/zh/model-studio/qwen-plus)。

### 6.2 Python 最小测试

```python
import os

from openai import OpenAI


api_key = os.environ["Qianwen_api_key"]
workspace_id = os.environ["Qianwen_workspace_id"]

client = OpenAI(
    api_key=api_key,
    base_url=(
        f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/"
        "compatible-mode/v1"
    ),
)

response = client.chat.completions.create(
    model="qwen-plus",
    messages=[
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user", "content": "只回复：LLM API 正常"},
    ],
    temperature=0.1,
)

print(response.choices[0].message.content)
```

生产代码中可以记录模型名、请求耗时、Token 用量和请求 ID，但不能记录请求头或 Key。

## 7. Embedding 调用

### 7.1 推荐配置

第一版使用：

```text
模型：text-embedding-v4
向量维度：1024
接口：{BASE_URL}/embeddings
```

`text-embedding-v4` 支持多语言和自定义向量维度；1024 维是性能、存储和检索效果之间的稳妥选择。参考：[百炼向量化文档](https://help.aliyun.com/zh/model-studio/embedding?disableWebsiteRedirect=true)。

后续可以评测更新的 `qwen3.7-text-embedding`，但不得在已有向量库上直接切换模型或维度。

### 7.2 Python 最小测试

```python
import os

from openai import OpenAI


api_key = os.environ["Qianwen_api_key"]
workspace_id = os.environ["Qianwen_workspace_id"]

client = OpenAI(
    api_key=api_key,
    base_url=(
        f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/"
        "compatible-mode/v1"
    ),
)

response = client.embeddings.create(
    model="text-embedding-v4",
    input=[
        "预算2500元，编程为主，需要4K和USB-C供电的显示器。",
        "27英寸4K显示器，支持USB-C 90W供电。",
    ],
    dimensions=1024,
)

vectors = [item.embedding for item in response.data]
assert len(vectors) == 2
assert all(len(vector) == 1024 for vector in vectors)
print("Embedding API 正常，向量维度为 1024。")
```

### 7.3 向量库不可破坏的约束

- 文档入库和用户查询必须使用相同 Embedding 模型。
- 两者必须使用相同维度。
- 第一版固定 `text-embedding-v4 + 1024维`。
- 切换模型或维度后，必须重新向量化全部文档并重建索引。
- 模型 ID、维度和索引版本应写入知识库元数据，启动时进行一致性校验。

## 8. Reranker 调用

### 8.1 推荐配置

```text
模型：qwen3-rerank
完整接口：
https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-api/v1/reranks
```

注意接口最后是复数 `/reranks`，不是 `/rerank`。`qwen3-rerank` 的 `query`、`documents`、`top_n` 和 `instruct` 都位于请求 JSON 顶层。参考：[百炼文本排序文档](https://help.aliyun.com/zh/model-studio/text-rerank-api)。

### 8.2 Python 最小测试

```python
import os

import requests


api_key = os.environ["Qianwen_api_key"]
workspace_id = os.environ["Qianwen_workspace_id"]

documents = [
    "A型号：27英寸2K、165Hz，不支持USB-C，售价1699元。",
    "B型号：27英寸4K、USB-C 90W、支持升降支架，售价2399元。",
    "C型号：27英寸OLED、240Hz，售价5999元。",
]

response = requests.post(
    (
        f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/"
        "compatible-api/v1/reranks"
    ),
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={
        "model": "qwen3-rerank",
        "query": "预算2500元，编程为主，需要4K和USB-C供电",
        "documents": documents,
        "top_n": 2,
        "instruct": (
            "Rank product evidence by how directly it supports the user's "
            "hard constraints, including budget, specifications, usage scenario, "
            "source credibility, and publication time. Penalize promotional or "
            "outdated content."
        ),
    },
    timeout=30,
)

response.raise_for_status()
payload = response.json()

for item in payload["results"]:
    index = item["index"]
    score = item["relevance_score"]
    print(index, score, documents[index])
```

`relevance_score` 是同一次请求内部的相对相关性分数，不能把不同请求的分数直接横向比较，也不应将 `0.8` 解释为“80%正确”。阈值必须基于本项目测试集校准。

## 9. 在 Youtu-RAG 中复用现有系统变量

Youtu-RAG 为 LLM、Embedding 和 Reranker 分别读取不同变量。为了避免把 Key 再写入 `.env`，推荐在启动进程前进行内存映射：

```powershell
if ([string]::IsNullOrWhiteSpace($env:Qianwen_api_key)) {
    throw "缺少 Qianwen_api_key。"
}

$env:UTU_LLM_API_KEY = $env:Qianwen_api_key
$env:UTU_EMBEDDING_API_KEY = $env:Qianwen_api_key
$env:UTU_RERANKER_API_KEY = $env:Qianwen_api_key
```

三个 `UTU_*_API_KEY` 最终是同一个值，只是为了适配项目现有配置接口。不要在日志中验证它们是否相等，也不要打印它们。

`.env` 或配置文件中只保存非敏感项：

```dotenv
UTU_LLM_TYPE=chat.completions
UTU_LLM_MODEL=qwen-plus
UTU_LLM_BASE_URL=https://你的WorkspaceId.cn-beijing.maas.aliyuncs.com/compatible-mode/v1

UTU_EMBEDDING_MODEL=text-embedding-v4
UTU_EMBEDDING_URL=https://你的WorkspaceId.cn-beijing.maas.aliyuncs.com/compatible-mode/v1

UTU_RERANKER_MODEL=qwen3-rerank
UTU_RERANKER_URL=https://你的WorkspaceId.cn-beijing.maas.aliyuncs.com/compatible-api/v1/reranks
```

不要在 `.env` 中保留空白或占位的 `UTU_*_API_KEY=`，以免某些配置加载逻辑用空值覆盖进程环境变量。

## 10. Youtu-RAG 当前需要重点检查的适配点

“同一个 Key 能调用三类模型”不代表当前 Youtu-RAG 版本只改环境变量就一定能运行。接手智能体应针对实际拉取的 commit 检查下列内容。

### 10.1 LLM

LLM 使用 OpenAI 兼容的 `chat/completions`，通常可以直接接入。至少验证：

- 普通对话；
- 流式输出；
- Function Calling / Tool Calling；
- 超时与 429 重试；
- Token 用量是否能记录。

### 10.2 Embedding

百炼 Embedding 使用标准 `/embeddings` 接口，但部分 Youtu-RAG 服务型 Embedding 实现会先请求 `{base_url}/model_id`。百炼没有该健康检查接口。

如果实际代码存在 `/model_id` 检查，不要把百炼 URL 配进去后反复重试，应选择以下一种实现：

1. 新增 `DashScopeEmbedding` / `OpenAICompatibleEmbedding` Provider，直接调用 `/embeddings`；或
2. 新增一个轻量本地适配服务，对 Youtu-RAG 暴露它需要的 `/model_id` 与向量接口，内部转调百炼。

第一种改法通常更清晰。实现后必须测试批量文本、空输入、超长文本、固定 1024 维和错误响应。

### 10.3 Reranker

Youtu-RAG 当前通用 Reranker 主要按单数 `/rerank` 处理，而百炼 `qwen3-rerank` 使用复数 `/reranks`。适配时应让完整端点原样保留，例如：

```python
if base_url.endswith(("/rerank", "/reranks")):
    endpoint = base_url
else:
    endpoint = f"{base_url.rstrip('/')}/rerank"
```

同时确认请求体可以透传可选 `instruct`，并从顶层 `results` 读取：

```json
{
  "index": 0,
  "relevance_score": 0.93
}
```

不得按旧版 `gte-rerank-v2` 的嵌套 `output.results` 格式解析 `qwen3-rerank`。

## 11. 推荐的配置封装

不要让业务代码在各处直接读取环境变量。建议建立统一配置对象：

```python
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class BailianConfig:
    api_key: str
    workspace_id: str
    region: str = "cn-beijing"

    @property
    def compatible_base_url(self) -> str:
        return (
            f"https://{self.workspace_id}.{self.region}.maas.aliyuncs.com/"
            "compatible-mode/v1"
        )

    @property
    def rerank_url(self) -> str:
        return (
            f"https://{self.workspace_id}.{self.region}.maas.aliyuncs.com/"
            "compatible-api/v1/reranks"
        )


def load_bailian_config() -> BailianConfig:
    api_key = os.getenv("Qianwen_api_key")
    workspace_id = os.getenv("Qianwen_workspace_id")

    if not api_key:
        raise RuntimeError("缺少 Qianwen_api_key")
    if not workspace_id:
        raise RuntimeError("缺少 Qianwen_workspace_id")

    return BailianConfig(
        api_key=api_key.strip(),
        workspace_id=workspace_id.strip(),
    )
```

日志对象、`repr()`、调试页面和 API 状态接口都不得返回 `api_key` 字段。

## 12. 超时、重试与错误处理

建议基础策略：

| 情况 | 处理方式 |
|---|---|
| 400 | 检查模型名、参数结构、Embedding 维度和输入长度，不盲目重试 |
| 401 | 检查 Key 是否有效，但不要打印 Key，不重试 |
| 403 | 检查业务空间和模型权限，不重试 |
| 404 | 优先检查地域、Workspace、`compatible-mode`/`compatible-api`、`rerank`/`reranks` |
| 429 | 指数退避并加入随机抖动，最多重试 2～3 次 |
| 5xx | 短暂指数退避，最多重试 2～3 次 |
| 网络超时 | 允许有限重试，保留可观测错误信息 |

推荐超时起点：

```text
LLM：60～120秒
Embedding：30～60秒
Reranker：30秒
```

日志允许包含：模型名、端点域名、HTTP 状态码、请求 ID、耗时、候选数、Token 用量。日志禁止包含：Key、完整 Authorization 请求头、用户敏感原文和未经脱敏的完整请求体。

## 13. 推荐开发顺序

接手智能体按以下顺序工作，不要一开始同时调试三条链路：

1. 只检查 `Qianwen_api_key` 是否存在，不显示值。
2. 获取并配置 `Qianwen_workspace_id`。
3. 独立运行 LLM 最小测试。
4. 独立运行 Embedding 最小测试，并确认输出正好是 1024 维。
5. 独立运行 Reranker 最小测试，并确认 `results` 位于响应顶层。
6. 适配 Youtu-RAG 的 LLM Provider。
7. 适配 Embedding `/embeddings`，处理可能存在的 `/model_id` 健康检查。
8. 适配 Reranker `/reranks` 和 `instruct`。
9. 构建小规模知识库，跑通“向量召回 → 重排 → LLM生成”。
10. 最后加入监控、重试、费用统计和本地降级方案。

## 14. 交付验收清单

- [ ] 项目和 Git 历史中不存在真实 API Key。
- [ ] 代码只通过 `Qianwen_api_key` 读取密钥。
- [ ] 新终端能够读取该变量，旧终端读取失败时有清晰提示。
- [ ] 已配置正确的 `Qianwen_workspace_id` 和北京地域。
- [ ] `qwen-plus` 普通对话和 Tool Calling 测试通过。
- [ ] `text-embedding-v4` 输出固定为 1024 维。
- [ ] 文档和查询使用相同 Embedding 模型及维度。
- [ ] `qwen3-rerank` 使用 `/compatible-api/v1/reranks`。
- [ ] Reranker 从顶层 `results` 读取结果。
- [ ] 消费决策场景的英文 `instruct` 已支持配置化。
- [ ] 401/403 不自动重试，429/5xx 使用有限指数退避。
- [ ] 日志和监控页面不会泄露密钥或 Authorization 请求头。
- [ ] 更换 Embedding 模型或维度时会强制重建向量索引。

## 15. 官方资料

- [获取与配置百炼 API Key](https://help.aliyun.com/zh/model-studio/get-api-key/)
- [qwen-plus 模型说明](https://help.aliyun.com/zh/model-studio/qwen-plus)
- [百炼向量化 API](https://help.aliyun.com/zh/model-studio/embedding?disableWebsiteRedirect=true)
- [百炼文本排序 API](https://help.aliyun.com/zh/model-studio/text-rerank-api)
- [百炼模型价格](https://help.aliyun.com/zh/model-studio/model-pricing)

