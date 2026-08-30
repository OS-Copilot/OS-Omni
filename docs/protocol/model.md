# Model 协议

## 1. 文档用途

本文档定义模型注册表格式，以及 `models.yaml` 与 `.env` 的职责边界。

## 2. 配置方式

模型配置分为两层：

- `models.yaml`: 公开、可提交到仓库的模型定义
- `.env`: 本地私密配置，例如 API key 

## 3. 文件格式

默认值约定：

- 只有文档中明确写出的字段才有默认值
- 未明确写默认值的字段，表示协议层不设默认值

模型注册表使用 `YAML` 定义。

路径：

```text
configs/models.yaml
```

## 4. ModelRegistry schema

### 4.1 顶层字段

| 字段 | 类型 | 必填 | 说明 | 约束 |
|---|---|---:|---|---|
| `models` | object | 是 | 模型注册表 | key 为 `model_id`，value 为模型配置对象 |

### 4.2 `models.<model_id>` 对象

| 字段 | 类型 | 必填 | 说明 | 约束 |
|---|---|---:|---|---|
| `provider` | string | 是 | 模型提供方 | 当前内置支持 `openai` / `google` / `intern` / `taobao` |
| `model_name` | string | 是 | 实际请求时传给 provider 的模型名 | 非空字符串 |
| `api_key_env` | string | 是 | 保存 API key 的环境变量名 | 非空字符串 |
| `base_url` | string | 否 | 固定 base URL | 非空字符串 |
| `base_url_env` | string | 否 | 保存 base URL 的环境变量名 | 非空字符串 |
| `temperature` | number | 否 | 默认温度参数 | 数值 |
| `max_output_tokens` | integer | 否 | 默认最大输出 token | 数值 |
| `top_p` | number | 否 | 默认 `top_p` | 数值 |
| `metadata` | object | 否 | 附加元数据 | 开放对象 |

说明：

- `model_id` 由 `models` 对象的 key 表示，不在 value 中重复定义
- `api_key_env` 记录的是环境变量名，不是 API key 本身
- `base_url` 和 `base_url_env` 至少要提供一个，也可以都填；若都填则 `base_url` 优先
- `provider` 必须在代码中的 provider registry 里有对应实现，否则该模型不可用
- `metadata` 当前不参与运行时行为，只作为预留元数据

新增 provider 的实现方式见 `llm_client.md`。

## 5. `.env` 约定

`.env` 中存放运行时实际使用的环境变量值。例如：

```env
OPENAI_API_KEY=sk-xxxx
OPENAI_BASE_URL=https://api.openai.com/v1
GOOGLE_API_KEY=xxxx
```

说明：

- 程序会尝试通过 `python-dotenv` 自动加载 `.env`
- 若未安装 `python-dotenv`，则需要由外部环境提前注入这些变量

## 6. 示例

### 6.1 `models.yaml`

```yaml
models:
  gpt5_4:
    provider: openai
    model_name: gpt-5.4
    api_key_env: OPENAI_API_KEY
    base_url_env: OPENAI_BASE_URL
    temperature: 0.0

  gemini_3_flash:
    provider: google
    model_name: gemini-3-flash-preview
    api_key_env: GOOGLE_API_KEY
    base_url_env: GOOGLE_BASE_URL

  internvl3_5:
    provider: intern
    model_name: internvl3.5-241b-a28b
    api_key_env: INTERN_API_KEY
    base_url_env: INTERN_API_URL
```

## 7. 公共 `validate()`

程序读取 `models.yaml` 后，会自动执行公共 `validate()`。

只有通过校验的 `model_id` 才允许在 `execution.yaml` 中使用。

公共 `validate()` 需要检查：

- `models` 是否为 object
- 每个 `model_id` 是否唯一且格式合法
- 每个模型是否包含 `provider`、`model_name`、`api_key_env`
- 每个模型是否至少包含 `base_url` 或 `base_url_env`
- `temperature`、`max_output_tokens`、`top_p` 如果存在，是否为数值
- `metadata` 如果存在，是否为 object
