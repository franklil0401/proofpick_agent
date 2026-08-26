# API 参数传递

## 概述

本文档详细说明 Youtu-RAG 系统中 API 参数的传递机制，包括前端请求构建、后端参数处理、API 调用的完整流程。

**适用范围**: 需要在对话过程中向智能体传递自定义变量（如用户信息、业务参数等）的场景。

**最后更新**: 2026-01-27

---

## 架构概览

### 数据流向

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│   前端组件       │ HTTP  │  后端服务        │ HTTP  │ 腾讯云 ADP API   │
│  (TypeScript)   │ ───>  │   (Python)      │ ───>  │                 │
└─────────────────┘       └─────────────────┘       └─────────────────┘
       Step 1                   Step 2                    Step 3
```

### 关键组件

| 组件 | 路径 | 职责 |
|------|------|------|
| 前端 API 服务 | `client/packages/adp-chat-component/src/service/api.ts` | 构建并发送 HTTP 请求 |
| 后端路由层 | `server/router/chat.py` | 接收请求、参数验证、添加服务端参数 |
| 核心业务层 | `server/core/chat.py` | 处理对话逻辑 |
| ADP 集成层 | `server/vendor/tcadp/tcadp.py` | 调用腾讯云 ADP API |

---

## 详细流程

### Step 1: 前端发起请求

#### 1.1 接口定义

**文件**: `client/packages/adp-chat-component/src/service/api.ts`

```typescript
export const sendMessage = async (
    params: object,
    options?: AxiosRequestConfig,
    apiPath?: string
): Promise<any> => {
    if (!apiPath) throw new Error('apiPath is required');
    
    const _options = {
        responseType: 'stream',
        adapter: 'fetch',
        timeout: 1000 * 600,
        ...options,
    } as AxiosRequestConfig;
    
    return httpService.post(apiPath, params, _options);
};
```

#### 1.2 请求参数结构

**类型定义**: `client/packages/adp-chat-component/src/model/type.ts`

```typescript
interface ChatMessageRequest {
    Query: string;                    // 必填: 用户输入的消息内容
    ApplicationId: string;            // 必填: 智能体应用 ID
    ConversationId?: string;          // 可选: 会话 ID (新会话为空)
    SearchNetwork?: boolean;          // 可选: 是否启用联网搜索 (默认 true)
    CustomVariables?: Record<string, any>;  // 可选: 自定义变量
}
```

#### 1.3 调用示例

```typescript
// 场景: 用户发送消息并传递业务参数
const response = await sendMessage({
    Query: "帮我查询最近的订单",
    ApplicationId: "app-123456",
    ConversationId: conversationId || undefined,
    SearchNetwork: true,
    CustomVariables: {
        user_level: "VIP",
        order_type: "recent",
        page_size: 10
    }
}, {}, '/chat/message');
```

**参数说明**:

- `CustomVariables`: 键值对对象，值可以是字符串、数字、布尔值或嵌套对象
- 前端传递的参数会原样转发到后端

---

### Step 2: 后端处理请求

#### 2.1 参数解析

**文件**: `server/router/chat.py`

```python
from sanic.views import HTTPMethodView
from sanic_restful_api import reqparse
from router import login_required

class ChatMessageApi(HTTPMethodView):
    @login_required
    async def post(self, request: Request):
        # 使用 reqparse 解析 JSON 请求体
        parser = reqparse.RequestParser()
        parser.add_argument("Query", type=str, required=True, location="json")
        parser.add_argument("ConversationId", type=str, location="json")
        parser.add_argument("ApplicationId", type=str, location="json")
        parser.add_argument("SearchNetwork", type=bool, default=True, location="json")
        parser.add_argument("CustomVariables", type=dict, default={}, location="json")
        
        args = parser.parse_args(request)
        logging.info(f"ChatMessageApi: {args}")
```

**关键点**:

- `location="json"`: 从 JSON 请求体中提取参数
- `required=True`: 必填字段验证
- `default={}`: 为可选参数提供默认值

#### 2.2 添加服务端参数

```python
        # 获取智能体应用配置
        application_id = args['ApplicationId']
        vendor_app = app.get_vendor_app(application_id)
        
        # 获取当前登录用户信息
        from core.account import CoreAccount
        import json
        
        account = await CoreAccount.get(request.ctx.db, request.ctx.account_id)
        
        # 添加用户信息到 CustomVariables
        # 注意: 腾讯云 ADP 约定，字典类型的值必须 JSON 序列化为字符串
        args['CustomVariables']['account'] = json.dumps({
            "id": str(account.Id),
            "name": account.Name,
            "email": account.Email,
            "avatar": account.Avatar
        })
        
        logging.info(f"[ChatMessageApi] ApplicationId: {application_id},\n"
                     f"CustomVariables: {args['CustomVariables']},\n"
                     f"vendor_app: {vendor_app}")
```

**重要约定**:

- **字典值必须 JSON 序列化**: 如果 `CustomVariables` 的值是字典，必须使用 `json.dumps()` 转换为字符串，这是腾讯云 ADP API 的协议要求
- **安全考量**: 不要将敏感信息（密码、token、密钥等）添加到 `CustomVariables`

#### 2.3 调用核心业务层

```python
        # 返回流式响应
        async def streaming_fn(response):
            async for data in CoreChat.message(
                vendor_app,
                request.ctx.db,
                request.ctx.account_id,
                args['Query'],
                args['ConversationId'],
                args['SearchNetwork'],
                args['CustomVariables']  # 传递完整的自定义变量
            ):
                await response.write(data)
        
        return ResponseStream(
            streaming_fn, 
            content_type='text/event-stream; charset=utf-8'
        )
```

---

### Step 3: 调用腾讯云 ADP API

#### 3.1 请求构建

**文件**: `server/vendor/tcadp/tcadp.py`

```python
async def chat(
    self,
    account_id: str,
    query: str,
    conversation_id: str,
    is_new_conversation: bool,
    conversation_cb: ConversationCallback,
    search_network = True,
    custom_variables = {}
):
    # 构建请求负载
    payload = {
        "content": query,
        "bot_app_key": self.config['AppKey'],
        "session_id": conversation_id,
        "visitor_biz_id": account_id,
        "search_network": "enable" if search_network else "disable",
        "custom_variables": custom_variables,
        "incremental": True
    }
    
    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {self.config['AppSecret']}"
    }
    
    # 发送 HTTP POST 请求
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{self.config['ApiEndpoint']}/chat",
            json=payload,
            headers=headers
        ) as response:
            # 处理流式响应...
```

#### 3.2 实际请求体示例

```json
{
  "content": "帮我查询最近的订单",
  "bot_app_key": "your-app-key-from-adp-platform",
  "session_id": "conv-uuid-xxxx-xxxx",
  "visitor_biz_id": "user-123",
  "search_network": "enable",
  "custom_variables": {
    "user_level": "VIP",
    "order_type": "recent",
    "page_size": 10,
    "account": "{\"id\":\"123\",\"name\":\"张三\",\"email\":\"user@example.com\"}"
  },
  "incremental": true
}
```

**字段说明**:

- `content`: 用户消息
- `bot_app_key`: 在腾讯云 ADP 平台获取
- `session_id`: 会话标识符
- `visitor_biz_id`: 业务系统的用户 ID
- `custom_variables`: 自定义变量，注意 `account` 字段是 JSON 字符串

---

## 在智能体中使用参数

### 配置示例

在腾讯云 ADP 平台的智能体配置中，可通过 `{{变量名}}` 语法引用传递的参数:

```yaml
# 提示词模板
system: |
  你是一个智能客服助手。
  
  当前用户信息:
  - 用户等级: {{user_level}}
  - 用户详情: {{account}}
  
  请根据用户等级提供个性化服务。

# 工作流节点
workflow:
  - node: 查询订单
    action: api_call
    config:
      url: "https://api.example.com/orders"
      method: POST
      body: |
        {
          "user_id": "{{account.id}}",
          "email": "{{account.email}}",
          "order_type": "{{order_type}}",
          "limit": {{page_size}}
        }
```

**变量解析**:

- 字符串值: 直接使用 `{{变量名}}`
- 嵌套对象: 使用点号访问 `{{account.id}}`
- 数值: 不需要引号 `{{page_size}}`

---

## 安全注意事项

### SQL 注入防护

在处理用户输入时，必须使用参数化查询:

```python
# 错误示例 - 直接拼接用户输入
query = f"SELECT * FROM orders WHERE user_id = '{args['user_id']}'"  # 危险!

# 正确示例 - 使用参数化查询
from sqlalchemy import select
stmt = select(Order).where(Order.user_id == args['user_id'])
result = await db.execute(stmt)
```

**参考**: 项目安全规则文档 `<security_rules>` 部分

### 敏感信息过滤

不要将以下信息添加到 `CustomVariables`:

- 密码 (`password`)
- 密码盐值 (`password_salt`)
- 访问令牌 (`access_token`, `token`)
- API 密钥 (`secret_key`, `api_key`)
- 会话密钥 (`session_secret`)

```python
# 正确做法: 显式排除敏感字段
args['CustomVariables']['account'] = json.dumps({
    "id": str(account.Id),
    "name": account.Name,
    "email": account.Email,
    # 不包含: password, token, secret 等
})
```

### 输入验证

对动态 SQL 字段（如 `orderBy`, `sortBy`）使用白名单验证:

```python
ALLOWED_COLUMNS = {"id", "username", "email", "create_time"}
ALLOWED_DIRECTIONS = {"ASC", "DESC"}

if order_by not in ALLOWED_COLUMNS:
    raise ValueError(f"Invalid column: {order_by}")
if sort_direction.upper() not in ALLOWED_DIRECTIONS:
    raise ValueError(f"Invalid direction: {sort_direction}")
```

---

## 完整示例: 订单查询场景

### 场景描述

用户在聊天界面输入"查询我的订单"，系统需要:

1. 识别用户身份
2. 调用智能体
3. 智能体通过工作流调用订单 API
4. 返回订单信息

### 前端代码

```typescript
// 文件: client/packages/adp-chat-component/src/components/ChatWindow.vue
async function handleSendMessage(message: string) {
    const response = await sendMessage({
        Query: message,
        ApplicationId: "order-assistant-app",
        ConversationId: currentConversationId.value,
        SearchNetwork: false,
        CustomVariables: {
            order_status: "pending",  // 业务参数: 订单状态
            page_size: 20             // 业务参数: 分页大小
        }
    }, {}, '/chat/message');
    
    // 处理流式响应...
}
```

### 后端代码

```python
# 文件: server/router/chat.py
@login_required
async def post(self, request: Request):
    # ... 参数解析代码 ...
    
    # 获取用户信息
    account = await CoreAccount.get(request.ctx.db, request.ctx.account_id)
    
    # 添加用户 ID 供智能体调用订单 API 使用
    args['CustomVariables']['account'] = json.dumps({
        "id": str(account.Id),
        "name": account.Name,
        "email": account.Email
    })
    
    # 调用对话服务
    async for data in CoreChat.message(
        vendor_app,
        request.ctx.db,
        request.ctx.account_id,
        args['Query'],
        args['ConversationId'],
        args['SearchNetwork'],
        args['CustomVariables']
    ):
        yield data
```

### 智能体配置

```yaml
# 在腾讯云 ADP 平台配置
workflow:
  - node: 查询订单
    type: api_call
    config:
      url: "https://api.example.com/v1/orders"
      method: POST
      headers:
        Content-Type: "application/json"
      body: |
        {
          "user_id": "{{account.id}}",
          "email": "{{account.email}}",
          "status": "{{order_status}}",
          "limit": {{page_size}}
        }
    output: order_list

  - node: 格式化输出
    type: text_generation
    input: "{{order_list}}"
    prompt: "将以下订单信息友好地呈现给用户: {{order_list}}"
```

### 实际调用订单 API 的请求

```json
POST https://api.example.com/v1/orders
Content-Type: application/json

{
  "user_id": "123",
  "email": "user@example.com",
  "status": "pending",
  "limit": 20
}
```

---

## 故障排查

### 常见问题

#### 1. 参数未传递到智能体

**症状**: 在智能体中 `{{变量名}}` 显示为空或未定义

**排查步骤**:

1. 检查后端日志，确认 `CustomVariables` 已打印:
   ```python
   logging.info(f"CustomVariables: {args['CustomVariables']}")
   ```

2. 检查 ADP API 请求体，确认 `custom_variables` 字段存在:
   ```python
   logging.info(f"Payload: {json.dumps(payload, ensure_ascii=False)}")
   ```

3. 在 ADP 平台测试工具中手动传递相同参数，验证智能体配置是否正确

#### 2. 字典类型参数无法访问

**症状**: `{{account.id}}` 显示为空，但 `{{account}}` 能显示完整字符串

**原因**: 字典值未进行 JSON 序列化

**解决方案**:
```python
# 错误
args['CustomVariables']['account'] = {
    "id": str(account.Id),
    "name": account.Name
}

# 正确
args['CustomVariables']['account'] = json.dumps({
    "id": str(account.Id),
    "name": account.Name
})
```

#### 3. SQL 注入风险告警

**症状**: 安全扫描工具报告 SQL 注入风险

**解决方案**: 使用 SQLAlchemy ORM 的参数化查询:
```python
from sqlalchemy import select

# 正确: 参数化查询
stmt = select(User).where(User.id == user_id)
result = await db.execute(stmt)

# 错误: 字符串拼接
query = f"SELECT * FROM users WHERE id = '{user_id}'"  # 禁止
```

---

## 参考资料

### 相关代码文件

| 文件路径 | 说明 |
|---------|------|
| `client/packages/adp-chat-component/src/service/api.ts` | 前端 API 服务 |
| `client/packages/adp-chat-component/src/model/type.ts` | TypeScript 类型定义 |
| `server/router/chat.py` | 后端路由层 - 参数解析与处理 |
| `server/core/chat.py` | 核心业务层 - 对话逻辑 |
| `server/core/account.py` | 账户管理 - 用户信息获取 |
| `server/vendor/tcadp/tcadp.py` | 腾讯云 ADP API 集成 |

### 外部文档

- [腾讯云智能体开发平台 (ADP)](https://cloud.tencent.com/product/tcadp) - 官方产品页
- [腾讯云 ADP 平台控制台](https://adp.cloud.tencent.com/) - 智能体配置平台
- [对话端接口文档 (HTTP SSE)](https://cloud.tencent.com/document/product/1759/105561) - 官方 API 规范
- [Sanic 框架文档](https://sanic.dev/) - 后端 Web 框架
- [SQLAlchemy 文档](https://docs.sqlalchemy.org/) - ORM 框架

---

## 官方文档对比分析

### 腾讯云 ADP 官方 API 规范

根据腾讯云智能体开发平台官方文档（[HTTP SSE 接口文档](https://cloud.tencent.com/document/product/1759/105561)），`custom_variables` 字段的规范定义如下：

#### 官方规范要求

| 属性 | 说明 |
|------|------|
| **字段名** | `custom_variables` |
| **数据类型** | `map[string]string` |
| **是否必填** | 否 |
| **值类型限制** | **所有值必须是字符串类型** |

#### 数据格式要求

**合法示例**（所有值均为字符串）:
```json
{
  "custom_variables": {
    "UserID": "10220022",
    "user_level": "VIP"
  }
}
```

**非法示例**（值为数字或对象）:
```json
{
  "custom_variables": {
    "UserID": 10220022,           // 错误: 数字类型
    "user_info": {                 // 错误: 对象类型
      "id": "123",
      "name": "张三"
    }
  }
}
```

#### 嵌套 JSON 的正确方式

如需传递复杂对象，必须将其序列化为 JSON 字符串：

```json
{
  "custom_variables": {
    "Data": "{\"UserID\":\"10220022\",\"Score\":{\"Chinese\":89,\"Math\":98}}"
  }
}
```

**注意转义**: JSON 字符串中的引号需要转义为 `\"`。

#### 多值传递规范

对于知识库检索范围设置场景，如需传递多个值，使用竖线 `|` 分隔：

```json
{
  "custom_variables": {
    "user_group": "user1|user2|user3"
  }
}
```

---

### ACC 项目当前实现

#### 代码实现位置

**后端路由层**: `server/router/chat.py` (第 26 行)
```python
parser.add_argument("CustomVariables", type=dict, default={}, location="json")
```

**ADP 集成层**: `server/vendor/tcadp/tcadp.py` (第 91-105 行)
```python
async def chat(
    self,
    db: AsyncSession,
    account_id: str,
    query: str,
    conversation_id: str,
    is_new_conversation: bool,
    conversation_cb: ConversationCallback,
    search_network = True,
    custom_variables = {}  # 接收 dict 类型
):
    # ...
    param = {
        "content": query,
        "bot_app_key": self.config['AppKey'],
        "session_id": conversation_id,
        "visitor_biz_id": account_id,
        "search_network": "enable" if search_network else "disable",
        "custom_variables": custom_variables,  # 直接传递 dict
        "incremental": incremental,
    }
```

#### 当前实现的问题

| 问题点 | 说明 | 风险等级 |
|--------|------|----------|
| **类型不匹配** | 接收和传递的是 Python `dict` 类型，未强制值为字符串 | 中 |
| **缺少类型验证** | 未验证 `dict` 中的值是否为字符串类型 | 中 |
| **文档不一致** | README 示例中使用 `json.dumps()` 处理嵌套对象，但未在所有场景强制执行 | 低 |

#### 实际运行表现

根据项目 README（第 306 行）的示例代码：

```python
# README 中的示例
from core.account import CoreAccount
account = await CoreAccount.get(request.ctx.db, request.ctx.account_id)

# 使用 json.dumps 将字典转为字符串
args['CustomVariables']['account'] = json.dumps({
    "id": str(account.Id),
    "name": account.Name,
})
```

**现状**:
- 开发者需要**手动**记住对嵌套对象使用 `json.dumps()`
- 如果开发者直接传递字典（如 `{"id": 123, "name": "test"}`），代码不会报错，但可能与官方 API 规范不符

---

### 差异对比总结

| 对比项 | 腾讯云 ADP 官方规范 | ACC 项目当前实现 | 是否一致 |
|--------|---------------------|------------------|----------|
| **参数名称** | `custom_variables` | `custom_variables` | ✅ 一致 |
| **外层数据类型** | `map[string]string` | Python `dict` | ✅ 一致（映射关系） |
| **值类型限制** | **所有值必须为 `string`** | 无强制限制，接受任意类型 | ❌ 不一致 |
| **类型验证** | API 层面强制校验 | 无验证逻辑 | ❌ 缺失 |
| **文档说明** | 明确要求字符串类型 | 示例中使用 `json.dumps()`，但未强制 | ⚠️ 部分一致 |
| **嵌套对象处理** | 必须序列化为 JSON 字符串 | 需开发者手动调用 `json.dumps()` | ⚠️ 依赖开发者 |

---

### 潜在风险分析

#### 1. 数据类型不匹配风险

**场景**: 开发者在前端或后端传递数字、布尔值或对象

```python
# 错误用法（ACC 当前不会报错，但违反官方规范）
args['CustomVariables']['user_id'] = 123              # 数字
args['CustomVariables']['is_vip'] = True              # 布尔值
args['CustomVariables']['user_info'] = {              # 对象
    "id": "123",
    "name": "test"
}
```

**后果**:
- 腾讯云 ADP API 可能拒绝请求或忽略非字符串值
- 智能体工作流中无法正确引用参数（如 `{{user_id}}` 可能显示为空）

#### 2. 前后端类型不一致

**前端传递**（TypeScript）:
```typescript
CustomVariables: {
    page_size: 10,  // 数字类型
    is_active: true // 布尔类型
}
```

**后端接收**（Python）:
```python
args['CustomVariables']  
# {'page_size': 10, 'is_active': True}
# 直接传递给 ADP API，违反官方规范
```

#### 3. 缺少统一的类型转换层

**问题**: 每个开发者需要自己记住哪些字段需要 `json.dumps()`，容易遗漏或不一致。

---

### 改进建议

#### 方案一: 添加类型验证和自动转换（推荐）

在 `server/router/chat.py` 中添加验证和转换逻辑：

```python
def normalize_custom_variables(variables: dict) -> dict:
    """
    将 custom_variables 的所有值转换为字符串类型，符合腾讯云 ADP API 规范。
    
    规则:
    - 字符串: 保持不变
    - 数字/布尔值: 转换为字符串
    - 字典/列表: 使用 json.dumps() 序列化
    - None: 转换为空字符串
    """
    import json
    
    normalized = {}
    for key, value in variables.items():
        if isinstance(value, str):
            normalized[key] = value
        elif isinstance(value, (dict, list)):
            normalized[key] = json.dumps(value, ensure_ascii=False)
        elif value is None:
            normalized[key] = ""
        else:
            normalized[key] = str(value)
    
    return normalized


class ChatMessageApi(HTTPMethodView):
    @login_required
    async def post(self, request: Request):
        # ... 现有代码 ...
        
        # 添加类型转换
        args['CustomVariables'] = normalize_custom_variables(args['CustomVariables'])
        
        logging.info(f"[ChatMessageApi] Normalized CustomVariables: {args['CustomVariables']}")
        
        # ... 继续现有流程 ...
```

**优点**:
- 自动兼容各种类型，开发者无需手动转换
- 符合官方 API 规范
- 向后兼容现有代码

#### 方案二: 严格校验（适合新项目）

添加严格的类型校验，拒绝非字符串值：

```python
def validate_custom_variables(variables: dict):
    """
    严格校验 custom_variables 的值类型。
    
    如果发现非字符串类型的值，抛出异常。
    """
    for key, value in variables.items():
        if not isinstance(value, str):
            raise ValueError(
                f"custom_variables['{key}'] 的值必须是字符串类型，"
                f"当前类型为 {type(value).__name__}。"
                f"如需传递对象或数组，请使用 json.dumps() 转换。"
            )


class ChatMessageApi(HTTPMethodView):
    @login_required
    async def post(self, request: Request):
        # ... 现有代码 ...
        
        # 严格校验
        validate_custom_variables(args['CustomVariables'])
        
        # ... 继续现有流程 ...
```

**优点**:
- 强制开发者遵守规范
- 问题在早期暴露，避免运行时错误

**缺点**:
- 破坏向后兼容性
- 需要修改现有调用代码

#### 方案三: 更新文档和类型提示

在代码中添加详细的类型注解和文档字符串：

```python
from typing import Dict

class ChatMessageApi(HTTPMethodView):
    @login_required
    async def post(self, request: Request):
        parser = reqparse.RequestParser()
        parser.add_argument(
            "CustomVariables", 
            type=dict, 
            default={}, 
            location="json",
            help="自定义变量（键值对），所有值必须为字符串类型。"
                 "如需传递对象或数组，请使用 json.dumps() 序列化。"
                 "参考: https://cloud.tencent.com/document/product/1759/105561"
        )
        # ...
```

---

### 推荐实施方案

**阶段一**: 立即实施（不破坏兼容性）
1. 添加 `normalize_custom_variables()` 函数（方案一）
2. 在 `server/router/chat.py` 中调用转换函数
3. 添加日志记录转换前后的值，便于调试

**阶段二**: 文档更新
1. 在技术文档中明确说明类型要求
2. 更新 README 示例，统一使用转换函数
3. 在前端 TypeScript 类型定义中添加注释说明

**阶段三**: 长期优化（可选）
1. 考虑在前端层面就进行类型转换
2. 添加单元测试覆盖各种类型转换场景
3. 如果确定无兼容性问题，可切换到严格校验模式

---

## 贡献与反馈

如发现文档问题或需要补充内容，请在项目 GitHub 仓库提交 Issue:

- GitHub 仓库: [https://github.com/TencentCloudADP/adp-chat-client](https://github.com/TencentCloudADP/adp-chat-client)
- 问题反馈: [https://github.com/TencentCloudADP/adp-chat-client/issues](https://github.com/TencentCloudADP/adp-chat-client/issues)

---

**许可证**: Apache License 2.0  
**版权所有**: Tencent Cloud ADP Team
