# iOS 实验说明

## 1. 环境准备

需要在 macOS 主机上准备好：

- Xcode 和 iOS Simulator
- Python 3.10+
- Node.js
- Appium 和 `xcuitest` driver

安装 Python 依赖（在仓库根目录执行）：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

安装 Appium：

```bash
npm install -g appium
appium driver install xcuitest
```

## 2. 配置模型密钥

模型列表定义在 `configs/models.yaml`。只需要为本次 `execution` 中实际使用的模型配置对应环境变量。

代码会自动读取仓库根目录下的 `.env`：

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=...
```

## 3. 准备基线模拟器

每次 iOS benchmark 都会从一个基线模拟器克隆出临时实例来执行任务，所以先准备一个状态稳定的 baseline simulator。

建议流程：

1. 在 Simulator 中手动把环境准备到你想要的初始状态。
2. 记录这个模拟器的 UDID：

```bash
xcrun simctl list devices available
```

3. 把 UDID 写入 `configs/ios.yaml`：

```yaml
appium_host: 127.0.0.1
appium_port: 4723
source_simulator_udid: "YOUR_SIMULATOR_UDID"
```

`source_simulator_udid` 就是每次实验的克隆源。如果任务依赖特定 App、文件或登录态，都应该先准备在这个基线模拟器里。

## 4. 启动 Appium

```bash
appium --port 4723
```

默认配置下，代码会连接 `http://127.0.0.1:4723`。

如果要跑 Delta Chat 或 Maily 相关任务，还需要先启动 GreenMail，并在基线模拟器里配置好邮件账号。

## 5. 准备 execution 文件和 task 文件

正式入口是一个 execution YAML，但它会通过 `tasks:` 字段引用一个或多个 task YAML，所以这两类文件都需要准备。

仓库里已有 execution 示例：

- `executions/ios/ios_test_1.yaml`

对应的 task 示例可以参考：

- `tasks/ios/open_settings.yaml`

格式示例：

```yaml
tasks:
  - tasks/ios/open_settings.yaml
models:
  - intern_s1_pro
action_mode: code_adapter
observation_mode: a11y_tree_only
history_window: 3
metadata:
  description: test
```

常用字段：

- `tasks`: 本次要跑的任务列表
- `models`: 要评测的模型 ID，必须存在于 `configs/models.yaml`
- `action_mode`: `code_adapter`
- `observation_mode`: `screenshot_only`、`a11y_tree_only` 或 `screenshot_and_a11y_tree`
- `history_window`: 给 agent 的历史步数窗口

## 6. 运行前校验(这个暂时没用不用做)

如果只想先检查 execution 是否能被正确解析，可以运行：

```bash
python scripts/run_benchmark.py --execution executions/ios/ios_test_1.yaml
```

这个命令只做 preflight 校验，不会真正执行实验。

## 7. 运行实验

```bash
python -m platforms.ios.cli --execution executions/ios/ios_test_1.yaml
```

如果要换成其他 execution，直接替换文件路径即可：

## 8. 查看结果

结果会按模型和平台分桶，记录到results文件夹下

通过命令可以打开可视化Web界面观看结果

`python scripts/run_workbench.py`

## 9. 常见问题

- `Connection refused 127.0.0.1:4723`：Appium 没启动，或者 `configs/ios.yaml` 里的 host/port 不对。
- 运行很慢：XCUITest/WDA 首次构建是正常现象。
- 找不到模拟器或 clone 失败：检查 `source_simulator_udid` 是否有效。
