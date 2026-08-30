# Windows Platform

Chinese version: `README.zh-CN.md`

This guide describes a full, reproducible Windows setup for HelloWorld benchmark runs.

## Scope

With this repository, a user can:

1. Install required host dependencies (WSL2, Docker Desktop, KVM check).
2. Prepare a Windows golden VM storage from `setup.iso`.
3. Run Windows benchmark executions.
4. Restore storage quickly if VM state is corrupted.

External assets still required:

- Windows 11 Enterprise Evaluation ISO (`setup.iso`, 64-bit)
- OpenAI API key

Important ISO note:

- Use the Enterprise Evaluation ISO. Other Windows ISOs may hang at language/OOBE steps during unattended prepare.

## Repository Paths

- Windows scripts: `platforms/windows/scripts/`
- VM launcher: `platforms/windows/start_windows_vm.sh`
- VM assets: `platforms/windows/vm/`
- VM storage: `platforms/windows/vm/storage/`

## 0. Fresh Machine Setup

Shell convention used in this guide:

- All `bash ...` commands should run inside WSL (Ubuntu).
- If you are currently in PowerShell, run bash commands as:
  - `wsl -e bash -lc "<command>"`

### 0.1 Enable virtualization in BIOS/UEFI

Before software setup, ensure CPU virtualization is enabled in BIOS/UEFI:

- Intel: `Intel VT-x` / `Intel Virtualization Technology`
- AMD: `SVM Mode`

### 0.2 Install WSL2 (PowerShell as Administrator)

```powershell
wsl --install -d Ubuntu-22.04
wsl --set-default-version 2
```

Reboot Windows if prompted.

### 0.3 Install Docker Desktop

1. Install Docker Desktop from Docker official site.
2. In Docker Desktop Settings:
- Enable `Use the WSL 2 based engine`
- Enable WSL integration for your distro (for example `Ubuntu-22.04`)

### 0.4 Verify WSL, Docker, KVM

Run from PowerShell:

```powershell
wsl -e bash -lc "echo WSL_OK; uname -a"
wsl -e sh -lc "test -e /dev/kvm && echo KVM_OK || echo KVM_MISSING"
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' version
```

Expected:

- `WSL_OK`
- `KVM_OK`
- Docker Client/Server version output

If `KVM_MISSING`, fix virtualization configuration before continuing.

## 1. Clone Repository

```powershell
git clone <your-helloworld-repo-url>
cd HelloWorld
```

## 2. Configure Environment

Copy `.env.example` to `.env` and set at least:

```ini
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1

# Optional local runtime tag used by launcher (kept as a local alias).
HELLOWORLD_WINDOWS_IMAGE=helloworld/windows-vm:latest

# Recommended public source image for bootstrap (Docker Hub).
HELLOWORLD_WINDOWS_SOURCE_IMAGE=yunta88/helloworld-windows-vm:latest

# Optional, defaults to platforms/windows/vm/storage
VM_STORAGE_DIR=/mnt/d/Research/HelloWorld/HelloWorld/platforms/windows/vm/storage
```

## 3. Bootstrap Windows VM Container Image

This creates the local image tag used by HelloWorld:

```bash
bash platforms/windows/scripts/bootstrap_windows_image.sh
```

Default behavior:

- Pull `yunta88/helloworld-windows-vm:latest` (or `HELLOWORLD_WINDOWS_SOURCE_IMAGE`)
- Keep local tag as `helloworld/windows-vm:latest`

If you use a custom source image, pass `--source-image` or set `HELLOWORLD_WINDOWS_SOURCE_IMAGE`.

## 4. Put ISO in Place

Place the Windows ISO at:

```text
platforms/windows/vm/image/setup.iso
```

## 5. Prepare Golden VM Storage (One Time)

Run once to build Windows golden storage:

```bash
bash platforms/windows/scripts/prepare_windows_golden_image.sh --clean-storage true
```

Notes:

- Watch VM screen at `http://localhost:8006`
- Do not interact with VM while preparing
- Typical time is 20-120 minutes depending on host performance

## 6. Back Up Golden Storage (Recommended)

After prepare succeeds, back up a clean copy:

```bash
mkdir -p platforms/windows/vm/storage.golden
rsync -a --delete platforms/windows/vm/storage/ platforms/windows/vm/storage.golden/
```

## 7. Run a Benchmark

```bash
bash platforms/windows/scripts/run_windows_execution.sh executions/windows/json/openshop_login.yaml
```

Equivalent direct command:

```bash
bash platforms/windows/start_windows_vm.sh --execution executions/windows/json/openshop_login.yaml
```

Runtime gate behavior (important):

- The launcher does not rely on `/probe` alone.
- It requires unified runtime APIs on port `5000` (`/health` + `/action_schema`).
- If port `5000` is still on legacy runtime, launcher will remediate in guest and retry before running tasks.
- If unified APIs are still unavailable, execution exits early instead of running against incompatible runtime.

Quick runtime self-check (after VM is up):

```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' exec helloworld_windows_vm `
  python -c "import requests; h={'Authorization':'Bearer windowsbench-runtime-token'}; base='http://20.20.20.21:5000'; print('probe',requests.get(base+'/probe',headers=h,timeout=8).status_code); print('health',requests.get(base+'/health',headers=h,timeout=8).status_code); print('action_schema',requests.get(base+'/action_schema',headers=h,timeout=8).status_code)"
```

Quick a11y self-check:

```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' exec helloworld_windows_vm `
  python -c "import requests; h={'Authorization':'Bearer windowsbench-runtime-token'}; u='http://20.20.20.21:5000/observe?include_ui_tree=1&include_screenshot_data=0'; j=requests.get(u,headers=h,timeout=20).json(); print('ui_nodes_len',len(j.get('ui_nodes',[])),'foreground',j.get('foreground_window'))"
```

## 8. Recover from Corrupted Storage

If VM enters automatic repair or runtime never becomes ready:

```bash
bash platforms/windows/scripts/reset_windows_storage.sh \
  --source-dir /path/to/storage.golden \
  --target-dir /path/to/storage
```

## Quick End-to-End Checklist

1. `WSL_OK`, `KVM_OK`, Docker `version` all pass.
2. `.env` has valid `OPENAI_API_KEY`.
3. `setup.iso` exists at `platforms/windows/vm/image/setup.iso`.
4. Run bootstrap image script once.
5. Run prepare golden storage once.
6. Run `executions/windows/json/openshop_login.yaml`.

## Troubleshooting

- `Docker daemon is not running`:
Start Docker Desktop and retry.

- `/dev/kvm` missing:
Enable CPU virtualization in BIOS/UEFI and confirm WSL2 setup.

- VM loops in automatic repair:
Reset working storage from your golden backup.

- API calls fail:
Check `OPENAI_API_KEY` and model config in `configs/models.yaml`.

- `http://localhost:8006` shows connection refused:
Check container status first:
```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' ps
```
If `helloworld_windows_vm` is not running, rerun launcher.
If it is running but viewer still fails, restart the run once (`wsl --shutdown`, then rerun launcher).

- Runtime protocol mismatch (`/probe` works but `/action_schema` fails):
This means legacy runtime is serving port `5000`.
Use the current launcher (which auto-remediates), and do not bypass the launcher with a stale container.

- Repeated `Waiting for a response from the windows server. This might take a while...`:
This means guest runtime has not become ready yet.
If it lasts more than 10-15 minutes, check:
```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' logs --tail 200 helloworld_windows_vm
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' exec helloworld_windows_vm curl -s http://20.20.20.21:5000/probe
```
If needed, restart once:
```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' exec helloworld_windows_vm curl -H "Authorization: Bearer windowsbench-runtime-token" -X POST http://20.20.20.21:5000/shutdown
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' stop helloworld_windows_vm
wsl -e bash -lc "cd /mnt/d/Research/HelloWorld/HelloWorld && bash platforms/windows/start_windows_vm.sh"
```

## Result Location

Windows runs are written to:

```text
results/<model>/windows/<execution_timestamp>/
```
