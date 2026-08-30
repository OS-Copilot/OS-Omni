#!/usr/bin/env python3
"""Environment doctor for OS-Omni."""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass(frozen=True)
class CheckItem:
    name: str
    ok: bool
    detail: str = ""
    optional: bool = False


def _has_module(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        return False


def _python_version_check(platform_name: str, version_info: tuple[int, int, int] | None = None) -> CheckItem:
    current = version_info or (
        int(sys.version_info.major),
        int(sys.version_info.minor),
        int(sys.version_info.micro),
    )
    minimum = (3, 12, 0) if platform_name == "macos" else (3, 9, 0)
    ok = current >= minimum
    detail = (
        f"current={current[0]}.{current[1]}.{current[2]}, "
        f"required>={minimum[0]}.{minimum[1]}"
    )
    return CheckItem("python version", ok, detail=detail)


def _module_checks(platform_name: str) -> list[CheckItem]:
    items = [
        CheckItem("python-dotenv", _has_module("dotenv")),
        CheckItem("PyYAML", _has_module("yaml")),
        CheckItem("httpx", _has_module("httpx")),
        CheckItem("openai", _has_module("openai")),
        CheckItem("google-genai", _has_module("google.genai")),
        CheckItem("appium-python-client", _has_module("appium")),
        CheckItem("selenium", _has_module("selenium")),
    ]
    if platform_name == "linux":
        items.extend(
            [
                CheckItem("flask", _has_module("flask")),
                CheckItem("Pillow", _has_module("PIL")),
                CheckItem("pyautogui", _has_module("pyautogui")),
                CheckItem("pyatspi", _has_module("pyatspi"), optional=True),
            ]
        )
    if platform_name == "macos":
        items.extend(
            [
                CheckItem("flask (guest runtime)", _has_module("flask"), optional=True),
                CheckItem("pyobjc-core", _has_module("objc"), optional=True),
            ]
        )
    return items


def _command_checks(platform_name: str) -> list[CheckItem]:
    commands: list[tuple[str, bool]] = []
    if platform_name == "linux":
        commands = [
            ("python3", False),
            ("xrandr", False),
            ("xprop", False),
            ("gnome-terminal", True),
            ("xdotool", True),
            ("wmctrl", True),
            ("import", True),
            ("vmrun", True),
        ]
    elif platform_name == "macos":
        commands = [
            ("curl", False),
            ("osascript", False),
        ]
    return [
        CheckItem(name, shutil.which(name) is not None, optional=optional)
        for name, optional in commands
    ]


def _python3_pyatspi_check(platform_name: str) -> CheckItem | None:
    if platform_name != "linux":
        return None
    python3 = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else shutil.which("python3")
    if not python3:
        return CheckItem("system python3 import pyatspi", False, "python3 not found", optional=True)
    try:
        result = subprocess.run(
            [python3, "-c", "import pyatspi; print('ok')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        return CheckItem(
            "system python3 import pyatspi",
            result.returncode == 0 and result.stdout.strip() == "ok",
            detail=result.stderr.strip(),
            optional=True,
        )
    except Exception as exc:
        return CheckItem("system python3 import pyatspi", False, detail=str(exc), optional=True)


def _env_var_checks() -> list[CheckItem]:
    model_vars = [
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "INTERN_API_KEY",
        "TAOBAO_API_KEY",
        "HELLOWORLD_MOCK_API_KEY",
        "HELLOWORLD_SCRIPTED_API_KEY",
    ]
    items = []
    for name in model_vars:
        items.append(CheckItem(name, bool(os.getenv(name)), optional=True))
    return items


def _tart_vm_initialized(vm_dir: Path) -> tuple[bool, str]:
    required = [vm_dir / "config.json", vm_dir / "disk.img", vm_dir / "nvram.bin"]
    missing = [path.name for path in required if not path.exists()]
    if missing:
        return False, f"missing={','.join(missing)} path={vm_dir}"
    return True, f"path={vm_dir}"


def _virtualbuddy_install_finished(vm_bundle_path: Path) -> tuple[bool, str]:
    metadata_path = vm_bundle_path / ".vbdata" / "Metadata.plist"
    if not metadata_path.exists():
        return False, f"metadata missing: {metadata_path}"

    try:
        with metadata_path.open("rb") as fh:
            payload = plistlib.load(fh) or {}
    except Exception as exc:
        return False, f"metadata unreadable: {exc}"

    install_finished = bool(payload.get("installFinished"))
    return install_finished, f"installFinished={int(install_finished)} metadata={metadata_path}"


def _macos_vm_provider_checks() -> list[CheckItem]:
    if platform.system().lower() != "darwin":
        return []

    items: list[CheckItem] = []

    try:
        from platforms.macos.host.runtime_env.virtual_buddy_manager import VirtualBuddyManager
        from platforms.macos.runtime_config import MACOS_RUNTIME_CONFIG_PATH, load_macos_runtime_config
    except Exception as exc:
        items.append(CheckItem("macOS runtime config import", False, detail=str(exc)))
        return items

    try:
        config = load_macos_runtime_config(MACOS_RUNTIME_CONFIG_PATH)
        items.append(CheckItem("macOS runtime config", True, detail=str(MACOS_RUNTIME_CONFIG_PATH)))
    except Exception as exc:
        items.append(CheckItem("macOS runtime config", False, detail=str(exc)))
        return items

    provider = str(config.vm_provider or "tart").strip().lower()
    items.append(CheckItem("configured macOS VM provider", provider in {"virtualbuddy", "tart"}, detail=f"provider={provider}"))

    if provider == "tart":
        tart_ok = shutil.which("tart") is not None
        items.append(CheckItem("tart", tart_ok, detail=shutil.which("tart") or "not found"))
        tart_home = Path(config.tart_home).expanduser() if config.tart_home else Path.home() / ".tart"
        vm_dir = tart_home / "vms" / config.base_vm_name
        initialized, detail = _tart_vm_initialized(vm_dir)
        items.append(CheckItem("configured Tart base VM exists", initialized, detail=f"base_vm_name={config.base_vm_name} {detail}"))
        return items

    app_path = Path("/Applications/VirtualBuddy.app")
    items.append(
        CheckItem(
            "VirtualBuddy.app",
            app_path.exists(),
            detail=str(app_path),
        )
    )
    items.append(CheckItem("vctool", shutil.which("vctool") is not None, detail=shutil.which("vctool") or "not found"))

    manager = VirtualBuddyManager()
    library_exists = manager.vm_library.exists()
    items.append(CheckItem("VirtualBuddy VM library", library_exists, detail=str(manager.vm_library)))

    base_vm_exists = manager.vm_exists(config.base_vm_name)
    items.append(
        CheckItem(
            "configured base VM exists",
            base_vm_exists,
            detail=f"base_vm_name={config.base_vm_name}",
        )
    )
    if base_vm_exists:
        install_finished, detail = _virtualbuddy_install_finished(
            manager.vm_library / f"{config.base_vm_name}.vbvm"
        )
        items.append(CheckItem("configured base VM install finished", install_finished, detail=detail))
    return items


def _macos_system_events_check() -> CheckItem | None:
    if platform.system().lower() != "darwin":
        return None

    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to count every process',
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return CheckItem("System Events accessibility", False, detail=str(exc))

    if result.returncode == 0:
        return CheckItem("System Events accessibility", True)

    detail = (result.stderr or result.stdout or "").strip()
    return CheckItem("System Events accessibility", False, detail=detail)


def _macos_runtime_health_check(timeout_seconds: float = 5.0) -> CheckItem | None:
    if platform.system().lower() != "darwin":
        return None

    try:
        from platforms.macos.runtime_config import MACOS_RUNTIME_CONFIG_PATH, load_macos_runtime_config
    except Exception as exc:
        return CheckItem("macOS runtime /health", False, detail=str(exc))

    try:
        config = load_macos_runtime_config(MACOS_RUNTIME_CONFIG_PATH)
    except Exception as exc:
        return CheckItem("macOS runtime /health", False, detail=str(exc))

    url = f"http://{config.vm_ip}:{config.runtime_port}/health"
    request = Request(
        url,
        headers={"Authorization": f"Bearer {config.vm_token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace").strip()
            return CheckItem(
                "macOS runtime /health",
                response.status == 200,
                detail=f"status={response.status} url={url} body={body}",
            )
    except HTTPError as exc:
        return CheckItem("macOS runtime /health", False, detail=f"HTTP {exc.code} url={url}")
    except URLError as exc:
        return CheckItem("macOS runtime /health", False, detail=f"url={url} error={exc.reason}")
    except Exception as exc:
        return CheckItem("macOS runtime /health", False, detail=f"url={url} error={exc}")


def _print_section(title: str, items: Iterable[CheckItem]) -> None:
    print(title)
    for item in items:
        status = "OK" if item.ok else ("MISS-OPT" if item.optional else "MISS")
        suffix = f" ({item.detail})" if item.detail else ""
        print(f"  [{status}] {item.name}{suffix}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check local OS-Omni environment.")
    parser.add_argument(
        "--platform",
        choices=["auto", "linux", "macos", "base"],
        default="auto",
        help="Which platform profile to validate.",
    )
    parser.add_argument(
        "--check-runtime",
        action="store_true",
        help="Also probe the configured macOS runtime /health endpoint.",
    )
    args = parser.parse_args(argv)

    detected = platform.system().lower()
    platform_name = args.platform
    if platform_name == "auto":
        platform_name = "linux" if detected == "linux" else "macos" if detected == "darwin" else "base"

    print(f"Python: {sys.executable}")
    print(f"Platform profile: {platform_name}")

    module_items = [_python_version_check(platform_name), *_module_checks(platform_name)]
    command_items = _command_checks(platform_name)
    env_items = _env_var_checks()
    maybe_pyatspi = _python3_pyatspi_check(platform_name)
    if maybe_pyatspi is not None:
        command_items.append(maybe_pyatspi)
    if platform_name == "macos":
        command_items.extend(_macos_vm_provider_checks())
        maybe_system_events = _macos_system_events_check()
        if maybe_system_events is not None:
            command_items.append(maybe_system_events)
        if args.check_runtime:
            maybe_runtime_health = _macos_runtime_health_check()
            if maybe_runtime_health is not None:
                command_items.append(maybe_runtime_health)

    _print_section("Python modules", module_items)
    _print_section("System commands", command_items)
    _print_section("Environment variables", env_items)

    missing_required = [item.name for item in [*module_items, *command_items] if not item.ok and not item.optional]
    if missing_required:
        print("Result: FAIL")
        print("Missing required items:")
        for item in missing_required:
            print(f"  - {item}")
        return 1

    print("Result: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
