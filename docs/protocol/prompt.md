# Prompt 协议

所有平台的Prompt都应该通过`core/prompt/builders.py`来生成，提供以下两个函数：

- `build_system_prompt`
- `build_step_prompt`

## 函数说明

### `build_system_prompt(...)`

| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `task` | string | 是 | 当前任务目标 |
| `platform` | string | 是 | 当前平台名称，例如：`Android `、`iOS` |
| `observation_type` | string | 是 | 只能是 `screenshot_only`、`a11y_tree_only`、`screenshot_and_a11y_tree`（对应execution.yaml） |
| `tool_calling` | boolean | 是 | 是否使用 tool calling；`False` 时会拼接 `ACTION_RULES`，`True` 时不拼接 `ACTION_RULES`，改为使用工具约束文案 |
| `action_rules` | string | 否 | 当前平台对应的动作规则文本；仅在 `tool_calling=False` 时需要；会直接拼进 prompt 里的 `ACTION_RULES = ...` |
| `extra_system_prompt` | string | 否 | 允许外部直接传入一段字符串，原样拼接到 system prompt 中，一般不传 |

### `build_step_prompt(...)`

| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `observation_type` | string | 是 | 只能是 `screenshot_only`、`a11y_tree_only`、`screenshot_and_a11y_tree`（对应execution.yaml） |
| `ui_context` | string | 否 | 在 `a11y_tree_only` / `screenshot_and_a11y_tree` 下会被拼进 step prompt |
| `extra_step_prompt` | string | 否 | 允许外部直接传入一段字符串，原样拼接到 step prompt 中，一般不传 |

## 调用示例

```python
from prompt_builders import build_step_prompt, build_system_prompt

system_prompt = build_system_prompt(
    task="Open Settings and enable Wi-Fi.",
    platform="Android",
    observation_type="a11y_tree_only",
    tool_calling=False,
    action_rules='{"action_type":"tap | swipe | input_text | back | home","target":"string or null","params":{}}',
    extra_system_prompt="The current app package is com.android.settings.",
)

step_prompt = build_step_prompt(
    observation_type="screenshot_ui_context",
    ui_context='{"id":"n1","type":"Switch","text":"Wi-Fi","checked":false}',
    extra_step_prompt="If a permission dialog is visible, handle it before continuing.",
)
```

