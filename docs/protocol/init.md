# Init 示例实现

## 1. 文档用途

本文档给 task 接入方和平台实现方一个最小参考：

- task 文件里怎么写 `init`
- initializer 类怎么继承 core 基类
- 平台 runner 怎么调用 initializer

## 2. 需要用到的 core 接口

initializer 相关公共接口统一从 `core.init` 导出：

```python
from core.init import BaseInitializer, InitResult, InitStatus, load_initializer
```

其中：

- `BaseInitializer` 是所有 initializer 必须继承的基类
- `InitResult` 是标准返回类型
- `InitStatus` 是标准状态枚举
- `load_initializer()` 负责按 import path 加载 initializer

当前 import path 格式是：

```text
<python.module.path>:<InitializerSymbol>
```

例如：

- `initializers.ios.open_app:OpenAppInitializer`
- `initializers.macos.open_app:OpenAppInitializer`

说明：

- loader的设计是直接按 import path 动态加载。
- `:` 左边是 Python module path，右边是模块导出的符号名。
- 该符号必须是一个继承 `BaseInitializer` 的类；类名建议使用 UpperCamelCase。

## 3. Task 里的写法

task 文件中的 `init` 最小示例如下：

```yaml
init:
  initializer_id: initializers.macos.open_app:OpenAppInitializer
  params: # 可以为空
    app_name: Calculator
    wait_ms: 800
```

约定：

- `initializer_id` 必须能被 `load_initializer()` 成功加载
- `params` 是开放对象，由具体 initializer 自己解释

## 4. 实现方伪代码

下面是一个最小 initializer 示例。

```python
from typing import Any, Mapping
from core.init import BaseInitializer, InitResult, InitStatus

class OpenAppInitializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
      	# ...
        # 初始化代码
        # ...
        return InitResult(
            status=InitStatus.PASS,
            message=f"Opened app '{app_name}'",
            metadata={
                "app_name": app_name,
                "wait_ms": wait_ms,
            },
        )
```

建议按下面的语义返回：

- `PASS`: 初始化成功，episode 可以继续执行
- `FAIL`: 初始化逻辑正常结束，但任务前置条件不满足
- `ERROR`: 初始化过程中抛异常，或运行环境本身不可用

`InitResult` 字段如下：

| 字段       | 类型   | 必填 | 说明                      |
| ---------- | ------ | ---: | ------------------------- |
| `status`   | string |   是 | `PASS` / `FAIL` / `ERROR` |
| `message`  | string |   否 | 简短说明                  |
| `metadata` | object |   否 | 开放对象                  |

## 5. 平台侧调用伪代码

平台 runner 的调用流程示例：

```python
from core.init import InitResult, InitStatus, load_initializer

def run_task_initialization(initializer_id, build_context):
    if initializer_id is None:
        return None

    initializer = load_initializer(initializer_id)
    context = build_context() # 平台自定context
    result = initializer.initialize(context)

    if not isinstance(result, InitResult):
        raise TypeError("initializer must return InitResult")

    return result
```

要点：

- `load_initializer()` 会校验 import path 并实例化目标类
- initializer 的返回值必须是 `InitResult`
- runner 应该在 step loop 之前执行 initializer
- 当状态不是 `PASS` 时，通常应直接终止当前 episode

## 6. `context` 建议内容

`context` 字段由平台决定，ios示例：

```python
context = {
    "params": dict(init.params), # task.yaml中init的params
    "controller": controller, # 可以执行观察和模拟行动的控制器
}
```

## 7. 参考实现

当前仓库里的真实实现可参考：

- `initializers/ios/open_app.py`
- `initializers/macos/open_app.py`
- `platforms/ios/runners/initialization.py`
- `platforms/macos/host/runners/initialization.py`
