# Lifecycle

一次实验依赖以下输入：

- `execution.yaml`
- `task.yaml`
- `configs/models.yaml`
- 平台默认 runtime 配置（`configs/<platform>.yaml`）

其中：

- `execution.yaml` 定义本次实验的任务集合、模型集合和执行配置
- `task.yaml` 定义单个任务的内容，以及初始化和评测入口
- `models.yaml` 定义 `model_id` 到真实模型配置的映射
- 平台默认 runtime 配置由平台定义和读取



```mermaid
flowchart TD
    A[scripts/run_benchmark.py] -->|传入 execution.yaml| C[文件校验]
    C --> D{校验通过?}
    D -- 否 --> E[报错并退出]
    D -- 是 --> F[分配 platform]
    F -->|传入 execution.yaml| G[对应 platform 的执行入口]
```



### execution

一次实验的顶层输入，对应一个 `execution.yaml` 文件。

一个 `execution` 定义：

- 要跑哪些 `task`
- 要跑哪些 `model`
- 本次运行的公共配置

启动后，会由`run_benchmark.py`校验并分配平台。

### episode

平台需要读取自己的运行时配置，然后把`execution` 展开为多个 `episode`。

展开方式是：`tasks x models`

也就是说，每个 `task` 都会分别和每个 `model` 组合，形成独立 `episode`。

一个`episode`的典型结构如下

```mermaid
flowchart TD
    A[Run VM] --> B[Run initializer]
    B --> C[Run steps]
    C -->|Receive termination signal| E[Run evaluator]
    E --> F[Record Data]
    F -->|Next episode| A

    classDef c1 fill:#EAF4FF,stroke:#93C5FD,stroke-width:1.2px,color:#1F2937,rx:10,ry:10;
    classDef c2 fill:#F3E8FF,stroke:#C4B5FD,stroke-width:1.2px,color:#1F2937,rx:10,ry:10;
    classDef c3 fill:#E8FFF7,stroke:#86EFAC,stroke-width:1.2px,color:#1F2937,rx:10,ry:10;
    classDef c5 fill:#FFECEF,stroke:#FDA4AF,stroke-width:1.2px,color:#1F2937,rx:10,ry:10;

    class A c1;
    class B c2;
    class C c3;
    class E c5;
```



`episode` 会在Steps传递出终止条件后结束。

`episode`的`step`循环停止后，系统会进入最终`evaluation`阶段，对 episode 的最终结果给出统一评测结论。

`episode` 结束后，应该写入该 `episode` 的过程产物，用于后续查看、调试和汇总。

### step

`episode` 在执行过程中会不断循环推进，每一轮循环就是一个 `step`。

一个 `step` 的典型结构如下：

```mermaid
flowchart TD
    A[Build Prompt] --> B[Observe]
    B --> C[Call Model]
    C --> D[Parse Decision]
    D --> E[Execute Action]
    E --> G{Check stop condition?}
    G -->|Yes| H[End]
    G -->|No / Next Step| A

    classDef c1 fill:#EAF4FF,stroke:#93C5FD,stroke-width:1.2px,color:#1F2937,rx:10,ry:10;
    classDef c2 fill:#F3E8FF,stroke:#C4B5FD,stroke-width:1.2px,color:#1F2937,rx:10,ry:10;
    classDef c3 fill:#E8FFF7,stroke:#86EFAC,stroke-width:1.2px,color:#1F2937,rx:10,ry:10;
    classDef c4 fill:#FFF7E8,stroke:#FCD34D,stroke-width:1.2px,color:#1F2937,rx:10,ry:10;
    classDef c5 fill:#FFECEF,stroke:#FDA4AF,stroke-width:1.2px,color:#1F2937,rx:10,ry:10;
    classDef c6 fill:#F3F4F6,stroke:#D1D5DB,stroke-width:1.2px,color:#1F2937,rx:10,ry:10;
    classDef c7 fill:#FEF3C7,stroke:#F59E0B,stroke-width:1.2px,color:#1F2937,rx:10,ry:10;
    classDef c8 fill:#E5E7EB,stroke:#9CA3AF,stroke-width:1.2px,color:#1F2937,rx:10,ry:10;

    class A c1;
    class B c2;
    class C c3;
    class D c4;
    class E c5;
    class F c6;
    class G c7;
    class H c8;
```

`step` 会在满足条件后结束。

终止条件通常包括：

- agent 返回终止信号，如 `success` 或 `fail`
- 达到 `execution` 设定的步数或时间预算上限
- 当前 `step` 中出现无法继续恢复的异常
- 当前 `step` 的模型输出无法继续解析或执行

