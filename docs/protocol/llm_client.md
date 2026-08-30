# LLM Client 使用示例

## 1. 文档用途

本文档给使用 shared LLM client 的调用方一个最小参考：

- 怎么初始化 `LLMClientManager`
- 怎么创建 `LLMSession`
- 怎么发起 `json_text` 请求
- 怎么发起 `tool_calling` 请求
- 怎么看返回结果
- 怎么新增一个 provider

## 2. 入口

入口如下：

```python
from core.llm import (
    LLMClientManager,
    SessionCreateRequest,
    ToolDefinition,
    TurnRequest,
    UserTurnMessage,
)
```

其中：

- `LLMClientManager` 负责读取 `models.yaml` 并创建 session
- `SessionCreateRequest` 用于创建一个新 session
- `TurnRequest` 用于在已有 session 上发起一次模型调用
- `UserTurnMessage` 是单轮用户输入
- `ToolDefinition` 用于定义 tool calling 模式下可用的工具

## 3. 初始化 Client

LLMClientManager会直接从默认 `configs/models.yaml` 初始化：

```python
from core.llm import LLMClientManager

manager = LLMClientManager.from_default_models_yaml()
```

## 4. 创建 Session

每个 episode ，应该创建一个新的 `LLMSession`。

```python
from core.llm import LLMClientManager, SessionCreateRequest

manager = LLMClientManager.from_default_models_yaml()

session = manager.create_session(
    SessionCreateRequest(
        model_id="gpt5_4",
        system_prompt="You are a helpful GUI agent.",
        image_history_window=3,
    )
)
```

其中 `image_history_window=3` 表示：除了当前 step 的截图外，还会在历史消息里额外保留最近 3 个 step 的截图，便于模型做前后对比。

**不要跨 episode 复用同一个 session**

## 5. 发起 `json_text` 请求

最简单的文本请求如下：

```python
from core.llm import TurnRequest, UserTurnMessage

response = session.run_turn(
    TurnRequest(
        message=UserTurnMessage(
            text="Reply with exactly: pong",
        ),
        response_mode="json_text",
        timeout_seconds=30,
    )
)
```

如果要附带一张截图：

```python
response = session.run_turn(
    TurnRequest(
        message={
            "text": "Describe what is visible in this screenshot.",
            "image_path": "/abs/path/to/screenshot.png",
        },
        response_mode="json_text",
    )
)
```

说明：

- `image_path` 必须是绝对路径
- `response_mode` 目前只支持 `json_text` 和 `tool_calling`

## 6. 发起 `tool_calling` 请求

这里的 `ToolDefinition` 是 shared 层规定的统一格式。

调用方只需要按 `ToolDefinition` 的字段传入：

- `name`
- `description`
- `parameters`

各个 Adapter 会在把 `ToolDefinition` 转成各 provider 需要的请求格式。

先定义 tools：

```python
tools = [
    ToolDefinition(
        name="tap",
        description="Tap a UI element.",
        parameters={
            "type": "object",
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
            "required": ["x", "y"],
        },
    ),
]
```

再发起请求：

```python
response = session.run_turn(
    TurnRequest(
        message={
            "text": "Tap the Settings icon.",
            "image_path": "/abs/path/to/screenshot.png",
        },
        response_mode="tool_calling",
        tools=tools,
        tool_choice="required",
        timeout_seconds=30,
    )
)
```

说明：

- `tool_calling` 模式下，`tools` 必填
- `tool_choice` 可选；常见值是 `auto` / `none` / `required`

## 7. 处理返回结果

统一返回对象是 `LLMResponse`。

最常见的处理方式：

```python
if response.error:
    print("request failed:", response.error)
else:
    print("provider:", response.provider)
    print("text:", response.text)
    print("tool_calls:", response.tool_calls)
```

常用字段：

- `response.text`: 文本响应
- `response.tool_calls`: tool calling 返回的工具调用列表
- `response.error`: 请求失败时的错误信息
- `response.provider`: 实际使用的 provider
- `response.raw_response`: provider 原始响应，便于排查问题

如果是 tool calling：

```python
tool_calls = response.tool_calls or []
for call in tool_calls:
    print(call.name)
    print(call.arguments_json)
```

## 8. 一个完整最小示例

```python
from core.llm import LLMClientManager, SessionCreateRequest, TurnRequest, UserTurnMessage

manager = LLMClientManager.from_default_models_yaml()

session = manager.create_session(
    SessionCreateRequest(
        model_id="gpt5_4",
        system_prompt="You are a concise assistant.",
        image_history_window=3,
    )
)

response = session.run_turn(
    TurnRequest(
        message=UserTurnMessage(text="Reply with exactly: pong"),
        response_mode="json_text",
        timeout_seconds=30,
    )
)

if response.error:
    raise RuntimeError(response.error)

print(response.text)
```

## 9. 如何新增一个 Provider

### 9.1 实现 Adapter

在 `core/llm/providers/` 下新增一个 adapter 文件，并实现一个继承 `ProviderAdapter` 的类。

最小骨架如下：

```python
from core.llm.providers.base import ProviderAdapter, ProviderRequest, ProviderResult


class MyProviderAdapter(ProviderAdapter):
    provider_name = "my_provider"
    supported_response_modes = {"tool_calling", "json_text"}

    def invoke(self, request: ProviderRequest) -> ProviderResult:
        api_key = request.credentials.api_key
        base_url = request.credentials.base_url
        model_name = request.model_spec.model_name
        parameters = request.parameters
        messages = request.messages

        # 1. 把统一 messages 转成 provider 自己的请求格式
        # 2. 发起 HTTP 请求
        # 3. 解析返回
        # 4. 转成统一的 ProviderResult

        return ProviderResult(
            text="...",
            tool_calls=[],
            finish_reason="stop",
            usage={},
            raw_response={},
        )
```

约定：

- `provider_name` 必须和 `models.yaml` 中的 `provider` 字段一致
- `invoke()` 必须返回 `ProviderResult`
- `request.credentials` 里提供已经解析好的 `api_key` 和 `base_url`
- `request.parameters` 里是共享层统一传下来的可选参数

### 9.2 导出并注册 Adapter

需要改两处：

1. 在 `core/llm/providers/__init__.py` 中导入并导出新的 adapter
2. 在 `LLMClientManager.build_default_provider_registry()` 中注册新的 adapter

### 9.3 在 `models.yaml` 中声明模型

例如：

```yaml
models:
  my_model:
    provider: my_provider
    model_name: my-model-name
    api_key_env: MY_PROVIDER_API_KEY
    base_url_env: MY_PROVIDER_BASE_URL
    temperature: 0.0
```

说明：

- `provider` 必须和 adapter 的 `provider_name` 完全一致
- `base_url` 或 `base_url_env` 至少提供一个
- `temperature`、`max_output_tokens`、`top_p` 都是可选的

## 10. 参考代码

如果想看真实调用方式，可以参考：

- `tests/smoke_llm_config.py`
- `platforms/ios/agent/planners/base_planner.py`
- `platforms/macos/host/agent/planners/base_planner.py`
