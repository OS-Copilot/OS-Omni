Linux platform support for OS-Omni follows the existing execution/task/result protocol.

Architecture:
- Host runner talks to a Linux guest runtime HTTP server.
- The guest runtime exposes observation, screenshot, action execution, bash/python helpers, and simple file APIs.
- The guest runtime also exposes setup endpoints for command execution, verified setup, file upload/download, file writes, and wallpaper changes.
- The host side reuses OS-Omni's shared LLM, prompt, runner, initializer, and evaluator protocol.
- Optionally, the host runner can boot a real Linux VM through VMware before each task-model run and then connect to the guest runtime inside that VM.
- Linux benchmark tasks should use `observation_mode: screenshot_only` unless there is a deliberate exception. The model should act from screenshots only; no a11y tree is exposed to the model in normal Linux runs.

Guest runtime prerequisites:
- Ubuntu/Linux desktop session with X11.
- Python deps from `platforms/linux/guest/requirements.txt` for full interactive control.
- `python3-pyatspi`, `xdotool`, and `wmctrl` are recommended for full a11y tree and input control.
- Without those optional dependencies, the runtime still supports screenshots, setup APIs, and launch commands in degraded mode.

Note:
- `pyatspi` may still be present inside the guest runtime for internal automation or diagnostics, but Linux model observations are configured as screenshot-only by default.

Run guest runtime example:

```bash
python -m platforms.linux.guest.runtime_server --host 0.0.0.0 --port 5000 --token linuxbench-runtime-token
```

Run host benchmark example:

```bash
python -m platforms.linux.cli --execution executions/linux/linux_office_writer_helloworld.yaml
```

Run the same Linux task through the shared Taobao OpenAI-compatible endpoint:

```bash
TAOBAO_API_KEY=... \
TAOBAO_API_URL=... \
python -m platforms.linux.cli --execution executions/linux/linux_openshop_taobao.yaml
```

If `configs/linux.yaml` sets `vm_provider: vmware`, the Linux CLI will resolve a VMware Linux VM from `vm_path` or from `vm_storage_dir` / `vm_image_url`, then:
- revert `vm_snapshot_name` before each task when `vm_reset_between_tasks: true`
- boot the VM
- resolve the guest IP
- automatically bootstrap the guest runtime through `vmrun` when `vm_guest_username` / `vm_guest_password` are configured and `/health` is not ready
- wait for the guest runtime HTTP server to become healthy
- stop the VM after the run if `vm_stop_on_exit: true`

Important:
- A VM reboot is not treated as a clean reset.
- If `vm_reset_between_tasks: true`, you must also set `vm_snapshot_name` to a clean baseline snapshot. Without a snapshot, Linux executions now fail fast instead of reusing a dirty VM state.

The recommended official-image path is to publish a VM archive that already auto-starts the guest runtime. In that mode, users only need VMware and either a `vm_path` or one `vm_image_url`. Automatic guest bootstrap remains available as a fallback for custom images.

Linux runtime config can also be overridden without editing `configs/linux.yaml`:
- `HELLOWORLD_LINUX_VM_IP`
- `HELLOWORLD_LINUX_RUNTIME_PORT`
- `HELLOWORLD_LINUX_RUNTIME_TOKEN`
- `HELLOWORLD_LINUX_VM_PROVIDER`
- `HELLOWORLD_LINUX_VM_PATH`
- `HELLOWORLD_LINUX_VM_SNAPSHOT_NAME`
- `HELLOWORLD_LINUX_VM_HEADLESS`
- `HELLOWORLD_LINUX_VM_STOP_ON_EXIT`
- `HELLOWORLD_LINUX_VM_USE_PROVIDER_IP`
- `HELLOWORLD_LINUX_VM_STORAGE_DIR`
- `HELLOWORLD_LINUX_VM_IMAGE_URL`
- `HELLOWORLD_LINUX_VM_IMAGE_ARCHIVE_NAME`
- `HELLOWORLD_LINUX_VM_IMAGE_NAME`
- `HELLOWORLD_LINUX_VM_BOOTSTRAP_RUNTIME`
- `HELLOWORLD_LINUX_VM_GUEST_USERNAME`
- `HELLOWORLD_LINUX_VM_GUEST_PASSWORD`
- `HELLOWORLD_LINUX_VM_GUEST_PYTHON_BIN`
- `HELLOWORLD_LINUX_VM_GUEST_RUNTIME_DIR`
- `HELLOWORLD_LINUX_VM_GUEST_INSTALL_DEPS`
