# Windows 平台

英文版本：`README.md`

本文档提供 HelloWorld Windows 基准测试的完整可复现流程。

## 适用范围

基于本仓库，用户可以：

1. 安装主机依赖（WSL2、Docker Desktop、KVM 检查）。
2. 从 `setup.iso` 制作 Windows golden VM 存储。
3. 运行 Windows 基准执行任务。
4. 在 VM 状态损坏时快速恢复存储。

仍需用户自行准备的外部资产：

- Windows 11 Enterprise Evaluation ISO（`setup.iso`，64-bit）
- OpenAI API Key

ISO 重要说明：

- 请使用 Enterprise Evaluation 版本 ISO。其他版本可能在语言选择/OOBE 阶段卡住，导致无人值守初始化失败。

## 仓库关键路径

- Windows 脚本：`platforms/windows/scripts/`
- VM 启动器：`platforms/windows/start_windows_vm.sh`
- VM 资产目录：`platforms/windows/vm/`
- VM 存储目录：`platforms/windows/vm/storage/`

## 0. 新机器初始化

本指南命令行约定：

- 文中的 `bash ...` 命令都应在 WSL（Ubuntu）内执行。
- 如果你当前在 PowerShell，请用下面形式执行：
  - `wsl -e bash -lc "<command>"`

### 0.1 在 BIOS/UEFI 开启虚拟化

开始前请先确认 CPU 虚拟化已开启：

- Intel: `Intel VT-x` / `Intel Virtualization Technology`
- AMD: `SVM Mode`

### 0.2 安装 WSL2（管理员 PowerShell）

```powershell
wsl --install -d Ubuntu-22.04
wsl --set-default-version 2
```

如提示重启，请先重启 Windows。

### 0.3 安装 Docker Desktop

1. 从 Docker 官方渠道安装 Docker Desktop。
2. 在 Docker Desktop 设置中确认：
- 开启 `Use the WSL 2 based engine`
- 为你的发行版（如 `Ubuntu-22.04`）开启 WSL integration

### 0.4 验证 WSL / Docker / KVM

在 PowerShell 执行：

```powershell
wsl -e bash -lc "echo WSL_OK; uname -a"
wsl -e sh -lc "test -e /dev/kvm && echo KVM_OK || echo KVM_MISSING"
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' version
```

期望看到：

- `WSL_OK`
- `KVM_OK`
- Docker Client/Server 版本输出

若显示 `KVM_MISSING`，请先修复虚拟化配置再继续。

## 1. 克隆仓库

```powershell
git clone <your-helloworld-repo-url>
cd HelloWorld
```

## 2. 配置环境变量

将 `.env.example` 复制为 `.env`，至少填写：

```ini
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1

# 可选，本地运行标签（launcher 使用本地别名）
HELLOWORLD_WINDOWS_IMAGE=helloworld/windows-vm:latest

# 推荐：bootstrap 时使用的公开来源镜像（Docker Hub）
HELLOWORLD_WINDOWS_SOURCE_IMAGE=yunta88/helloworld-windows-vm:latest

# 可选，默认值为 platforms/windows/vm/storage
VM_STORAGE_DIR=/mnt/d/Research/HelloWorld/HelloWorld/platforms/windows/vm/storage
```

## 3. 初始化 Windows VM 容器镜像

执行：

```bash
bash platforms/windows/scripts/bootstrap_windows_image.sh
```

默认行为：

- 拉取 `yunta88/helloworld-windows-vm:latest`（或 `HELLOWORLD_WINDOWS_SOURCE_IMAGE`）
- 本地保持 `helloworld/windows-vm:latest` 标签

如需使用自定义来源镜像，可传 `--source-image` 或设置 `HELLOWORLD_WINDOWS_SOURCE_IMAGE`。

## 4. 放置 ISO

将 Windows ISO 放到：

```text
platforms/windows/vm/image/setup.iso
```

## 5. 制作 Golden VM 存储（一次性）

执行：

```bash
bash platforms/windows/scripts/prepare_windows_golden_image.sh --clean-storage true
```

说明：

- 可在 `http://localhost:8006` 观察 VM 屏幕
- 制作期间不要人工干预 VM
- 耗时通常在 20-120 分钟（取决于宿主机性能）

## 6. 备份 Golden 存储（强烈推荐）

制作完成后，建议备份一份干净副本：

```bash
mkdir -p platforms/windows/vm/storage.golden
rsync -a --delete platforms/windows/vm/storage/ platforms/windows/vm/storage.golden/
```

## 7. 运行基准测试

```bash
bash platforms/windows/scripts/run_windows_execution.sh executions/v1/windows.yaml
```

等价直接命令：

```bash
bash platforms/windows/start_windows_vm.sh --execution executions/v1/windows.yaml
```

如果 Windows VM 运行在 QEMU 上并且 guest runtime 已启动，可以用批量 runner，每个任务前恢复快照：

```bash
python scripts/run_linux_qemu_batch.py --platform windows --execution executions/v1/windows.yaml ...
```

QEMU 镜像准备见 [docs/windows_android_companion.md](../../docs/windows_android_companion.md)，完整模型配置示例见 [docs/windows/qwen38-max-reproduction.md](../../docs/windows/qwen38-max-reproduction.md)。

Runtime 启动判定（重要）：

- 启动器不再只依赖 `/probe`。
- 必须确认 `5000` 端口上的 unified runtime 接口可用（`/health` + `/action_schema`）。
- 如果 `5000` 仍是 legacy runtime，启动器会在来宾系统内自动修复后再继续。
- 若修复后仍不可用，会直接退出，不会带着不兼容 runtime 继续跑任务。

Runtime 快速自检（VM 启动后执行）：

```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' exec helloworld_windows_vm `
  python -c "import requests; h={'Authorization':'Bearer windowsbench-runtime-token'}; base='http://20.20.20.21:5000'; print('probe',requests.get(base+'/probe',headers=h,timeout=8).status_code); print('health',requests.get(base+'/health',headers=h,timeout=8).status_code); print('action_schema',requests.get(base+'/action_schema',headers=h,timeout=8).status_code)"
```

a11y 快速自检：

```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' exec helloworld_windows_vm `
  python -c "import requests; h={'Authorization':'Bearer windowsbench-runtime-token'}; u='http://20.20.20.21:5000/observe?include_ui_tree=1&include_screenshot_data=0'; j=requests.get(u,headers=h,timeout=20).json(); print('ui_nodes_len',len(j.get('ui_nodes',[])),'foreground',j.get('foreground_window'))"
```

## 8. 存储损坏后的恢复

如果 VM 进入自动修复或 runtime 长时间不可用：

```bash
bash platforms/windows/scripts/reset_windows_storage.sh \
  --source-dir /path/to/storage.golden \
  --target-dir /path/to/storage
```

## 一键自检清单

1. `WSL_OK`、`KVM_OK`、Docker `version` 均通过。
2. `.env` 中 `OPENAI_API_KEY` 有效。
3. `setup.iso` 位于 `platforms/windows/vm/image/setup.iso`。
4. 先跑一次镜像 bootstrap。
5. 先跑一次 golden 存储制作。
6. 再跑 `executions/v1/windows.yaml`。

## 常见问题

- `Docker daemon is not running`：
启动 Docker Desktop 后重试。

- `/dev/kvm` 缺失：
检查 BIOS/UEFI 虚拟化开关和 WSL2 配置。

- VM 反复自动修复：
用 golden 备份恢复工作存储。

- API 调用失败：
检查 `OPENAI_API_KEY` 与 `configs/models.yaml` 中模型配置。

- `http://localhost:8006` 拒绝连接：
先检查容器状态：
```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' ps
```
若 `helloworld_windows_vm` 不在运行，重新启动 launcher。
若容器在运行但页面仍打不开，执行一次 `wsl --shutdown` 后重启 launcher。

- Runtime 协议不匹配（`/probe` 通但 `/action_schema` 不通）：
通常说明 `5000` 被 legacy runtime 占用。
请使用当前 launcher（会自动修复），不要直接复用旧容器绕过启动流程。

- 一直打印 `Waiting for a response from the windows server. This might take a while...`：
表示来宾 runtime 还没就绪。
如果持续超过 10-15 分钟，先检查：
```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' logs --tail 200 helloworld_windows_vm
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' exec helloworld_windows_vm curl -s http://20.20.20.21:5000/probe
```
必要时重启一次：
```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' exec helloworld_windows_vm curl -H "Authorization: Bearer windowsbench-runtime-token" -X POST http://20.20.20.21:5000/shutdown
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' stop helloworld_windows_vm
wsl -e bash -lc "cd /mnt/d/Research/HelloWorld/HelloWorld && bash platforms/windows/start_windows_vm.sh"
```

## 结果目录

Windows 运行结果会输出到：

```text
results/<model>/windows/<execution_timestamp>/
```
