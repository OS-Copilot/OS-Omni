# Execution 协议

## 1. 文档用途

本文档定义一次实验的执行文件格式。

## 2. 文件格式

execution 配置使用 `YAML` 定义。

路径：

```text
executions/<name>.yaml
```

## 3. ExecutionSpec schema

### 3.1 顶层字段

| 字段 | 类型 | 必填 | 说明 | 约束 |
|---|---|---:|---|---|
| `tasks` | array[string] | 是 | task 文件路径列表 | 非空数组；每个元素都必须是合法 task 文件路径 |
| `models` | array[string] | 是 | `model_id` 列表 | 每个元素都必须能在项目默认模型注册表中找到 |
| `action_mode` | string | 否 | 本次运行的动作输出模式 | 见 4.1 |
| `observation_mode` | string | 否 | 本次运行向模型暴露的 observation 形式 | 见 4.2 |
| `history_window` | integer | 否 | agent 可见历史窗口 | 见 4.3 |
| `metadata` | object | 否 | 执行级元数据 | 开放对象，不会被平台消费 |

### 3.2 `tasks`

`tasks` 直接使用字符串数组。

数组中的每个元素都是一个 task 文件路径。

说明：

- 一个 execution 可以直接包含多个 task
- 所有 task 的 `platform` 必须一致

## 4. 运行时可变配置

### 4.1 `action_mode`

`action_mode` 用于定义本次 execution 的动作输出模式。

支持的值：

- `code_adapter`

### 4.2 `observation_mode`

`observation_mode` 用于定义本次运行向模型提供的 observation 形式。

支持的值：

- `screenshot_only`
- `a11y_tree_only`
- `screenshot_and_a11y_tree`

### 4.3 `history_window`

`history_window` 用于定义每次向 LLM 发起请求时，保留多少个历史 step。

说明：

- 一个 history step 可能包含多条消息
- 在内部文本响应模式下，一个 step 至少包含：
  - 当时该 step 的 `user` 消息，内容是当时的 observation / step prompt
  - 当时模型返回的 `assistant` 消息
- 在内部 tool-calling 响应模式下，一个 step 的 history 至少还需要能表达：
  - 模型发起的 tool call
  - tool execution output
- `messages` 的第一条永远是 `system` 消息，也就是 system prompt；它不受 `history_window` 影响
- 假设程序已经运行了 `N` 个 step，那么在第 `k+1` 个 step 请求 LLM 时，请求内容应为：
  - `system prompt`
  - 最近 `history_window` 个已完成 step 的 history
  - 当前 step 的 `user` 消息
- 更早的历史 step 会被丢弃，不再发送给 模型

`history_window` 决定模型可见的历史步数。

## 5. 平台运行时配置

平台运行时配置不写在 `execution.yaml` 。

程序应根据 `tasks` 中所有 task 对应的平台，从`configs/`目录下读取该平台的 runtime 配置文件。

各平台自己设计自己的运行时配置文件。

例如：

- iOS: `configs/ios.yaml`
- macOS: `configs/macos.yaml`

## 6. 展开语义

ExecutionSpec 进入 各平台的runner 后，应当按下面的逻辑展开：

- `tasks x models`

- `tasks` 中所有 task 的 `platform` 必须一致
- 一个 execution 只允许单平台运行

## 7. 单任务 execution 示例

```yaml
tasks:
  - tasks/v1/ios/contacts_add_contact_card.yaml
models:
  - gpt5_4
  - gemini_3_flash
action_mode: code_adapter
observation_mode: screenshot_and_a11y_tree
metadata:
  experiment_name: ios_single_task_debug
```

## 8. 多任务 execution 示例

```yaml
tasks:
  - tasks/v1/ios/contacts_add_contact_card.yaml
  - tasks/v1/ios/calendar_update_and_create_followup.yaml
  - tasks/v1/ios/reminders_manage_seeded_list.yaml
models:
  - gpt5_4
  - internvl3_5
  - gemini_3_flash
action_mode: code_adapter
observation_mode: screenshot_and_a11y_tree
metadata:
  experiment_name: ios_core_tasks_main
```

## 9. 公共 `validate()`

程序读取 `execution.yaml` 后，会自动执行公共 `validate()`。

只有 execution 通过公共校验后，才会进入平台代码。

公共 `validate()` 需要检查：

- 必填字段是否存在
- `tasks` 是否为非空字符串数组
- 每个 task 文件是否存在且合法
- `models` 是否为非空字符串数组
- 每个 `model_id` 是否存在于项目默认模型注册表
- `action_mode`、`observation_mode`、`history_window` 如果存在，格式是否合法
- `metadata` 如果存在，是否为 object
- `tasks` 中所有 task 的 `platform` 是否一致
