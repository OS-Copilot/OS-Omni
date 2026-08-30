"""Optional Windows VMware lifecycle support for benchmark executions."""

from __future__ import annotations

import logging
import io
import platform
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from platforms.windows.runtime_config import WindowsRuntimeConfig
from platforms.windows.runtime_env.controller import WindowsRuntimeController, WindowsRuntimeError

logger = logging.getLogger(__name__)

DEFAULT_VM_IP_TIMEOUT_SECONDS = 180.0
DEFAULT_VM_IP_POLL_INTERVAL_SECONDS = 3.0
DEFAULT_VMWARE_LIST_TIMEOUT_SECONDS = 20.0
DEFAULT_VMWARE_START_TIMEOUT_SECONDS = 90.0
DEFAULT_VMWARE_STOP_SOFT_TIMEOUT_SECONDS = 90.0
DEFAULT_VMWARE_STOP_HARD_TIMEOUT_SECONDS = 120.0
DEFAULT_VMWARE_STOP_POLL_TIMEOUT_SECONDS = 30.0
DEFAULT_VMWARE_STOP_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_VMWARE_REVERT_TIMEOUT_SECONDS = 240.0
DEFAULT_RUNTIME_HEALTH_TIMEOUT_SECONDS = 75.0
DEFAULT_RUNTIME_HEALTH_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_RUNTIME_POWERSHELL_SMOKE_TIMEOUT_SECONDS = 10
DEFAULT_RUNTIME_BOOTSTRAP_ATTEMPTS = 3
DEFAULT_RUNTIME_SCREEN_WIDTH = 1920
DEFAULT_RUNTIME_SCREEN_HEIGHT = 1080
HOST_WINDOWS_SETUP_DIR = Path(__file__).resolve().parents[1] / "vm" / "setup"
HOST_WINDOWS_SERVER_DIR = HOST_WINDOWS_SETUP_DIR / "server"
HOST_WINDOWS_RUNTIME_FILES = (
    (HOST_WINDOWS_SETUP_DIR / "start-helloworld-server.cmd", r"start-helloworld-server.cmd"),
    (HOST_WINDOWS_SETUP_DIR / "watch-helloworld-server.ps1", r"watch-helloworld-server.ps1"),
    (HOST_WINDOWS_SETUP_DIR / "arrange-sota-desktop.py", r"arrange-sota-desktop.py"),
    (HOST_WINDOWS_SERVER_DIR / "helloworld_server.py", r"server\helloworld_server.py"),
    (HOST_WINDOWS_SERVER_DIR / "helloworld_requirements.txt", r"server\helloworld_requirements.txt"),
)
DEFAULT_GUEST_RUNTIME_DIR_NAME = "HelloWorldRuntime"


class WindowsVMError(RuntimeError):
    """VM lifecycle failure for the Windows benchmark runtime."""


@dataclass
class WindowsVMRuntimeSession:
    provider: "VMwareWindowsVMProvider"
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
        self.logger_obj.info("Stopping Windows VM: %s", self.vm_path)
        self.provider.stop_emulator(self.vm_path)


def start_windows_vm_session(
    config: WindowsRuntimeConfig,
    *,
    logger_obj: logging.Logger | None = None,
) -> WindowsVMRuntimeSession | None:
    if not config.vm_provider:
        return None

    normalized_provider = config.vm_provider.strip().lower()
    if normalized_provider != "vmware":
        raise WindowsVMError(
            "Unsupported Windows VM provider. Configure vm_provider=vmware or leave vm_provider empty."
        )
    if not config.vm_path:
        raise WindowsVMError("Windows vm_provider=vmware requires vm_path in configs/windows.yaml.")
    if config.vm_reset_between_tasks and not config.vm_snapshot_name:
        raise WindowsVMError(
            "Windows task reset requires a VMware snapshot. Set vm_snapshot_name to a clean baseline snapshot."
        )

    logger_instance = logger_obj or logger
    provider = VMwareWindowsVMProvider(vm_password=config.vm_password)
    vm_path = str(Path(config.vm_path).expanduser())

    was_running = provider.is_running(vm_path)
    if config.vm_snapshot_name:
        if was_running:
            logger_instance.info("Windows VM is already running; stopping before snapshot revert: %s", vm_path)
            provider.stop_emulator(vm_path)
        logger_instance.info("Reverting Windows VM snapshot '%s': %s", config.vm_snapshot_name, vm_path)
        provider.revert_to_snapshot(vm_path, config.vm_snapshot_name)
        was_running = False

    if was_running:
        logger_instance.info("Windows VM already running, reusing it: %s", vm_path)
    else:
        logger_instance.info("Starting Windows VM via VMware: %s", vm_path)
        provider.start_emulator(vm_path, headless=config.vm_headless)

    runtime_host = config.vm_ip.strip()
    if config.vm_use_provider_ip:
        runtime_host = provider.get_ip_address(vm_path)
        logger_instance.info("Resolved Windows VM guest IP: %s", runtime_host)
    if not runtime_host:
        raise WindowsVMError(
            "Windows runtime host is empty. Set vm_ip or enable vm_use_provider_ip so VMware can resolve it."
        )
    ensure_windows_guest_runtime(
        config,
        provider=provider,
        vm_path=vm_path,
        runtime_host=runtime_host,
        logger_obj=logger_instance,
    )

    return WindowsVMRuntimeSession(
        provider=provider,
        vm_path=vm_path,
        runtime_host=runtime_host,
        started_by_session=(not was_running) or bool(config.vm_snapshot_name),
        stop_on_exit=config.vm_stop_on_exit,
        reset_between_tasks=config.vm_reset_between_tasks,
        logger_obj=logger_instance,
    )


class VMwareWindowsVMProvider:
    def __init__(self, *, vm_password: str | None = None) -> None:
        self._vm_password = vm_password

    @staticmethod
    def _vmrun_type_tokens() -> list[str]:
        system_name = platform.system().lower()
        if system_name == "darwin":
            return ["-T", "fusion"]
        if system_name in {"windows", "linux"}:
            return ["-T", "ws"]
        raise WindowsVMError(f"Unsupported host OS for vmrun: {system_name}")

    def _vmrun_prefix(self) -> list[str]:
        command = ["vmrun", *self._vmrun_type_tokens()]
        if self._vm_password:
            command.extend(["-vp", self._vm_password])
        return command

    @staticmethod
    def _display_command(command: list[str]) -> str:
        redacted: list[str] = []
        skip_next = False
        for token in command:
            if skip_next:
                redacted.append("***")
                skip_next = False
                continue
            redacted.append(token)
            if token in {"-vp", "-gp"}:
                skip_next = True
        return " ".join(redacted)

    def _run_command(self, command: list[str], *, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                capture_output=True,
                timeout=timeout_seconds,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise WindowsVMError(
                "vmrun is not installed or not on PATH. Install VMware CLI support before enabling vm_provider=vmware."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise WindowsVMError(
                f"VMware command timed out after {timeout_seconds:.0f}s: {self._display_command(command)}"
            ) from exc

    def _require_success(self, command: list[str], *, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        result = self._run_command(command, timeout_seconds=timeout_seconds)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise WindowsVMError(f"VMware command failed: {self._display_command(command)}: {detail}")
        return result

    @staticmethod
    def _normalize_path(vm_path: str) -> str:
        return str(Path(vm_path).expanduser()).replace("\\", "/").lower()

    def is_running(self, vm_path: str) -> bool:
        normalized = self._normalize_path(vm_path)
        result = self._require_success(
            [*self._vmrun_prefix(), "list"],
            timeout_seconds=DEFAULT_VMWARE_LIST_TIMEOUT_SECONDS,
        )
        for line in result.stdout.splitlines():
            candidate = line.strip()
            if candidate and candidate.endswith(".vmx") and self._normalize_path(candidate) == normalized:
                return True
        return False

    def start_emulator(self, vm_path: str, *, headless: bool) -> None:
        if self.is_running(vm_path):
            return
        command = [*self._vmrun_prefix(), "start", vm_path]
        command.append("nogui" if headless else "gui")
        try:
            self._require_success(command, timeout_seconds=DEFAULT_VMWARE_START_TIMEOUT_SECONDS)
            return
        except WindowsVMError as first_error:
            time.sleep(5)
            if self.is_running(vm_path):
                return
            try:
                self._require_success(command, timeout_seconds=DEFAULT_VMWARE_START_TIMEOUT_SECONDS)
                return
            except WindowsVMError as second_error:
                raise WindowsVMError(
                    f"VMware start failed twice for {vm_path}. "
                    f"First error: {first_error}; second error: {second_error}"
                ) from second_error

    def stop_emulator(self, vm_path: str) -> None:
        if not self.is_running(vm_path):
            return
        stop_prefix = [*self._vmrun_prefix(), "stop", vm_path]
        try:
            self._require_success([*stop_prefix, "soft"], timeout_seconds=DEFAULT_VMWARE_STOP_SOFT_TIMEOUT_SECONDS)
        except WindowsVMError:
            self._require_success([*stop_prefix, "hard"], timeout_seconds=DEFAULT_VMWARE_STOP_HARD_TIMEOUT_SECONDS)

        deadline = time.time() + DEFAULT_VMWARE_STOP_POLL_TIMEOUT_SECONDS
        while time.time() < deadline:
            if not self.is_running(vm_path):
                return
            time.sleep(DEFAULT_VMWARE_STOP_POLL_INTERVAL_SECONDS)
        raise WindowsVMError(f"VMware VM still running after stop attempt: {vm_path}")

    def revert_to_snapshot(self, vm_path: str, snapshot_name: str) -> None:
        self._require_success(
            [*self._vmrun_prefix(), "revertToSnapshot", vm_path, snapshot_name],
            timeout_seconds=DEFAULT_VMWARE_REVERT_TIMEOUT_SECONDS,
        )

    def get_ip_address(self, vm_path: str) -> str:
        deadline = time.time() + DEFAULT_VM_IP_TIMEOUT_SECONDS
        last_error = None
        command = [*self._vmrun_prefix(), "getGuestIPAddress", vm_path, "-wait"]
        while time.time() < deadline:
            try:
                result = self._require_success(command, timeout_seconds=DEFAULT_VM_IP_POLL_INTERVAL_SECONDS + 5)
                candidate = result.stdout.strip()
                if candidate:
                    return candidate
            except WindowsVMError as exc:
                last_error = exc
            time.sleep(DEFAULT_VM_IP_POLL_INTERVAL_SECONDS)
        raise WindowsVMError(f"Timed out waiting for VMware guest IP for {vm_path}. Last error: {last_error}")

    def run_program_in_guest(
        self,
        vm_path: str,
        *,
        username: str,
        password: str,
        program: str,
        args: list[str],
        timeout_seconds: float = 60.0,
        interactive: bool = False,
        no_wait: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            *self._vmrun_prefix(),
            "-gu",
            username,
            "-gp",
            password,
            "runProgramInGuest",
            vm_path,
        ]
        if interactive:
            command.append("-interactive")
        if no_wait:
            command.append("-noWait")
        command.extend(
            [
                program,
                *args,
            ]
        )
        result = self._run_command(command, timeout_seconds=timeout_seconds)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise WindowsVMError(f"VMware guest command failed: {self._display_command(command)}: {detail}")
        return result

    def copy_file_to_guest(
        self,
        vm_path: str,
        *,
        username: str,
        password: str,
        host_path: Path,
        guest_path: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        command = [
            *self._vmrun_prefix(),
            "-gu",
            username,
            "-gp",
            password,
            "CopyFileFromHostToGuest",
            vm_path,
            str(host_path),
            guest_path,
        ]
        result = self._run_command(command, timeout_seconds=timeout_seconds)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise WindowsVMError(f"VMware guest file copy failed: {self._display_command(command)}: {detail}")


def ensure_windows_guest_runtime(
    config: WindowsRuntimeConfig,
    *,
    provider: VMwareWindowsVMProvider,
    vm_path: str,
    runtime_host: str,
    logger_obj: logging.Logger | None = None,
) -> None:
    logger_instance = logger_obj or logger
    if _runtime_is_ready(runtime_host, config.runtime_port, config.runtime_token):
        logger_instance.info(
            "Windows guest runtime already ready at http://%s:%d",
            runtime_host,
            config.runtime_port,
        )
        return

    if not config.vm_bootstrap_runtime:
        raise WindowsVMError(
            "Windows VM booted, but the guest runtime is not healthy and vm_bootstrap_runtime is disabled."
        )
    if not config.vm_guest_username or not config.vm_guest_password:
        raise WindowsVMError(
            "Windows VM booted, but the guest runtime is not healthy and guest bootstrap credentials are missing. "
            "Set vm_guest_username/vm_guest_password, or preconfigure the guest runtime to auto-start."
        )

    logger_instance.warning("Bootstrapping Windows guest runtime inside VMware guest...")
    guest = VMwareWindowsGuestAgent(
        provider=provider,
        vm_path=vm_path,
        username=config.vm_guest_username,
        password=config.vm_guest_password,
    )
    last_bootstrap_error: WindowsVMError | None = None
    for attempt in range(DEFAULT_RUNTIME_BOOTSTRAP_ATTEMPTS):
        try:
            guest.bootstrap_runtime(runtime_port=config.runtime_port, runtime_token=config.runtime_token)
        except WindowsVMError as exc:
            last_bootstrap_error = exc
            logger_instance.warning(
                "Windows guest runtime bootstrap command reported an error "
                "(attempt %d/%d); checking health before retrying/failing: %s",
                attempt + 1,
                DEFAULT_RUNTIME_BOOTSTRAP_ATTEMPTS,
                exc,
            )
        else:
            last_bootstrap_error = None

        try:
            _wait_for_runtime_ready(
                runtime_host,
                config.runtime_port,
                config.runtime_token,
                timeout_seconds=DEFAULT_RUNTIME_HEALTH_TIMEOUT_SECONDS,
            )
            if last_bootstrap_error is not None:
                logger_instance.warning(
                    "Windows guest runtime became ready despite bootstrap command error; continuing."
                )
            return
        except WindowsVMError:
            if attempt < DEFAULT_RUNTIME_BOOTSTRAP_ATTEMPTS - 1:
                time.sleep(DEFAULT_RUNTIME_HEALTH_POLL_INTERVAL_SECONDS)
                continue
            if last_bootstrap_error is not None:
                raise last_bootstrap_error
            raise


def _runtime_is_healthy(runtime_host: str, runtime_port: int, runtime_token: str) -> bool:
    controller = WindowsRuntimeController(
        runtime_url=f"http://{runtime_host}:{int(runtime_port)}",
        token=str(runtime_token),
        timeout=5.0,
    )
    try:
        payload = controller.health()
    except WindowsRuntimeError:
        return False
    return str(payload.get("status", "")).upper() == "HEALTHY"


def _runtime_powershell_smoke_ok(runtime_host: str, runtime_port: int, runtime_token: str) -> bool:
    controller = WindowsRuntimeController(
        runtime_url=f"http://{runtime_host}:{int(runtime_port)}",
        token=str(runtime_token),
        timeout=5.0,
    )
    try:
        result = controller.run_powershell_script(
            "'HELLOWORLD_PS_OK'",
            timeout=DEFAULT_RUNTIME_POWERSHELL_SMOKE_TIMEOUT_SECONDS,
        )
    except WindowsRuntimeError:
        return False
    output = str(result.get("output") or "")
    return str(result.get("status") or "").lower() == "success" and "HELLOWORLD_PS_OK" in output


def _runtime_screenshot_smoke_ok(runtime_host: str, runtime_port: int, runtime_token: str) -> bool:
    controller = WindowsRuntimeController(
        runtime_url=f"http://{runtime_host}:{int(runtime_port)}",
        token=str(runtime_token),
        timeout=8.0,
    )
    try:
        observation = controller.observe(include_ui_tree=False, include_screenshot_data=True)
    except WindowsRuntimeError:
        return False

    screenshot_data = observation.screenshot_data or b""
    if observation.width != DEFAULT_RUNTIME_SCREEN_WIDTH or observation.height != DEFAULT_RUNTIME_SCREEN_HEIGHT:
        return False
    if len(screenshot_data) < 50_000:
        return False

    try:
        from PIL import Image

        image = Image.open(io.BytesIO(screenshot_data)).convert("RGB")
        if image.size != (DEFAULT_RUNTIME_SCREEN_WIDTH, DEFAULT_RUNTIME_SCREEN_HEIGHT):
            return False
        sample = image.resize((64, 36))
        pixels = list(sample.getdata())
    except Exception:
        return False

    extrema = sample.getextrema()
    channel_ranges = [high - low for low, high in extrema]
    if max(channel_ranges) <= 5:
        return False

    unique_sample = len(set(pixels))
    if unique_sample <= 4:
        return False

    mean = tuple(sum(pixel[index] for pixel in pixels) / len(pixels) for index in range(3))
    if max(mean) <= 4.0:
        return False

    return True


def _runtime_is_ready(runtime_host: str, runtime_port: int, runtime_token: str) -> bool:
    return _runtime_is_healthy(runtime_host, runtime_port, runtime_token) and _runtime_powershell_smoke_ok(
        runtime_host,
        runtime_port,
        runtime_token,
    ) and _runtime_screenshot_smoke_ok(
        runtime_host,
        runtime_port,
        runtime_token,
    )


def _wait_for_runtime_ready(
    runtime_host: str,
    runtime_port: int,
    runtime_token: str,
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _runtime_is_ready(runtime_host, runtime_port, runtime_token):
            return
        time.sleep(DEFAULT_RUNTIME_HEALTH_POLL_INTERVAL_SECONDS)
    raise WindowsVMError(
        f"Windows guest runtime did not become ready at http://{runtime_host}:{runtime_port} "
        f"(/health plus /run_powershell plus 1920x1080 screenshot smoke test) "
        f"within {int(timeout_seconds)}s."
    )


class VMwareWindowsGuestAgent:
    def __init__(
        self,
        *,
        provider: VMwareWindowsVMProvider,
        vm_path: str,
        username: str,
        password: str,
    ) -> None:
        self.provider = provider
        self.vm_path = vm_path
        self.username = username
        self.password = password

    def run_powershell(self, script: str, *, timeout_seconds: float = 60.0) -> None:
        self.provider.run_program_in_guest(
            self.vm_path,
            username=self.username,
            password=self.password,
            program=r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            args=[
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            timeout_seconds=timeout_seconds,
        )

    def copy_file_to_guest(self, host_path: Path, guest_path: str, *, timeout_seconds: float = 60.0) -> None:
        if not host_path.exists():
            raise WindowsVMError(f"Host runtime file not found: {host_path}")
        self.provider.copy_file_to_guest(
            self.vm_path,
            username=self.username,
            password=self.password,
            host_path=host_path,
            guest_path=guest_path,
            timeout_seconds=timeout_seconds,
        )

    def bootstrap_runtime(self, *, runtime_port: int, runtime_token: str) -> None:
        guest_user = self.username.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] or "User"
        guest_runtime_dir = rf"C:\Users\{guest_user}\AppData\Local\Temp\{DEFAULT_GUEST_RUNTIME_DIR_NAME}"
        guest_server_dir = rf"{guest_runtime_dir}\server"
        self.run_powershell(
            rf"""
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path '{guest_runtime_dir}' | Out-Null
New-Item -ItemType Directory -Force -Path '{guest_server_dir}' | Out-Null
""",
            timeout_seconds=30.0,
        )
        for host_path, relative_guest_path in HOST_WINDOWS_RUNTIME_FILES:
            self.copy_file_to_guest(host_path, rf"{guest_runtime_dir}\{relative_guest_path}")

        script = rf"""
$ErrorActionPreference = 'Continue'
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change standby-timeout-dc 0 | Out-Null
powercfg /change monitor-timeout-ac 0 | Out-Null
powercfg /change monitor-timeout-dc 0 | Out-Null
powercfg /hibernate off | Out-Null
Get-CimInstance Win32_NetworkAdapter -ErrorAction SilentlyContinue |
  Where-Object {{ $_.NetEnabled -eq $true }} |
  ForEach-Object {{
    try {{
      $pnp = Get-CimInstance MSPower_DeviceEnable -Namespace root\wmi -Filter "InstanceName LIKE '$($_.PNPDeviceID.Replace('\', '\\'))%'" -ErrorAction SilentlyContinue
      if ($pnp) {{
        $pnp.Enable = $false
        Set-CimInstance -InputObject $pnp -ErrorAction SilentlyContinue | Out-Null
      }}
    }} catch {{}}
  }}
Get-CimInstance Win32_Process |
  Where-Object {{ ($_.ProcessId -ne $PID) -and (($_.CommandLine -like '*helloworld_server.py*') -or ($_.CommandLine -like '*start-helloworld-server.cmd*') -or ($_.CommandLine -like '*watch-helloworld-server.ps1*')) }} |
  ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}
Start-Sleep -Seconds 2
$scriptFolder = '{guest_runtime_dir}'
$watchdogScript = Join-Path $scriptFolder 'watch-helloworld-server.ps1'
if (-not (Test-Path $watchdogScript)) {{
  throw "HelloWorld runtime launcher/watchdog not found under $scriptFolder"
}}
$global:LASTEXITCODE = 0
exit 0
"""
        self.run_powershell(script, timeout_seconds=90.0)
        self.provider.run_program_in_guest(
            self.vm_path,
            username=self.username,
            password=self.password,
            program=r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            args=[
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                rf"{guest_runtime_dir}\watch-helloworld-server.ps1",
                "-ScriptFolder",
                guest_runtime_dir,
                "-Port",
                str(int(runtime_port)),
                "-Token",
                str(runtime_token),
            ],
            timeout_seconds=30.0,
            interactive=True,
            no_wait=True,
        )
