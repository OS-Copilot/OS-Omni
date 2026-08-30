# Benchmark Workbench 设计文档（v1 落地版）

## 1. 文档目标

这份文档定义 `workbench` 第一版的信息架构、页面边界和交互流转。

重点不是补字段表，而是回答三件事：

1. 这个项目到底需要一个什么样的工作台
2. 当前仓库的数据能力能支撑哪些页面，不能假装支撑哪些页面
3. 第一版应该如何组织导航、主页面和详情页

---

## 2. 我对项目的理解

这个仓库本质上是一个 **GUI agent benchmark workspace**。

它的主流程是：

1. 用 `executions/*.yaml` 定义一批待跑任务与模型组合
2. 用平台 runner 执行 benchmark
3. 为每个 run 产出标准工件：
   - `args.json`
   - `result.json`
   - `trajectory.jsonl`
   - `screenshots/`
   - `runner.log`（可选）
4. 最终由 `workbench` 把这些离散工件重新组织成：
   - 可浏览的结果空间
   - 可追查的运行详情
   - 可人工审核的证据工作区
   - 可聚合分析的统计视图

所以 `workbench` 不是文件浏览器，也不是配置编辑器。
它首先是一个 **benchmark result operations console**。

---

## 3. 第一版必须遵守的现实约束

这是我认为原文档里最需要补上的部分。

### 3.1 当前后端是只读扫描模型

当前 `workbench/backend` 的能力是：

* 扫描 `results/`
* 归一化成 `workspace / execution / run detail`
* 暴露只读 API

这意味着第一版页面设计必须建立在“读 benchmark 结果”之上，而不是建立在“编辑 benchmark 配置”之上。

### 3.2 当前天然可用的数据来源

当前 workbench 可以稳定依赖的信息是：

* run summary
* execution summary
* execution detail
* run detail
* 截图与最终 observation
* step 级 action / prompt / llm_response / llm_reasoning / execution status
* execution/task/model/platform 的快照信息

### 3.3 当前还没有服务端 review 存储

这点很关键。

所以第一版的 **Review** 模块可以做，但它要被定义成：

* 有完整证据浏览能力
* 有审核判定动作
* 判定结果先做本地持久化（例如浏览器本地存储）

而不是假装已经有完整的 review backend。

### 3.4 第一版不做的事

以下内容可以作为后续扩展，但不应强行塞进 v1：

* 多人协作 review
* 服务端 review record 持久化
* saved views / library
* 配置编辑
* 长时间序列趋势系统
* evaluator 策略管理后台

---

## 4. 总体结构

我建议把整个 workbench 固定成：

**左侧导航 + 顶部上下文区 + 主工作区 + 非导航详情页**

其中：

* 左侧导航：承载一级工作模式
* 顶部上下文区：承载共享筛选与当前范围
* 主工作区：承载模块主流程
* 非导航详情页：承载 execution / task / run / review workspace

这里有一个重要原则：

**左侧导航按“工作模式”分，不按“对象类型”分。**

---

## 5. 一级导航

第一版直接定成 4 个：

1. `Overview`
2. `Results`
3. `Review`
4. `Analytics`

这版最适合当前项目。

### 不建议进入左栏的页面

以下页面重要，但不应是一级导航：

* `Execution Detail`
* `Task Compare`
* `Run Detail`
* `Review Workspace`

原因很简单：
它们都属于“从某个结果空间继续钻取”的详情工作流，不是用户一进来就要切换到的工作模式。

---

## 6. 顶部上下文区

原文档提到了顶部区，但还不够具体。
我建议在 v1 里把它明确为一个 **全局共享筛选条**：

### 必备筛选

* search
* platform
* model
* task
* execution
* status

### 设计要求

* 所有一级页面共享同一套上下文
* 从 Analytics 钻回 Results 时沿用这套上下文
* 详情页也显示当前上下文，但不以详情页自身替代全局筛选

换句话说：

**筛选是 workbench 的工作上下文，不是某个页面的临时表单。**

---

## 7. 一级页面定义

## 7.1 Overview

### 页面定位

工作台首页。
它回答的是：

* 当前扫描到了多少结果
* 最近有哪些 execution
* 现在最该处理什么
* 下一步应该去哪个模块

### 页面内容

建议包含：

* 当前范围内的核心指标
* 最近 execution
* 待 review 数量
* 失败热点 task
* 最近活动
* 快捷入口

### 页面原则

Overview 不是深分析页，而是 **工作引导页**。

---

## 7.2 Results

### 页面定位

这是 workbench 的主战场。

### 必须承担的任务

* 浏览 run
* 横向比较 task / model / execution
* 快速定位失败项
* 进入 execution / task / run 详情
* 从这里跳到 review workspace

### v1 视图要求

Results 至少要有两种视图：

1. **Matrix View**
2. **Run List View**

#### Matrix View

矩阵是第一视图。

在当前仓库里，最自然的 v1 组织方式是：

* 行：task
* 列：model
* 单元格：当前筛选范围内该 task-model 组合的 run 状态摘要

当同一个单元格里有多个 run 时，不强行摊平，而是：

* 显示聚合摘要
* 再钻取到 `Task Compare`

#### Run List View

列表是排查视图。

它适合：

* 扫非通过项
* 看失败原因
* 快速进入 run detail
* 批量处理 review 队列入口

### 页面原则

Results 是 **结果浏览器**，不是目录树。

---

## 7.3 Review

### 页面定位

这是人工审核模块。

### v1 现实定义

因为当前没有服务端 review 存储，所以 v1 的 Review 应定义为：

* 以非通过 run 为默认待处理队列
* 允许人工给出 verdict / note / tags
* verdict 先存本地
* 后续可以替换成服务端持久化，不改页面结构

### 模块层级

Review 分成两层：

1. `Review Queue`
2. `Review Workspace`

#### Review Queue

用于决定先审哪条。

页面上应有：

* pending / reviewed 切换
* 审核状态摘要
* 待审列表
* 最近已审项

#### Review Workspace

从队列点进去后进入。

布局建议明确成三栏：

* 左：step / frame 导航
* 中：证据区域
* 右：审核动作区

这里证据区域优先展示：

* step screenshot
* final observation
* action 与 execution 结果
* prompt / llm output
* runner log 摘要

### 页面原则

Review 不是“再看一次 run detail”，而是 **围绕证据完成判定**。

---

## 7.4 Analytics

### 页面定位

Analytics 是聚合观察层，不替代 Results。

### 第一版建议主题

Analytics 不要做成“图表瀑布流”，而要按主题组织：

1. 整体表现
2. 模型对比
3. task 风险分布
4. execution 对比
5. review 覆盖与 verdict 分布

### 交互要求

Analytics 里的每个分析区都应该能回跳到：

* Results
* Execution Detail
* Task Compare

这样它才是工作流入口，不是静态展示页。

---

## 8. 非导航详情页

## 8.1 Execution Detail

### 页面定位

聚焦某次 execution 的上下文工作页。

### v1 应展示

* execution 概况
* 当前 execution 的 task x model 矩阵
* 运行模式信息
* 该 execution 下的 run 列表

它本质上是 “Results 在单个 execution 上的展开”。

---

## 8.2 Task Compare

### 页面定位

聚焦单个 task 的横向比较页。

### v1 应展示

* 同 task 在不同 execution 下的表现
* 同 task 在不同 model 下的表现
* 同 task 的失败样本
* 该 task 的全部 run 列表

它本质上是 “Results 中单个 task 组合的比较页”。

---

## 8.3 Run Detail

### 页面定位

单次运行复盘页。

### v1 建议布局

* 概况卡片
* replay / frame 区
* frame analysis
* observation 数据
* artifact 与 peer runs

这里强调的是“复盘”，不是“做判定”。

---

## 8.4 Review Workspace

### 页面定位

单次 run 的审核工作区。

### 与 Run Detail 的区别

* Run Detail 重在复盘
* Review Workspace 重在判定

所以即便两者会复用不少证据组件，也应该是两条不同的页面路线。

---

## 9. 页面流转

第一版建议固定成下面这条主路径：

### 从 Overview

* 去最近 execution
* 去 Results 看当前范围
* 去 Review 处理 pending
* 去 Analytics 看总体表现

### 从 Results

* 去 `Execution Detail`
* 去 `Task Compare`
* 去 `Run Detail`
* 去 `Review Workspace`

### 从 Review

* 从 Queue 进入 `Review Workspace`
* 审核后回到 Queue
* 必要时跳到 `Run Detail`

### 从 Analytics

* 点击某个聚合项回到 Results
* 或直接钻取到 Execution / Task

这条关系可以概括成一句话：

**Overview 是入口，Results 是浏览中心，Review 是处理中心，Analytics 是观察中心。**

---

## 10. 第一版实现建议

为了保证这份文档能直接指导实现，我建议把 v1 明确成下面这版：

### 必做

* 四个一级模块：Overview / Results / Review / Analytics
* 一个共享顶部筛选条
* Results 的矩阵视图与列表视图
* Execution Detail
* Task Compare
* Run Detail
* Review Queue
* Review Workspace

### 允许的技术妥协

* review record 先保存在浏览器本地
* analytics 先以表格 / bar list 为主，不强求复杂图表
* 不做 saved views
* 不做设置中心

### 明确不做

* 服务端 review API
* 多用户协作状态同步
* 可编辑 benchmark 配置
* 权限与审批系统

---

## 11. 结论

原文档的方向是对的，尤其是这几点我认为完全成立：

* 左栏应该按工作模式分
* Results 必须是核心页
* Review 必须独立出来
* Run / Task / Execution 更适合做二级详情页

但它还需要补三类约束，才能真正指导当前仓库落地：

1. **v1 必须以现有只读扫描模型为边界**
2. **Review 要先定义成本地持久化工作流**
3. **Execution / Task / Run / Review Workspace 必须明确为非导航详情页**

按这版收敛后，文档和当前项目实现就是一致的了。
