# Evaluation 示例实现

## 1. 文档用途

本文档给 task 接入方和平台实现方一个最小参考：

- task 文件里怎么写 `evaluation`
- evaluator 类怎么继承 core 基类
- 平台 runner 怎么调用 evaluator

## 2. 需要用到的 core 接口

evaluator 相关公共接口统一从 `core.evaluation` 导出：

```python
from core.evaluation import BaseEvaluator, EvalResult, EvalStatus, load_evaluator
```

其中：

- `BaseEvaluator` 是所有 evaluator 必须继承的基类
- `EvalResult` 是标准返回类型
- `EvalStatus` 是标准状态枚举
- `load_evaluator()` 负责按 import path 加载 evaluator

当前 import path 格式是：

```text
<python.module.path>:<EvaluatorSymbol>
```

例如：

- `evaluators.ios.open_settings:OpenSettingsEvaluator`
- `evaluators.ios.search_contract_file:searchContractFileEvaluator`
- `evaluators.macos.open_calculator:OpenCalculatorEvaluator`
- `evaluators.macos.one_plus_one:OnePlusOneEvaluator`

说明：

- loader的设计是直接按 import path 动态加载。
- `:` 左边是 Python module path，右边是模块导出的符号名。
- 该符号必须是一个继承 `BaseEvaluator` 的类；类名建议使用 UpperCamelCase。

## 3. Task 里的写法

task 文件中的 `evaluation` 最小示例如下：

```yaml
evaluation:
  evaluator_id: evaluators.macos.one_plus_one:OnePlusOneEvaluator
  params: # 可以为空
    expected_result: "2"
```

约定：

- `evaluator_id` 必须能被 `load_evaluator()` 成功加载
- `params` 是开放对象，由具体 evaluator 自己解释

## 4. 实现方伪代码

下面是一个最小 evaluator 示例。重点不是具体 UI 树结构，而是继承关系、上下文读取和返回结构。

```python
from typing import Any, Mapping
from core.evaluation import BaseEvaluator, EvalResult, EvalStatus

class OnePlusOneEvaluator(BaseEvaluator):
    def evaluate(self, context: Mapping[str, Any]) -> EvalResult:
	      #	...
        # 代码实现
        # ...
        return EvalResult(
            status=EvalStatus.PASS,
            message="Calculator shows the expected result",
            metadata={
                "expected_result": expected_result,
                "actual_result": actual_result,
            },
        )
```

建议按下面的语义返回：

- `PASS`: 明确满足任务目标
- `FAIL`: 明确不满足任务目标
- `UNDETERMINED`: 有观测但证据不足，无法可靠判定
- `ERROR`: evaluator 自身执行失败，或依赖环境不可用

`EvalResult` 字段如下：

| 字段       | 类型   | 必填 | 说明                                       |
| ---------- | ------ | ---: | ------------------------------------------ |
| `status`   | string |   是 | `PASS` / `FAIL` / `UNDETERMINED` / `ERROR` |
| `message`  | string |   否 | 简短说明                                   |
| `metadata` | object |   否 | 开放对象                                   |

## 5. 平台侧调用伪代码

平台 runner 的调用流程示例：

```python
from core.evaluation import EvalResult, EvalStatus, load_evaluator

def run_task_evaluation(evaluator_id, build_context):
  	
    evaluator = load_evaluator(evaluator_id)
    context = build_context()  # 平台自定context
    result = evaluator.evaluate(context)

    if not isinstance(result, EvalResult):
        raise TypeError("evaluator must return EvalResult")

    return result
```

要点：

- `load_evaluator()` 会校验 import path 并实例化目标类
- evaluator 的返回值必须是 `EvalResult`
- evaluator 应在 episode 结束时执行
- 当前 runner 会将 `UNDETERMINED` 和 `ERROR` 视为需要人工复核

## 6. `context` 

`context` 字段由各平台决定，iOS示例：

```python
context = {
    "params": dict(evaluation.params), # task.yaml中evaluation的params
    "controller": controller, # 可以执行观察和模拟行动的控制器
    "final_observation": final_observation, # 最后观察结果
}
```

如果 evaluator 需要更多能力，各平台可以继续往 `context` 里放平台对象，共享层只要求它是一个 mapping。

## 7. 参考实现

当前仓库里的真实实现可参考：

- `evaluators/ios/open_settings.py`
- `evaluators/ios/search_contract_file.py`
- `evaluators/macos/open_calculator.py`
- `evaluators/macos/one_plus_one.py`
- `platforms/ios/runners/evaluation.py`
- `platforms/macos/host/runners/evaluation.py`
