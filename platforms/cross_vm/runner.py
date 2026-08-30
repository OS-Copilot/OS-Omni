"""Sequential Windows -> Linux cross-VM benchmark runner."""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from core.llm.llm_client import LLMClientManager

from platforms.android.controller import AdbController
from platforms.android.core.types import load_task_from_file as load_android_task_from_file
from platforms.android.runtime_config import load_android_runtime_config
from platforms.android.runners.episode import EpisodeRunner as AndroidEpisodeRunner
from platforms.android.cli import (
    _ensure_emulator_running as ensure_android_emulator_running,
    reset_android_emulator_snapshot,
)
from platforms.cross_vm.types import CrossVmExecutionSpec, CrossVmTaskSpec, load_cross_vm_task
from platforms.linux.core.types import load_task_from_file as load_linux_task_from_file
from platforms.linux.runners.episode import EpisodeRunner as LinuxEpisodeRunner
from platforms.linux.runners.episode import wait_for_runtime_ready as wait_for_linux_runtime_ready
from platforms.linux.runtime_config import load_linux_runtime_config
from platforms.linux.runtime_env.vm_manager import LinuxVMRuntimeSession, start_linux_vm_session
from platforms.windows.core.types import load_task_from_file as load_windows_task_from_file
from platforms.windows.runners.episode import EpisodeRunner as WindowsEpisodeRunner
from platforms.windows.runners.episode import wait_for_runtime_ready as wait_for_windows_runtime_ready
from platforms.windows.runtime_config import WINDOWS_RUNTIME_CONFIG_PATH, load_windows_runtime_config
from platforms.windows.runtime_env.controller import WindowsRuntimeController
from platforms.windows.runtime_env.vm_manager import WindowsVMRuntimeSession, start_windows_vm_session


logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTAINER_NAME = os.getenv("HELLOWORLD_WINDOWS_CONTAINER_NAME", "helloworld_windows_vm")
DEFAULT_WINDOWS_HOST_RUNTIME_HOST = os.getenv("HELLOWORLD_WINDOWS_HOST_RUNTIME_HOST", "127.0.0.1")


class WindowsRuntimeSession:
    """Lifecycle wrapper for a Windows runtime backed by VMware or the legacy container."""

    def __init__(
        self,
        controller: WindowsRuntimeController,
        *,
        vm_session: WindowsVMRuntimeSession | None = None,
        started_by_session: bool = False,
        container_name: str = DEFAULT_CONTAINER_NAME,
    ) -> None:
        self.controller = controller
        self.vm_session = vm_session
        self.started_by_session = started_by_session
        self.container_name = container_name

    def close(self) -> None:
        if self.vm_session is not None:
            self.vm_session.close()
            return
        if not self.started_by_session:
            return
        token = self.controller.token
        port = int(self.controller.runtime_url.rsplit(":", 1)[1])
        docker_bin = _resolve_docker_bin()
        subprocess.run(
            [
                docker_bin,
                "exec",
                self.container_name,
                "curl",
                "-s",
                "-H",
                f"Authorization: Bearer {token}",
                "-X",
                "POST",
                f"http://172.30.0.2:{port}/shutdown",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [docker_bin, "stop", self.container_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def start_windows_runtime_session() -> WindowsRuntimeSession:
    runtime_config = load_windows_runtime_config(WINDOWS_RUNTIME_CONFIG_PATH)
    if runtime_config.vm_provider:
        vm_session = start_windows_vm_session(runtime_config, logger_obj=logger)
        controller = WindowsRuntimeController(
            runtime_url=f"http://{vm_session.runtime_host}:{int(runtime_config.runtime_port)}",
            token=str(runtime_config.runtime_token),
            timeout=20.0,
        )
        wait_for_windows_runtime_ready(controller.runtime_url, controller.token)
        return WindowsRuntimeSession(controller=controller, vm_session=vm_session)

    docker_bin = _resolve_docker_bin()
    inspect = subprocess.run(
        [docker_bin, "container", "inspect", DEFAULT_CONTAINER_NAME],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    started_by_session = inspect.returncode != 0
    if started_by_session:
        launcher = REPO_ROOT / "platforms" / "windows" / "start_windows_vm.sh"
        subprocess.run(
            ["bash", _to_bash_path(launcher)],
            check=True,
            cwd=str(REPO_ROOT),
        )

    host_runtime_host = DEFAULT_WINDOWS_HOST_RUNTIME_HOST
    controller = WindowsRuntimeController(
        runtime_url=f"http://{host_runtime_host}:{int(runtime_config.runtime_port)}",
        token=str(runtime_config.runtime_token),
        timeout=20.0,
    )
    wait_for_windows_runtime_ready(controller.runtime_url, controller.token)
    return WindowsRuntimeSession(
        controller=controller,
        started_by_session=started_by_session,
        container_name=DEFAULT_CONTAINER_NAME,
    )


class AndroidRuntimeSession:
    """Lifecycle wrapper for an Android emulator connection."""

    def __init__(self, controller: AdbController, runtime_config: Any) -> None:
        self.controller = controller
        self.runtime_config = runtime_config

    def close(self) -> None:
        return


def start_android_runtime_session() -> AndroidRuntimeSession:
    runtime_config = load_android_runtime_config(REPO_ROOT / "configs" / "android.yaml")
    ensure_android_emulator_running(runtime_config)
    controller = AdbController(adb_device=runtime_config.adb_device)
    health = controller.health()
    if str(health.get("status", "")).upper() != "HEALTHY":
        raise RuntimeError(f"Android device is not healthy: {health}")
    return AndroidRuntimeSession(controller=controller, runtime_config=runtime_config)


def run_execution(execution: CrossVmExecutionSpec) -> int:
    action_mode = str(execution.action_mode or "code_adapter").strip()
    if action_mode != "code_adapter":
        raise ValueError("cross_vm execution.action_mode only supports code_adapter")
    observation_mode = str(execution.observation_mode or "screenshot_and_a11y_tree").strip()
    history_window = int(execution.history_window or 3)
    max_steps = execution.max_steps

    logger.info("Execution: %s", execution.source_path)
    logger.info("Tasks: %d, Models: %d", len(execution.task_paths), len(execution.models))

    failed_tasks: list[str] = []
    task_specs = [load_cross_vm_task(task_path) for task_path in execution.task_paths]
    needs_linux = any(spec.target_platform == "linux" or spec.source_platform == "linux" for spec in task_specs)
    needs_android = any(spec.target_platform == "android" or spec.source_platform == "android" for spec in task_specs)
    needs_windows = any(spec.target_platform == "windows" or spec.source_platform == "windows" for spec in task_specs)
    linux_runtime_config = load_linux_runtime_config(REPO_ROOT / "configs" / "linux.yaml") if needs_linux else None

    for model_id in execution.models:
        execution_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        execution_run_dir = REPO_ROOT / "results" / _safe_name(model_id) / "cross_vm" / f"{execution.source_path.stem}_{execution_stamp}"
        execution_run_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Execution output dir for model %s: %s", model_id, execution_run_dir)

        llm_client = LLMClientManager.from_default_models_yaml()
        windows_session = start_windows_runtime_session() if needs_windows else None
        linux_session = start_linux_vm_session(linux_runtime_config) if needs_linux else None
        android_session = start_android_runtime_session() if needs_android else None
        if needs_linux and linux_session is None:
            raise RuntimeError("Linux VM provider is required for cross-VM execution.")
        try:
            for spec in task_specs:
                ok = _run_cross_vm_task(
                    spec=spec,
                    model_id=model_id,
                    llm_client=llm_client,
                    action_mode=action_mode,
                    observation_mode=observation_mode,
                    history_window=history_window,
                    max_steps=max_steps,
                    windows_session=windows_session,
                    android_session=android_session,
                    linux_session=linux_session,
                    linux_runtime_config=linux_runtime_config,
                    execution_run_dir=execution_run_dir,
                )
                if not ok:
                    failed_tasks.append(f"{model_id}:{spec.task_id}")
        finally:
            if android_session is not None:
                android_session.close()
            if linux_session is not None:
                linux_session.close()
            if windows_session is not None:
                windows_session.close()

    if failed_tasks:
        logger.error("Cross-VM execution finished with failures: %s", ", ".join(failed_tasks))
        return 1
    return 0


def _run_cross_vm_task(
    *,
    spec: CrossVmTaskSpec,
    model_id: str,
    llm_client: LLMClientManager,
    action_mode: str,
    observation_mode: str,
    history_window: int,
    max_steps: int | None,
    windows_session: WindowsRuntimeSession | None,
    android_session: AndroidRuntimeSession | None,
    linux_session: LinuxVMRuntimeSession | None,
    linux_runtime_config: Any,
    execution_run_dir: Path,
) -> bool:
    task_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = execution_run_dir / f"{_safe_name(spec.task_id)}_{task_stamp}"
    windows_run_dir = run_dir / "windows_phase"
    linux_run_dir = run_dir / "linux_phase"
    transfer_dir = run_dir / "transfer"
    windows_run_dir.mkdir(parents=True, exist_ok=True)
    linux_run_dir.mkdir(parents=True, exist_ok=True)
    transfer_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Running cross-VM task: %s", spec.task_id)
    if spec.source_platform == "windows" and spec.target_platform == "linux":
        if windows_session is None or linux_session is None:
            raise RuntimeError("Windows and Linux sessions are required")
        return _run_windows_to_linux_task(
            spec=spec,
            model_id=model_id,
            llm_client=llm_client,
            action_mode=action_mode,
            observation_mode=observation_mode,
            history_window=history_window,
            max_steps=max_steps,
            windows_session=windows_session,
            linux_session=linux_session,
            linux_runtime_config=linux_runtime_config,
            run_dir=run_dir,
            windows_run_dir=windows_run_dir,
            linux_run_dir=linux_run_dir,
            transfer_dir=transfer_dir,
        )
    if spec.source_platform == "android" and spec.target_platform == "windows":
        if android_session is None or windows_session is None:
            raise RuntimeError("Android and Windows sessions are required")
        return _run_android_to_windows_task(
            spec=spec,
            model_id=model_id,
            llm_client=llm_client,
            action_mode=action_mode,
            observation_mode=observation_mode,
            history_window=history_window,
            max_steps=max_steps,
            android_session=android_session,
            windows_session=windows_session,
            run_dir=run_dir,
            android_run_dir=run_dir / "android_phase",
            windows_run_dir=windows_run_dir,
            transfer_dir=transfer_dir,
        )
    raise ValueError(f"Unsupported cross-VM route: {spec.source_platform}->{spec.target_platform}")


def _run_windows_to_linux_task(
    *,
    spec: CrossVmTaskSpec,
    model_id: str,
    llm_client: LLMClientManager,
    action_mode: str,
    observation_mode: str,
    history_window: int,
    max_steps: int | None,
    windows_session: WindowsRuntimeSession,
    linux_session: LinuxVMRuntimeSession,
    linux_runtime_config: Any,
    run_dir: Path,
    windows_run_dir: Path,
    linux_run_dir: Path,
    transfer_dir: Path,
) -> bool:
    windows_task = load_windows_task_from_file(str(spec.windows_task_path))
    _apply_max_steps(windows_task, max_steps)
    windows_runner = WindowsEpisodeRunner(
        controller=windows_session.controller,
        llm_client=llm_client,
        model_id=model_id,
        action_mode=action_mode,
        observation_mode=observation_mode,
        save_trajectory=True,
        history_window=history_window,
        output_dir=str(windows_run_dir),
        run_dir=windows_run_dir,
    )
    windows_result = windows_runner.run_episode(windows_task)
    if not windows_result.success:
        _write_summary(
            run_dir,
            {
                "task_id": spec.task_id,
                "status": "FAIL",
                "phase": "windows",
                "windows_success": False,
                "linux_success": False,
                "message": windows_result.failure_message,
            },
        )
        return False

    host_transfer_path = transfer_dir / spec.transfer.host_filename
    host_transfer_path.write_bytes(windows_session.controller.get_file(spec.transfer.source_guest_path))

    linux_task = load_linux_task_from_file(str(spec.linux_task_path))
    _apply_max_steps(linux_task, max_steps)
    _inject_linux_transfer_step(
        task=linux_task,
        host_transfer_path=host_transfer_path,
        linux_guest_path=spec.transfer.target_guest_path,
    )

    linux_controller = _build_linux_controller(linux_session, linux_runtime_config)
    wait_for_linux_runtime_ready(linux_controller.runtime_url, linux_controller.token)
    linux_runner = LinuxEpisodeRunner(
        controller=linux_controller,
        llm_client=llm_client,
        model_id=model_id,
        action_mode=action_mode,
        observation_mode=observation_mode,
        save_trajectory=True,
        history_window=history_window,
        output_dir=str(linux_run_dir),
        run_dir=linux_run_dir,
    )
    linux_result = linux_runner.run_episode(linux_task)
    _write_summary(
        run_dir,
        {
            "task_id": spec.task_id,
            "status": "PASS" if linux_result.success else "FAIL",
            "phase": "linux",
            "windows_success": True,
            "linux_success": linux_result.success,
            "transfer_file": str(host_transfer_path),
            "windows_result": {
                "steps_taken": windows_result.steps_taken,
                "status": windows_result.status,
            },
            "linux_result": {
                "steps_taken": linux_result.steps_taken,
                "status": linux_result.status,
                "failure_message": linux_result.failure_message,
            },
        },
    )
    return linux_result.success


def _run_android_to_windows_task(
    *,
    spec: CrossVmTaskSpec,
    model_id: str,
    llm_client: LLMClientManager,
    action_mode: str,
    observation_mode: str,
    history_window: int,
    max_steps: int | None,
    android_session: AndroidRuntimeSession,
    windows_session: WindowsRuntimeSession,
    run_dir: Path,
    android_run_dir: Path,
    windows_run_dir: Path,
    transfer_dir: Path,
) -> bool:
    android_run_dir.mkdir(parents=True, exist_ok=True)
    reset_android_emulator_snapshot(android_session.runtime_config, reason=spec.task_id)
    android_task = load_android_task_from_file(str(spec.android_task_path))
    _apply_max_steps(android_task, max_steps)
    android_runner = AndroidEpisodeRunner(
        controller=android_session.controller,
        llm_client=llm_client,
        model_id=model_id,
        action_mode=action_mode,
        observation_mode=observation_mode,
        save_trajectory=True,
        history_window=history_window,
        output_dir=str(android_run_dir),
        run_dir=android_run_dir,
    )
    android_result = android_runner.run_episode(android_task)
    if not android_result.success:
        _write_summary(
            run_dir,
            {
                "task_id": spec.task_id,
                "status": "FAIL",
                "phase": "android",
                "android_success": False,
                "windows_success": False,
                "message": android_result.failure_message,
            },
        )
        return False

    host_transfer_path = transfer_dir / spec.transfer.host_filename
    host_transfer_path.write_bytes(android_session.controller.get_file(spec.transfer.source_guest_path))

    windows_task = load_windows_task_from_file(str(spec.windows_task_path))
    _apply_max_steps(windows_task, max_steps)
    _inject_windows_transfer_step(
        task=windows_task,
        host_transfer_path=host_transfer_path,
        windows_guest_path=spec.transfer.target_guest_path,
    )

    wait_for_windows_runtime_ready(
        windows_session.controller.runtime_url,
        windows_session.controller.token,
        timeout_seconds=180,
    )
    windows_runner = WindowsEpisodeRunner(
        controller=windows_session.controller,
        llm_client=llm_client,
        model_id=model_id,
        action_mode=action_mode,
        observation_mode=observation_mode,
        save_trajectory=True,
        history_window=history_window,
        output_dir=str(windows_run_dir),
        run_dir=windows_run_dir,
    )
    windows_result = windows_runner.run_episode(windows_task)
    _write_summary(
        run_dir,
        {
            "task_id": spec.task_id,
            "status": "PASS" if windows_result.success else "FAIL",
            "phase": "windows",
            "android_success": True,
            "windows_success": windows_result.success,
            "transfer_file": str(host_transfer_path),
            "android_result": {
                "steps_taken": android_result.steps_taken,
                "status": android_result.status,
            },
            "windows_result": {
                "steps_taken": windows_result.steps_taken,
                "status": windows_result.status,
                "failure_message": windows_result.failure_message,
            },
        },
    )
    return windows_result.success


def _inject_linux_transfer_step(*, task: Any, host_transfer_path: Path, linux_guest_path: str) -> None:
    if task.init is None:
        raise ValueError(f"Linux child task must define init to receive transfer artifact: {task.id}")
    params = dict(task.init.params or {})
    steps = list(params.get("steps") or [])
    parent_dir = str(PurePosixPath(linux_guest_path).parent)
    steps.append(
        {
            "type": "run_bash",
            "script": f"mkdir -p {shlex.quote(parent_dir)}",
            "timeout": 15,
        }
    )
    steps.append(
        {
            "type": "upload_file",
            "local_path": str(host_transfer_path),
            "path": linux_guest_path,
        }
    )
    params["steps"] = steps
    task.init.params.clear()
    task.init.params.update(params)


def _inject_windows_transfer_step(*, task: Any, host_transfer_path: Path, windows_guest_path: str) -> None:
    if task.init is None:
        raise ValueError(f"Windows child task must define init to receive transfer artifact: {task.id}")
    params = dict(task.init.params or {})
    steps = list(params.get("steps") or [])
    parent_dir = str(PureWindowsPath(windows_guest_path).parent)
    steps.append(
        {
            "type": "run_powershell",
            "script": f"New-Item -ItemType Directory -Force -Path '{parent_dir}' | Out-Null",
            "timeout": 15,
        }
    )
    steps.append(
        {
            "type": "upload_file",
            "local_path": str(host_transfer_path),
            "path": windows_guest_path,
        }
    )
    params["steps"] = steps
    task.init.params.clear()
    task.init.params.update(params)


def _apply_max_steps(task: Any, max_steps: int | None) -> None:
    if max_steps is not None:
        task.max_steps = max_steps


def _build_linux_controller(session: LinuxVMRuntimeSession, runtime_config: Any):
    from platforms.linux.runtime_env.controller import LinuxRuntimeController

    return LinuxRuntimeController(
        runtime_url=f"http://{session.runtime_host}:{int(runtime_config.runtime_port)}",
        token=str(runtime_config.runtime_token),
        timeout=20.0,
    )


def _write_summary(run_dir: Path, payload: dict[str, Any]) -> None:
    (run_dir / "cross_vm_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _resolve_docker_bin() -> str:
    docker_bin = shutil.which("docker")
    if docker_bin:
        return docker_bin
    windows_docker = Path("/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe")
    if windows_docker.exists():
        return str(windows_docker)
    local_windows_docker = Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe")
    if local_windows_docker.exists():
        return str(local_windows_docker)
    raise FileNotFoundError("docker is required to start the Windows VM container")


def _to_bash_path(path: Path) -> str:
    raw = path.resolve().as_posix()
    if len(raw) >= 3 and raw[1:3] == ":/":
        return f"/mnt/{raw[0].lower()}{raw[2:]}"
    return raw


def _safe_name(raw: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (raw or "unnamed"))
