# macOS 实验说明

macOS 实验分成两部分：

- Guest：在 macOS VM 内安装 runtime 服务
- Host：在宿主机上配置 VM 信息并运行 benchmark

当前推荐的宿主机 VM 提供方是 **Tart**，因为它支持纯命令行、headless 启动、快速 clone，更适合 benchmark/CI 场景。

> 当前状态说明：
>
> - macOS benchmark 的正式生命周期现在以 **Tart** 为主
> - **VirtualBuddy** 仅保留为旧 baseline 的迁移来源和兼容备选，不再是默认推荐路径
> - 默认镜像是 `allapps-base`，所有 macOS task/execution 默认从这个模板 clone
> - runner 默认只连接镜像内预装并自启动的 HTTP guest runtime；SSH 同步 runtime 只作为本地调试开关

推荐把准备过程理解成一层：

- 维护一个长期保存的 `allapps-base` VM 模板，里面放 macOS 任务集需要的通用环境、应用和 HTTP runtime
- 每道任务自己的文件、账号状态和应用状态应由 initializer 在 clone 内准备，避免再维护多个专用 base VM

## 1. Host 环境准备

宿主机需要准备好：

- macOS（Apple Silicon）
- Python 3.12（项目依赖当前锁定在 `>=3.12,<3.14`，不要让 uv 自动选到 3.14）
- Tart
- 一个可作为 baseline 的 macOS VM

在仓库根目录安装 Python 依赖。推荐固定 Python 3.12，避免解析到 Python 3.14 后碰到第三方包 wheel 不兼容：

```bash
uv sync --python 3.12
```

如果不用 uv，也至少用 Python 3.12 创建虚拟环境，再安装项目依赖：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

安装 Tart：

```bash
brew install cirruslabs/cli/tart
```

## 2. 配置模型密钥

模型列表定义在 `configs/models.yaml`。只需要配置本次 `execution` 中实际会用到的模型。

代码会自动读取仓库根目录下的 `.env`：

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=...
```

## 3. 准备 baseline VM

### 方案 A：直接用 Tart 创建

可以直接创建一个新的 macOS VM：

```bash
tart create base --from-ipsw latest
tart run base
```

第一次启动后，在 VM 内完成系统初始化。建议至少确认这些事情：

- 用本地管理员账号完成初始化
- 开启自动登录，确保 VM 开机后直接进入桌面，而不是停在登录界面
- 关闭或放宽会导致空闲后锁屏的设置，避免运行过程中掉回登录页

### 方案 B：从已有 VirtualBuddy baseline 迁移到 Tart

如果你已经有一个可用的 VirtualBuddy baseline，可以直接用仓库里的脚本迁移：

```bash
python3 scripts/migrate_virtualbuddy_to_tart.py \
  --source-vm-name base \
  --target-vm-name base
```

迁移结果会写到默认的 `~/.tart/vms/<name>`。迁移完成后可检查：

```bash
tart list
tart get base
```

## 4. 关闭 SIP，允许脚本自动写入权限

`platforms/macos/guest/install_macos_vm.sh` 会尝试自动写入 TCC 权限（`Accessibility`、`Screen Recording`、`AppleEvents`）。这一步只有在关闭 `SIP` 后才会成功。

在 baseline VM 里重启进入 Recovery Mode，然后执行：

```bash
csrutil disable
```

你需要这么做：

1. 让 VM 进入 Recovery Mode
2. 在菜单栏打开 `Utilities -> Terminal`
3. 运行 `csrutil disable`
4. 重启回正常系统

## 5. 安装 Guest runtime

把 `platforms/macos/guest` 放进 VM 能访问到的位置后，在 VM 内执行：

```bash
bash install_macos_vm.sh
```

注意：

- 不要用 `sudo` 整体执行这个脚本。
- 这个脚本内部会在需要的地方单独调用 `sudo`，所以当前用户需要是管理员。
- VM 在安装阶段需要能联网，因为脚本会安装 Python 依赖，并可能拉起 Homebrew 或 Xcode Command Line Tools。
- 安装过程中如果弹出权限请求，允许。
- 如果安装过程中出现 Homebrew、Xcode Command Line Tools 或系统权限相关弹窗，也一并同意。
- 默认端口是 `5000`，默认 token 是 `macuibench-runtime-token`。

如果你想自定义端口或 token，可以这样安装：

```bash
MACUI_PORT=5000 MACUI_TOKEN='your-runtime-token' bash platforms/macos/guest/install_macos_vm.sh
```

安装脚本会把 runtime 安装到 `/Applications/MacUIBenchRuntime/runtime`，并注册一个用户级 `LaunchAgent`。安装完成后：

- 这个 VM 以后每次开机并进入桌面时，Guest runtime 都会自动启动
- 不需要每次开机都重新执行 `install_macos_vm.sh`
- 如果你改了 token，记得后面同步更新宿主机上的 `configs/macos.yaml`

## 6. 固化 baseline VM

benchmark 会对基线 VM 做 `clone -> run -> stop -> delete`，所以基线 VM 本身应该是一个干净、稳定、可重复的初始状态。

建议在基线 VM 里提前完成这些事情：

- 完成系统初始化和登录
- 确认 `csrutil status` 显示 SIP 已关闭
- 安装并验证 guest runtime
- 确认 runtime 所需权限已经授予成功
- 确认 Tart display 为 `1920x1080px`，并且 `displayRefit` 为 `false`
- 把桌面和应用状态整理成你期望的实验起点

准备完成后，把这个 VM 关机。macOS benchmark 运行时要求 `base_vm_name` 对应的基线 VM 已存在，并且处于停止状态。

macOS benchmark 的屏幕尺寸约定是 `1920x1080`。正式运行前，runner 会检查 guest
runtime 报告的屏幕尺寸和实际截图尺寸是否都是 `1920x1080`；如果 base VM 仍是
高分辨率 Retina 配置，例如 `4480x2520px`，任务会在 runtime readiness 阶段失败。

可以用下面命令检查 Tart 模板：

```bash
TART_HOME="${TART_HOME:-$HOME/.tart}"
tart get "$BASE_VM"
cat "$TART_HOME/vms/$BASE_VM/config.json"
```

如果显示尺寸不对，请先关机，再设置模板：

```bash
tart stop "$BASE_VM"
tart set "$BASE_VM" --display 1920x1080px --no-display-refit
```

如果你后面需要做某一类实验的专用初始态，比如：

- 预放一些文件
- 预装某个应用
- 预先登录某个账号

优先把这些准备逻辑写进对应 initializer。`allapps-base` 只承载可复用的系统级环境和已安装应用；
任务运行时仍然走 `clone -> initialize -> run -> stop -> delete`，所以 initializer 对 clone 的改动不会污染模板。

## 7. 配置宿主机连接信息

编辑 `configs/macos.yaml`。当前推荐配置长这样：

```yaml
vm_provider: "tart"
base_vm_name: "allapps-base"
vm_ip: "192.168.64.2"
runtime_port: 5000
vm_token: "macuibench-runtime-token"
```

字段说明：

- `vm_provider`: 当前使用的 VM 提供方；推荐填 `tart`，`virtualbuddy` 仅保留为兼容/迁移用途
- `base_vm_name`: 作为 clone 源的模板 VM 名称
- `vm_ip`: 当你直接连接一个已经启动的 live VM 时使用的地址
- `runtime_port`: Guest runtime 的端口
- `vm_token`: Guest runtime 的 Bearer token
- `tart_home`: 可选；如果你不用默认 `~/.tart`，可以显式指定 Tart 存储目录

### `base_vm_name` 怎么填

填 Tart 里你准备用来做 `clone -> run -> delete` 的那个模板 VM 名称。

- 当前仓库默认应保持为 `allapps-base`
- macOS task/execution 文件不应再写专用 `metadata.base_vm_name`
- benchmark 要求这个 VM 在运行前已经存在，并且处于关机状态

### `vm_ip` 怎么填

如果你是 **skip clone / 直接复用 live VM**，就先手动启动那台 VM，然后在 VM 内执行：

```bash
ipconfig getifaddr en0
```

如果这条命令没有返回值，再用下面这条命令确认当前有 IP 的网卡：

```bash
ifconfig
```

拿到 IPv4 地址后，把它填到 `configs/macos.yaml` 的 `vm_ip`。

如果你走的是 **标准 clone-based Tart benchmark**，runner 会在 clone 启动后自动解析 clone 的 IP，所以 `vm_ip` 主要用于 live/debug 模式。

## 8. 连接检查

正式跑实验前，建议先检查宿主机环境：

```bash
python3 scripts/check_env.py --platform macos
```

如果你当前已经有一台 live VM 跑着 guest runtime，也可以顺手检查：

```bash
python3 scripts/check_env.py --platform macos --check-runtime
```

它会帮助你检查：

- Python 版本是否满足 macOS benchmark 要求
- `requirements.txt` 的宿主机依赖是否已安装
- `tart` 是否存在
- `configs/macos.yaml` 是否可读
- `base_vm_name` 指向的 Tart VM 是否存在
- （可选）当前配置下的 guest runtime `/health` 是否可达

## 9. 准备 execution 文件和 task 文件

正式入口是一个 execution YAML，但它会通过 `tasks:` 字段引用一个或多个 task YAML，所以这两类文件都需要准备。

仓库里已有 execution 示例：

- `executions/macos/macos_test_1.yaml`
- `executions/macos/macos_test_2.yaml`
- `executions/macos/macos_zotero.yaml`

对应的 task 示例可以参考：

- `tasks/macos/textedit_append_ops_note.yaml`

格式示例：

```yaml
tasks:
  - tasks/macos/textedit_append_ops_note.yaml
models:
  - gpt5_4
action_mode: code_adapter
observation_mode: screenshot_only
history_window: 3
metadata:
  description: test
```

常用字段：

- `tasks`: 本次要跑的任务列表
- `models`: 要评测的模型 ID，必须存在于 `configs/models.yaml`
- `action_mode`: macOS benchmark 现在统一使用 `code_adapter`；该模式会让模型输出 Python 动作代码，底层按 reflection-pyautogui 路径执行
- `observation_mode`: macOS benchmark 现在统一使用 `screenshot_only`
- `history_window`: 给 agent 的历史步数窗口
- `metadata`: 只放描述、prompt profile 等执行元数据；base VM 统一由 `configs/macos.yaml` 控制

macOS task YAML 的 `limits` 现在统一约定为：

- `max_steps: 100`
- `step_timeout_seconds: 120`

这里的 `step_timeout_seconds` 表示**单步 python / action 执行预算**，不再作为整道题的 wall-clock 总超时。

## 10. 运行前校验

如果只想先检查 execution 是否能被正确解析，可以运行：

```bash
python3 scripts/run_benchmark.py --execution executions/macos/macos_test_1.yaml
```

这个命令只做 preflight 校验，不会真正执行实验。

如果要做不依赖模型 API key 的最小 VM/runtime smoke，可以跑 macOS OpenShop oracle execution：

```bash
python3 -m platforms.macos.host.cli --execution executions/macos/macos_openshop_oracle.yaml
```

这条路径仍会走 macOS runner、Tart clone、guest runtime、动作执行和 evaluator，但模型侧使用本地 oracle provider，因此适合确认 VM 生命周期和 runtime 链路是否正常。

## 11. 运行实验

```bash
python3 -m platforms.macos.host.cli --execution executions/macos/macos_test_1.yaml
```

如果要换成其他 execution，直接替换文件路径即可：

```bash
python3 -m platforms.macos.host.cli --execution executions/macos/macos_test_2.yaml
```

如果你要串行跑一组 macOS executions，可以自己维护一个 suite manifest，并传给 `scripts/run_macos_execution_suite.py`：

```bash
python3 scripts/run_macos_execution_suite.py --suite path/to/macos_suite.yaml
```

如果你要做**真模型全量跑**，并且明确要求**不允许任何 Oracle execution 混入**，可以加上：

```bash
python3 scripts/run_macos_execution_suite.py \
  --suite path/to/macos_suite.yaml \
  --model-override free_codesonline_gpt5_5_responses \
  --forbid-oracle-models
```

这里的 `--model-override` 会把 suite 里每条 execution 的 `models:` 临时重写成同一个真模型；
`--forbid-oracle-models` 会在执行前做硬性检查，只要最终 effective execution 里还残留任何 `*oracle*` model id，就直接报错退出，而不是带着脏配置开跑。
当前仓库里的 `free_codesonline_gpt5_5_responses` 已按 macOS 全量跑口径配置为 Responses API + `reasoning_effort: high`。

它会：

- 先逐个对 execution 做 preflight
- 再串行执行整套 macOS execution
- 在 `results/full_runs/` 下写出 `status.txt`、`master.log` 和 `execution_summary.tsv`

这个 Python 脚本会把每个子 execution 的 `stdin` 显式重定向到 `/dev/null`，避免 shell `while read` 驱动时被子进程偷吃输入、只跑完第一条 execution 就提前结束。

如果你在做第一轮 smoke，且想直接复用当前已经启动并验证过 runtime 的 live VM，
可以先设置：

```bash
export MACOS_SKIP_VM_CLONE=1
```

这样 execution 路径会直接连当前 `configs/macos.yaml` 指向的 live VM，
避免在 clone/IP 管理问题还没确认前卡在完整 benchmark 生命周期里。

标准 Tart 流程会：

1. 从 `base_vm_name` clone 出临时 VM
2. 用 `tart run --no-graphics` headless 启动 clone
3. 自动解析 clone 的 IP
4. 任务结束后 stop + delete 这个 clone

因此 base VM 自己应始终保持关机和干净状态。

### 可选 Guest runtime 同步 SSH key

标准 clone-based runner 默认只依赖镜像内已经安装并自启动的 HTTP guest runtime，不要求
宿主机能 SSH 进入 guest。上传/分发用的 macOS 镜像应预装 runtime，并保证开机自动登录后
`/health`、`/observe`、`/execute` 和 `/screenshot` 可通过 HTTP 使用。

如果你在本地调试 runtime 源码，确实需要在每个 clone 启动后通过 `scp/ssh bench@<clone-ip>`
同步 `platforms/macos/guest/runtime_server.py`，可以显式开启：

```bash
export MACOS_ENABLE_GUEST_RUNTIME_SYNC=1
```

开启后，为避免宿主机 ssh-agent 里多把 key 触发 guest 端 `MaxAuthTries`，runner 会固定使用
public-key-only SSH 选项，并按下面顺序选择 key：

1. 如果设置了 `HELLOWORLD_MACOS_GUEST_SSH_IDENTITY_FILE`，使用这个路径。
2. 否则如果存在 `$HOME/.ssh/helloworld_macos_bench`，自动使用这个默认 key。
3. 如果两者都没有，就只使用 SSH 默认 identity files，但仍禁用 agent 批量试 key。

推荐每台宿主机都准备自己的默认 key，并把 public key 写进每个 macOS base VM 的
`bench` 用户 `authorized_keys`：

```bash
KEY="${HELLOWORLD_MACOS_GUEST_SSH_IDENTITY_FILE:-$HOME/.ssh/helloworld_macos_bench}"
test -f "$KEY" || ssh-keygen -t ed25519 -N "" -f "$KEY" -C "helloworld-macos-bench-runtime-sync"

BASE_VM="allapps-base"
tart run --no-graphics "$BASE_VM"
BASE_IP="$(tart ip "$BASE_VM")"

cat "$KEY.pub" | ssh "bench@$BASE_IP" \
  'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'

tart stop "$BASE_VM"
```

如果你的 base VM 不叫 `allapps-base`，把上面的 `BASE_VM` 换成实际的 `base_vm_name`。
如果你使用非默认 key 路径，运行 benchmark 前设置：

```bash
export HELLOWORLD_MACOS_GUEST_SSH_IDENTITY_FILE=/path/to/your/bench_key
```

如果你已经显式开启过 runtime SSH 同步，但想回到上传镜像的 HTTP-only 默认路径，可以取消
`MACOS_ENABLE_GUEST_RUNTIME_SYNC`，或显式设置：

```bash
export MACOS_SKIP_GUEST_RUNTIME_SYNC=1
```

## 12. 结果目录

结果会按模型和平台分桶，记录到 `results/` 文件夹下。

通过命令可以打开可视化 Web 界面观看结果：

```bash
python scripts/run_workbench.py
```

## 13. 常见问题

- `Base VM not found`：检查 `configs/macos.yaml` 里的 `base_vm_name` 是否和 `tart list` 里的 VM 名称一致。
- `tart: command not found`：先确认已经 `brew install cirruslabs/cli/tart`。
- `Too many authentication failures`：只会影响显式开启 `MACOS_ENABLE_GUEST_RUNTIME_SYNC=1` 的本地调试路径；默认 HTTP-only benchmark 不需要 SSH。若必须同步 runtime，确认 runner 版本包含 public-key-only SSH 选项，并优先使用 `HELLOWORLD_MACOS_GUEST_SSH_IDENTITY_FILE` 或 `$HOME/.ssh/helloworld_macos_bench`。
- `Permission denied (publickey,password,keyboard-interactive)`：只会影响显式开启 runtime SSH 同步的本地调试路径。按上面的 “可选 Guest runtime 同步 SSH key” 步骤把 public key 写入对应 base VM，或关闭 `MACOS_ENABLE_GUEST_RUNTIME_SYNC` 回到 HTTP-only 默认路径。
- runtime 连接失败：检查 `runtime_port`、`vm_token` 是否和 VM 内安装时一致；如果是 live 模式，再确认 `vm_ip` 是否正确。
- 返回 `401 Unauthorized`：宿主机配置的 token 和 Guest runtime 实际 token 不一致。
- VM 开机后停在登录界面：通常是没有开启自动登录，导致用户级 `LaunchAgent` 没有启动。
- 观察或动作失败：通常是 VM 里没有授予 `Screen Recording` 或 `Accessibility` 权限；如果想让脚本自动写入这些权限，需要先在 Recovery Mode 里执行 `csrutil disable`。
