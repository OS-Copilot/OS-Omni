# Artifacts 协议

## 1. 文档用途

本文档定义 benchmark 运行产物的目录结构，以及结果产物和过程产物的边界。

## 2. 目录结构

严格按照如下目录结构：

```text
results/
  <model_id>/
    <platform>/
      <execution_name>_<timestamp>/
        <task_id>_<timestamp>/
            args.json
            trajectory.jsonl
            result.json
            runner.log 
            screenshots/
            	  step_1.png
  							step_2.png
 							  final.png
```

## 3. 产物

### 3.1 `args.json`

记录本次 task run 的输入快照。

这个文件放在最终 task 结果目录下，与 `trajectory.json` 同级。

字段包含：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `created_at` | string | 是 | 生成时间，建议使用 ISO 8601 |
| `task` | object | 是 | 当前运行的`task.yaml` 的路径和快照 |
| `execution` | object / null | 否 | 当前运行的`execution.yaml` 的路径和快照 |
| `model` | object | 是 | `configs/models.yaml` 中当前 `model_id` 对应模型配置的路径和快照 |
| `platform_config` | object / null | 否 | 当前运行的`configs/<platform>.yaml` 的路径和快照 |

其中：

- `task`、`execution`、`model`、`platform_config` 这四个对象下只应包含 `path` 和 `snapshot` 两个字段
- `task.snapshot` 应保存本次运行对应的原始 `task.yaml`
- `execution.snapshot` 应保存本次运行对应的原始 `execution.yaml`
- `model.snapshot` 应只保存 `configs/models.yaml` 中当前运行 model 的那一段，而不是整份文件
- `platform_config.snapshot` 应保存当前平台的运行配置，例如 `configs/ios.yaml` 或 `configs/macos.yaml`

**`core/artifacts/run_args.py`已经实现了相关功能，可以直接调用来完成 `args.json` 的创建**

示例：

```json
{
  "created_at": "2026-03-19T08:12:30.123456+00:00",
  "task": {
    "path": "tasks/v1/ios/contacts_add_contact_card.yaml",
    "snapshot": {
      "task_id": "ios.contacts.add_contact_card",
      "platform": "ios",
      "instruction": "Add a contact card ..."
    }
  },
  "execution": {
    "path": "executions/v1/ios.yaml",
    "snapshot": {
      "tasks": ["tasks/v1/ios/contacts_add_contact_card.yaml"],
      "models": ["gpt_4o"]
    }
  },
  "model": {
    "path": "configs/models.yaml",
    "snapshot": {
      "provider": "openai",
      "model_name": "gpt-4o"
    }
  },
  "platform_config": {
    "path": "configs/ios.yaml",
    "snapshot": {
      "appium_host": "127.0.0.1",
      "appium_port": 4723
    }
  }
}
```

### 3.2 `trajectory.jsonl`

每一个step的过程记录

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `step_index` | integer | 是 | 1-based 步号 |
| `timestamp` | string | 是 | ISO 8601（含时区） |
| `observation` | object | 是 | 本步观察结果 |
| `prompt` | string | 是 | 发给 LLM 的输入 |
| `llm_response` | string | 是 | LLM 原始输出 |
| `llm_reasoning` | object\|null | 否 | 模型可见 reasoning / thought 摘要；Responses API 等支持时输出 |
| `action_parse` | object | 是 | LLM 输出解析结果 |
| `action_execution` | object\|null | 是 | action 执行结果；如果本步未进入执行阶段，可为 `null` |
| `latency_ms` | integer\|number | 是 | 本步总耗时，单位毫秒 |

示例：

```json
{
  "step_index": 1,
  "timestamp": "2026-03-19T16:12:30.123456+08:00",
  "observation": {
    "screenshot_path": "folder/path",
    "a11y_tree": {},
    "addition_info": {}
  },
  "prompt": "...",
  "llm_response": "...",
  "llm_reasoning": {
    "api_mode": "responses",
    "summaries": ["I should tap n25 next."],
    "reasoning_tokens": 31
  },
  "action_parse": {
    "status": "SUCCESS",
    "action": {
      "type": "tap",
      "target": "n25"
    },
    "error": null
  },
  "action_execution": {
    "status": "SUCCESS",
    "result": "Tapped at (340, 434)",
    "error": null
  },
  "latency_ms": 120
},
{
  ...
}

```

### 3.3 `result.json`

task 最终结果摘要。字段包含：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `task_id` | string | 是 | 当前 task 的唯一标识 |
| `platform` | string | 是 | 当前运行平台，例如 `ios`、`macos` |
| `model_id` | string | 是 | 本次运行使用的模型 ID |
| `status` | string | 是 | task 最终状态， `PASS`、`FAIL`、`ERROR` |
| `started_at` | string | 是 | task 开始时间，使用 ISO 8601（含时区） |
| `ended_at` | string | 是 | task 结束时间，使用 ISO 8601（含时区） |
| `steps_taken` | integer | 是 | 实际执行的 step 数 |
| `latency_ms` | integer\|number | 是 | task 总耗时，单位毫秒 |
| `episode_result` | object | 是 | 本次 episode 的直接运行结果 |
| `initializer` | object\|null | 是 | initializer 最终结果；如果当前 task 未配置 initializer，则为 `null` |
| `evaluation` | object\|null | 是 | evaluator 最终结果；如果当前 task 未配置 evaluator，则为 `null` |
| `final_observation` | object | 是 | 记录运行结束时的观察结果 |

示例：

```json
{
  "task_id": "ios.settings.open_settings",
  "platform": "ios",
  "model_id": "gpt_5_4",
  "status": "PASS",
  "started_at": "2026-03-19T16:12:10.000000+08:00",
  "ended_at": "2026-03-19T16:12:35.000000+08:00",
  "steps_taken": 2,
  "latency_ms": 222,
  "episode_result": {
    "status": "PASS",
    "message": "Successfully opened the Settings app"
  },
  "initializer": {
    "status": "PASS",
    "message": null,
    "metadata": {}
  },
  "evaluation": {
    "status": "PASS",
    "message": null,
    "metadata": {}
  },
  "final_observation": {
    "screenshot_path": "PASS",
    "a11y_tree": null,
    "addition_info": {}
  },
}
```

### 3.4 `screenshots/`

保存逐步截图和最终截图。

文件名必须以 `step_` + `index`开头，例如：

- `step_1.png`
- `step_2.png`

step index 从 1 开始，按执行顺序递增

**在运行终止后，需要保存最终截图`final.png`**

screenshots文件结构示例：

```text
screenshots/
  step_1.png
  step_2.png
  final.png
```

### 3.5 ` runner.log `

保存终端输出，便于复盘调试。

可以不做
