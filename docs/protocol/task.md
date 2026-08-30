# Task 协议

本文档定义 benchmark 中单任务文件的格式。

任务文件使用 `YAML` 定义，主要作为任务接入方、平台端、评估端之间的接口说明。

## 1. 单任务文件 schema

单任务文件下文统一称为 `TaskSpec`。

### 1.1 顶层字段

| 字段 | 类型 | 必填 | 说明 | 约束 |
|---|---|---:|---|---|
| `task_id` | string | 是 | 任务唯一标识 | 推荐匹配 `^[a-z0-9][a-z0-9._/-]*$` |
| `platform` | string | 是 | 任务目标平台 | `ios` / `macos` / `android` / `windows` / `linux` / `web` |
| `instruction` | string | 是 | 任务描述 | 非空字符串 |
| `timeout_seconds` | number | 是 | 任务总预算 | `> 0` |
| `init` | object | 否 | 任务开始前的初始化逻辑 | 见 1.2 |
| `evaluation` | object | 是 | 任务评估规则 | 见 1.3 |
| `limits` | object | 是 | 执行预算 | 见 1.4 |
| `metadata` | object | 否 | 附加元数据 | 协议层不校验具体键；部分平台运行时会按约定读取其中的字段 |

### 1.2 `init`

当前版本采用代码 initializer 方案。

如果 task 定义了 `init`，平台在进入 step loop 之前必须先执行一次 initializer。

`init` 用于：

- 准备任务所需的初始环境
- 向虚拟机、模拟器或浏览器注入前置数据
- 执行任务开始前必须完成的一段初始化代码

具体示例实现可参考 `init.md`。

####  `init` 字段

| 字段 | 类型 | 必填 | 说明 | 约束 |
|---|---|---:|---|---|
| `initializer_id` | string | 是 | initializer 加载标识 | 必须为 Python import path，见 1.2.2 |
| `params` | object | 否 | 传给 initializer 的参数 | 开放对象 |

### 1.3 `evaluation`

当前版本采用代码 evaluator 方案。

每个 task 通过 `evaluator_id` 绑定一个 Python evaluator。

`evaluator_id` 直接使用 Python import path，不额外引入 registry。

各平台可以用自己的方式完成评估，例如查 UI、查 DOM、查 DB、查文件系统、做滚动或其他验证动作。

只统一 evaluator 的调用方式和返回格式。

传给 evaluator 的 `context` 具体字段由平台自己定义。

具体示例实现可参考 `evaluation.md`。

#### `evaluation` 字段

| 字段 | 类型 | 必填 | 说明 | 约束 |
|---|---|---:|---|---|
| `evaluator_id` | string | 是 | evaluator 唯一标识 | 推荐使用 import path 形式，见 1.3.2 |
| `params` | object | 否 | 传给 evaluator 的参数 | 开放对象 |

evaluator 在 episode 正常结束时必须执行一次。

### 1.4 `limits`

| 字段 | 类型 | 必填 | 说明 | 约束 |
|---|---|---:|---|---|
| `max_steps` | integer | 是 | 最大步数 | `> 0` |
| `step_timeout_seconds` | number | 否 | 单步软超时 | `> 0`；协议层不设默认值 |

### 1.5 `metadata`

`metadata` 是开放对象，协议层不限制字段。

但按当前实现，下面这些字段已经是事实上的通用约定，建议各端保持兼容：

| 字段 | 类型 | 说明 |
|---|---|---|
| `tags` | string[] | 任务标签，用于筛选和组织 |
| `description` | string | 任务补充说明 |
| `app` | string | 面向人阅读的应用名 |
| `app_bundle_id` | string | 平台可消费的应用 bundle id |
| `include_screenshot` | boolean | 是否在运行记录中保留截图 |
| `success_criteria` | object | 平台自定义的补充成功条件 |

### 1.6 单任务示例

```yaml
task_id: macos.one_plus_one
platform: macos
instruction: Use Calculator to calculate 1 + 1 and leave the result visible.
timeout_seconds: 60
init:
  initializer_id: initializers.macos.open_app:OpenAppInitializer
  params:
    app_name: Calculator
    wait_ms: 800
evaluation:
  evaluator_id: evaluators.macos.one_plus_one:OnePlusOneEvaluator
  params:
    expected_result: "2"
limits:
  max_steps: 15
  step_timeout_seconds: 30
metadata:
  tags: [calculator, open, easy]
  app_bundle_id: com.apple.calculator
```

## 2. 公共 `validate()`

程序进入后，会自动校验 task 是否正常，校验通过后才会进入平台代码。
