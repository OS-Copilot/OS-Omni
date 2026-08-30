"""Optional Linux VM lifecycle support for benchmark executions."""

from __future__ import annotations

import logging
import os
import platform
import re
import shlex
import subprocess
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from platforms.linux.runtime_config import LinuxRuntimeConfig
from platforms.linux.runtime_env.controller import LinuxRuntimeController, LinuxRuntimeError


logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[3]
HOST_RUNTIME_SERVER_PATH = REPO_ROOT / "platforms" / "linux" / "guest" / "runtime_server.py"

DEFAULT_VM_IP_TIMEOUT_SECONDS = 180.0
DEFAULT_VM_IP_POLL_INTERVAL_SECONDS = 3.0
DEFAULT_RUNTIME_HEALTH_TIMEOUT_SECONDS = 45.0
DEFAULT_RUNTIME_HEALTH_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_VMWARE_LIST_TIMEOUT_SECONDS = 20.0
DEFAULT_VMWARE_START_TIMEOUT_SECONDS = 180.0
DEFAULT_VMWARE_STOP_SOFT_TIMEOUT_SECONDS = 60.0
DEFAULT_VMWARE_STOP_HARD_TIMEOUT_SECONDS = 90.0
DEFAULT_VMWARE_STOP_POLL_TIMEOUT_SECONDS = 20.0
DEFAULT_VMWARE_STOP_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_VMWARE_REVERT_TIMEOUT_SECONDS = 180.0
VMWARE_SKIP_RUNNING_CHECK_ENV = "HELLOWORLD_VMWARE_SKIP_RUNNING_CHECK"


class LinuxVMError(RuntimeError):
    """VM lifecycle failure for the Linux benchmark runtime."""


class LinuxVMProvider(Protocol):
    provider_name: str

    def is_running(self, vm_path: str) -> bool:
        """Return whether the VM is already running."""

    def start_emulator(self, vm_path: str, *, headless: bool) -> None:
        """Start the configured VM."""

    def stop_emulator(self, vm_path: str) -> None:
        """Stop the configured VM."""

    def revert_to_snapshot(self, vm_path: str, snapshot_name: str) -> None:
        """Revert the VM to one snapshot."""

    def get_ip_address(self, vm_path: str) -> str:
        """Resolve the guest IP address after boot."""


def create_linux_vm_provider(provider_name: str) -> LinuxVMProvider:
    normalized = str(provider_name or "").strip().lower()
    if normalized == "vmware":
        return VMwareLinuxVMProvider()
    raise LinuxVMError(
        "Unsupported Linux VM provider. "
        "Configure vm_provider=vmware or leave vm_provider empty to use an already-running runtime."
    )


@dataclass
class LinuxVMRuntimeSession:
    provider: LinuxVMProvider
    vm_path: str
    runtime_host: str
    started_by_session: bool
    stop_on_exit: bool
    reset_between_tasks: bool
    logger_obj: logging.Logger
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self.stop_on_exit:
            return
        if not self.started_by_session and not self.reset_between_tasks:
            return
        self.logger_obj.info("Stopping Linux VM: %s", self.vm_path)
        self.provider.stop_emulator(self.vm_path)


def start_linux_vm_session(
    config: LinuxRuntimeConfig,
    *,
    provider: LinuxVMProvider | None = None,
    logger_obj: logging.Logger | None = None,
) -> LinuxVMRuntimeSession | None:
    if not config.vm_provider:
        return None

    logger_instance = logger_obj or logger
    provider_instance = provider or create_linux_vm_provider(config.vm_provider)
    vm_path = resolve_linux_vm_path(config, logger_obj=logger_instance)

    if config.vm_reset_between_tasks and not config.vm_snapshot_name:
        raise LinuxVMError(
            "Linux task reset requires a VMware snapshot. "
            "Set vm_snapshot_name (or HELLOWORLD_LINUX_VM_SNAPSHOT_NAME) to a clean baseline snapshot "
            "before running executions with vm_reset_between_tasks=true."
        )

    was_running = provider_instance.is_running(vm_path)
    if config.vm_snapshot_name:
        if was_running:
            logger_instance.info(
                "Linux VM is already running; stopping it before snapshot revert: %s",
                vm_path,
            )
            provider_instance.stop_emulator(vm_path)
        logger_instance.info("Reverting Linux VM snapshot '%s': %s", config.vm_snapshot_name, vm_path)
        provider_instance.revert_to_snapshot(vm_path, config.vm_snapshot_name)
        was_running = False

    if was_running:
        logger_instance.info("Linux VM already running, reusing it: %s", vm_path)
    else:
        logger_instance.info("Starting Linux VM via %s: %s", provider_instance.provider_name, vm_path)
        provider_instance.start_emulator(vm_path, headless=config.vm_headless)

    runtime_host = config.vm_ip
    if config.vm_use_provider_ip:
        runtime_host = provider_instance.get_ip_address(vm_path)
        logger_instance.info("Resolved Linux VM guest IP: %s", runtime_host)
    ensure_linux_guest_runtime(
        config,
        provider=provider_instance,
        vm_path=vm_path,
        runtime_host=runtime_host,
        logger_obj=logger_instance,
    )

    return LinuxVMRuntimeSession(
        provider=provider_instance,
        vm_path=vm_path,
        runtime_host=runtime_host,
        started_by_session=(not was_running) or bool(config.vm_snapshot_name),
        stop_on_exit=config.vm_stop_on_exit,
        reset_between_tasks=config.vm_reset_between_tasks,
        logger_obj=logger_instance,
    )


def resolve_linux_vm_path(
    config: LinuxRuntimeConfig,
    *,
    logger_obj: logging.Logger | None = None,
) -> str:
    logger_instance = logger_obj or logger
    if config.vm_path:
        return str(Path(config.vm_path).expanduser())
    if str(config.vm_provider or "").strip().lower() != "vmware":
        raise LinuxVMError("Automatic Linux VM image resolution is currently supported only for vm_provider=vmware.")

    manager = VMwareLinuxImageManager(config, logger_obj=logger_instance)
    return manager.resolve_vm_path()


def ensure_linux_guest_runtime(
    config: LinuxRuntimeConfig,
    *,
    provider: LinuxVMProvider,
    vm_path: str,
    runtime_host: str,
    logger_obj: logging.Logger | None = None,
) -> None:
    logger_instance = logger_obj or logger
    if _runtime_is_healthy(runtime_host, config.runtime_port, config.runtime_token):
        logger_instance.info(
            "Linux guest runtime already healthy at http://%s:%d",
            runtime_host,
            config.runtime_port,
        )
        return

    if not config.vm_bootstrap_runtime:
        raise LinuxVMError(
            "Linux VM booted, but the guest runtime is not healthy and vm_bootstrap_runtime is disabled."
        )

    if provider.provider_name != "vmware":
        raise LinuxVMError(
            "Automatic Linux guest runtime bootstrap is currently supported only for vm_provider=vmware."
        )

    if not config.vm_guest_username or not config.vm_guest_password:
        raise LinuxVMError(
            "Linux VM booted, but the guest runtime is not healthy and guest bootstrap credentials are missing. "
            "Set vm_guest_username/vm_guest_password, or preconfigure the guest runtime to auto-start."
        )

    logger_instance.info("Bootstrapping Linux guest runtime inside VMware guest...")
    guest = VMwareGuestAgent(
        vm_path=vm_path,
        username=config.vm_guest_username,
        password=config.vm_guest_password,
    )
    guest.bootstrap_runtime(
        runtime_port=config.runtime_port,
        runtime_token=config.runtime_token,
        guest_python_bin=config.vm_guest_python_bin,
        guest_runtime_dir=config.vm_guest_runtime_dir,
        install_deps=config.vm_guest_install_deps,
    )
    _wait_for_runtime_health(
        runtime_host,
        config.runtime_port,
        config.runtime_token,
        timeout_seconds=DEFAULT_RUNTIME_HEALTH_TIMEOUT_SECONDS,
    )


def _runtime_is_healthy(runtime_host: str, runtime_port: int, runtime_token: str) -> bool:
    controller = LinuxRuntimeController(
        runtime_url=f"http://{runtime_host}:{int(runtime_port)}",
        token=str(runtime_token),
        timeout=5.0,
    )
    try:
        payload = controller.health()
    except LinuxRuntimeError:
        return False
    return str(payload.get("status", "")).upper() == "HEALTHY"


def _wait_for_runtime_health(
    runtime_host: str,
    runtime_port: int,
    runtime_token: str,
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _runtime_is_healthy(runtime_host, runtime_port, runtime_token):
            return
        time.sleep(DEFAULT_RUNTIME_HEALTH_POLL_INTERVAL_SECONDS)
    raise LinuxVMError(
        f"Linux guest runtime did not become healthy at http://{runtime_host}:{runtime_port} "
        f"within {int(timeout_seconds)}s."
    )


class VMwareLinuxVMProvider:
    provider_name = "vmware"

    @staticmethod
    def _vmrun_type_tokens() -> list[str]:
        system_name = platform.system()
        if system_name in {"Windows", "Linux"}:
            return ["-T", "ws"]
        if system_name == "Darwin":
            return ["-T", "fusion"]
        raise LinuxVMError(f"Unsupported host OS for vmrun: {system_name}")

    @staticmethod
    def _run_command(
        command: list[str],
        *,
        timeout_seconds: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise LinuxVMError(
                "vmrun is not installed or not on PATH. "
                "Install VMware Workstation/Fusion CLI support before enabling vm_provider=vmware."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LinuxVMError(
                f"VMware command timed out after {timeout_seconds:.0f}s: {' '.join(command)}"
            ) from exc
        except OSError as exc:
            raise LinuxVMError(f"Failed to execute {' '.join(command)}: {exc}") from exc

    @classmethod
    def _require_success(
        cls,
        command: list[str],
        *,
        timeout_seconds: float | None = None,
    ) -> str:
        result = cls._run_command(command, timeout_seconds=timeout_seconds)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise LinuxVMError(f"VMware command failed: {' '.join(command)}: {detail}")
        return result.stdout.strip()

    @staticmethod
    def _normalize_path(raw_path: str) -> str:
        text = str(raw_path).strip()
        if re.match(r"^[A-Za-z]:[\\/]", text):
            drive = text[0].lower()
            tail = text[2:].replace("/", "\\").rstrip("\\")
            return f"{drive}:{tail}"
        return str(Path(text).expanduser().resolve())

    def is_running(self, vm_path: str) -> bool:
        if str(os.getenv(VMWARE_SKIP_RUNNING_CHECK_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}:
            return False
        normalized = self._normalize_path(vm_path)
        output = self._require_success(
            ["vmrun", *self._vmrun_type_tokens(), "list"],
            timeout_seconds=DEFAULT_VMWARE_LIST_TIMEOUT_SECONDS,
        )
        for line in output.splitlines():
            candidate = line.strip()
            if not candidate or not candidate.endswith(".vmx"):
                continue
            try:
                if self._normalize_path(candidate) == normalized:
                    return True
            except OSError:
                if candidate == normalized:
                    return True
        return False

    def start_emulator(self, vm_path: str, *, headless: bool) -> None:
        if self.is_running(vm_path):
            return
        command = ["vmrun", *self._vmrun_type_tokens(), "start", vm_path]
        if headless:
            command.append("nogui")
        self._require_success(command, timeout_seconds=DEFAULT_VMWARE_START_TIMEOUT_SECONDS)

    def stop_emulator(self, vm_path: str) -> None:
        if not self.is_running(vm_path):
            return
        stop_prefix = ["vmrun", *self._vmrun_type_tokens(), "stop", vm_path]
        soft_error: LinuxVMError | None = None
        try:
            self._require_success(
                [*stop_prefix, "soft"],
                timeout_seconds=DEFAULT_VMWARE_STOP_SOFT_TIMEOUT_SECONDS,
            )
        except LinuxVMError as exc:
            soft_error = exc
            logger.warning(
                "Soft stop failed for VMware VM %s; retrying with hard stop: %s",
                vm_path,
                exc,
            )
            self._require_success(
                [*stop_prefix, "hard"],
                timeout_seconds=DEFAULT_VMWARE_STOP_HARD_TIMEOUT_SECONDS,
            )

        deadline = time.time() + DEFAULT_VMWARE_STOP_POLL_TIMEOUT_SECONDS
        last_error: Exception | None = soft_error
        while time.time() < deadline:
            try:
                if not self.is_running(vm_path):
                    return
            except LinuxVMError as exc:
                last_error = exc
            time.sleep(DEFAULT_VMWARE_STOP_POLL_INTERVAL_SECONDS)

        detail = f" Last error: {last_error}" if last_error is not None else ""
        raise LinuxVMError(f"VMware VM still running after stop attempt: {vm_path}.{detail}")

    def revert_to_snapshot(self, vm_path: str, snapshot_name: str) -> None:
        self._require_success(
            ["vmrun", *self._vmrun_type_tokens(), "revertToSnapshot", vm_path, snapshot_name],
            timeout_seconds=DEFAULT_VMWARE_REVERT_TIMEOUT_SECONDS,
        )

    def get_ip_address(self, vm_path: str) -> str:
        deadline = time.time() + DEFAULT_VM_IP_TIMEOUT_SECONDS
        last_error = None
        command = ["vmrun", *self._vmrun_type_tokens(), "getGuestIPAddress", vm_path, "-wait"]
        while time.time() < deadline:
            try:
                output = self._require_success(command)
                if output:
                    return output
                last_error = "empty guest IP"
            except LinuxVMError as exc:
                last_error = str(exc)
            time.sleep(DEFAULT_VM_IP_POLL_INTERVAL_SECONDS)
        raise LinuxVMError(
            f"Timed out waiting for VMware guest IP for {vm_path}. Last error: {last_error or 'unknown'}"
        )


class VMwareGuestAgent:
    def __init__(self, *, vm_path: str, username: str, password: str) -> None:
        self.vm_path = vm_path
        self.username = username
        self.password = password

    @staticmethod
    def _base_command() -> list[str]:
        return [
            "vmrun",
            *VMwareLinuxVMProvider._vmrun_type_tokens(),
        ]

    def _auth_prefix(self) -> list[str]:
        return [
            "-gu",
            self.username,
            "-gp",
            self.password,
        ]

    def _run_vmrun(self, command: list[str]) -> str:
        result = VMwareLinuxVMProvider._run_command(command)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise LinuxVMError(f"VMware guest command failed: {' '.join(command)}: {detail}")
        return result.stdout.strip()

    def _run_vmrun_result(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return VMwareLinuxVMProvider._run_command(command)

    def copy_file_to_guest(self, host_path: Path, guest_path: str) -> None:
        self._run_vmrun(
            [
                *self._base_command(),
                *self._auth_prefix(),
                "CopyFileFromHostToGuest",
                self.vm_path,
                str(host_path),
                guest_path,
            ]
        )

    def run_bash(self, script: str) -> None:
        self._run_vmrun(
            [
                *self._base_command(),
                *self._auth_prefix(),
                "runProgramInGuest",
                self.vm_path,
                "/bin/bash",
                "-lc",
                script,
            ]
        )

    def run_program(self, argv: list[str], *, allow_nonzero: bool = False) -> subprocess.CompletedProcess[str]:
        guest_argv = list(argv)
        if guest_argv and "/" not in guest_argv[0]:
            guest_argv = ["/usr/bin/env", *guest_argv]
        result = self._run_vmrun_result(
            [
                *self._base_command(),
                *self._auth_prefix(),
                "runProgramInGuest",
                self.vm_path,
                *guest_argv,
            ]
        )
        if result.returncode != 0 and not allow_nonzero:
            detail = (result.stderr or result.stdout).strip()
            raise LinuxVMError(
                f"VMware guest command failed: {' '.join([*self._base_command(), *self._auth_prefix(), 'runProgramInGuest', self.vm_path, *guest_argv])}: {detail}"
            )
        return result

    def bootstrap_runtime(
        self,
        *,
        runtime_port: int,
        runtime_token: str,
        guest_python_bin: str,
        guest_runtime_dir: str,
        install_deps: bool,
    ) -> None:
        if not HOST_RUNTIME_SERVER_PATH.exists():
            raise LinuxVMError(f"Host runtime server not found: {HOST_RUNTIME_SERVER_PATH}")

        guest_dir = guest_runtime_dir.rstrip("/") or "/tmp/helloworld_linux_runtime"
        guest_runtime_path = f"{guest_dir}/runtime_server.py"
        self.run_bash(f"mkdir -p {shlex.quote(guest_dir)}")
        self.copy_file_to_guest(HOST_RUNTIME_SERVER_PATH, guest_runtime_path)

        if install_deps:
            deps_check = self.run_program(
                [
                    guest_python_bin,
                    "-c",
                    (
                        "import importlib.util, sys; "
                        "required=['flask','PIL','pyautogui']; "
                        "missing=[name for name in required if importlib.util.find_spec(name) is None]; "
                        "sys.exit(1 if missing else 0)"
                    ),
                ],
                allow_nonzero=True,
            )
            if deps_check.returncode != 0:
                self.run_program(
                    [
                        guest_python_bin,
                        "-m",
                        "pip",
                        "install",
                        "--user",
                        "flask",
                        "Pillow",
                        "pyautogui",
                    ]
                )

        log_file = f"{guest_dir}/runtime_server.log"
        pid_file = f"{guest_dir}/runtime_server.pid"
        xauthority_path = f"/home/{self.username}/.Xauthority"
        start_script = (
            f"set -e; "
            f"mkdir -p {shlex.quote(guest_dir)}; "
            f"export DISPLAY=:0; "
            f"export XAUTHORITY={shlex.quote(xauthority_path)}; "
            f"if [ -f {shlex.quote(pid_file)} ]; then "
            f"old_pid=$(cat {shlex.quote(pid_file)} 2>/dev/null || true); "
            f'if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then '
            f'kill "$old_pid" 2>/dev/null || true; sleep 1; '
            f"fi; "
            f"fi; "
            f"nohup {shlex.quote(guest_python_bin)} {shlex.quote(guest_runtime_path)} "
            f"--host 0.0.0.0 --port {int(runtime_port)} --token {shlex.quote(runtime_token)} "
            f">{shlex.quote(log_file)} 2>&1 </dev/null & "
            f"echo $! >{shlex.quote(pid_file)}"
        )
        self.run_bash(start_script)


class VMwareLinuxImageManager:
    def __init__(self, config: LinuxRuntimeConfig, *, logger_obj: logging.Logger | None = None) -> None:
        self.config = config
        self.logger = logger_obj or logger
        self.storage_dir = Path(config.vm_storage_dir).expanduser().resolve()

    def resolve_vm_path(self) -> str:
        existing = self._find_existing_vmx()
        if existing is not None:
            self.logger.info("Using existing Linux VMware image: %s", existing)
            return str(existing)

        image_url = str(self.config.vm_image_url or "").strip()
        if not image_url:
            raise LinuxVMError(
                "No Linux VMware image found under vm_storage_dir and vm_image_url is not configured."
            )

        archive_path = self._download_archive(image_url)
        self._extract_archive(archive_path)
        resolved = self._find_existing_vmx()
        if resolved is None:
            raise LinuxVMError(
                f"Downloaded Linux VM image from {image_url}, but no .vmx file was found under {self.storage_dir}."
            )
        self.logger.info("Prepared Linux VMware image: %s", resolved)
        return str(resolved)

    def _preferred_name(self) -> str | None:
        text = str(self.config.vm_image_name or "").strip()
        return text.lower() or None

    def _find_existing_vmx(self) -> Path | None:
        if not self.storage_dir.exists():
            return None
        vmx_files = sorted(self.storage_dir.rglob("*.vmx"))
        if not vmx_files:
            return None

        preferred = self._preferred_name()
        if preferred:
            for candidate in vmx_files:
                if candidate.stem.lower() == preferred or candidate.parent.name.lower() == preferred:
                    return candidate.resolve()

        if len(vmx_files) == 1:
            return vmx_files[0].resolve()

        raise LinuxVMError(
            f"Multiple .vmx files were found under {self.storage_dir}. "
            "Set vm_image_name or vm_path to disambiguate which Linux VM HelloWorld should use."
        )

    def _download_archive(self, image_url: str) -> Path:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        filename = str(self.config.vm_image_archive_name or "").strip()
        if not filename:
            parsed = urllib.parse.urlparse(image_url)
            filename = Path(parsed.path).name or "helloworld-linux-vm.zip"
        archive_path = self.storage_dir / filename
        if archive_path.exists() and archive_path.stat().st_size > 0:
            self.logger.info("Using existing Linux VM archive: %s", archive_path)
            return archive_path

        self.logger.info("Downloading Linux VM archive: %s", image_url)
        try:
            urllib.request.urlretrieve(image_url, archive_path)
        except Exception as exc:
            raise LinuxVMError(f"Failed to download Linux VM archive from {image_url}: {exc}") from exc
        return archive_path

    def _extract_archive(self, archive_path: Path) -> None:
        self.logger.info("Extracting Linux VM archive: %s", archive_path)
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(self.storage_dir)
        except zipfile.BadZipFile as exc:
            raise LinuxVMError(f"Linux VM archive is not a valid zip file: {archive_path}") from exc
