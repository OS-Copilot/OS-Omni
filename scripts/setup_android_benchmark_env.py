#!/usr/bin/env python3
"""Validate and optionally restore the Android benchmark environment.

This script is intentionally conservative by default.  A plain invocation only
checks host-side files, SDK tools, AVD metadata, and optional local assets.  It
does not connect to or modify a running emulator unless explicit device options
are passed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AVD_NAME = "AndroidWorldAvd"
DEFAULT_DEVICE = "emulator-5554"
REQUIRED_SYSTEM_IMAGE = "system-images;android-33;google_apis;x86_64"
EXPECTED_IMAGE_SYSDIR_UNIX = "system-images/android-33/google_apis/x86_64/"
EXPECTED_IMAGE_SYSDIR_WINDOWS = "system-images\\android-33\\google_apis\\x86_64\\"

REQUIRED_PACKAGES = {
    "app.organicmaps.web": "Organic Maps",
    "chat.delta": "Delta Chat",
    "com.fsck.k9": "K-9 Mail",
    "com.github.emavgl.piggybankpro": "Oinkoin",
    "com.killt.openshop": "OpenShop benchmark app",
    "me.zhanghai.android.files": "Material Files",
    "net.gsantner.markor": "Markor",
    "org.documentfoundation.libreoffice": "LibreOffice Viewer",
    "org.fossify.calendar": "Fossify Calendar",
    "org.fossify.gallery": "Fossify Gallery",
    "org.fossify.math": "Fossify Math",
    "org.tasks": "Tasks.org",
    "oss.krtirtho.spotube": "Spotube",
}

COMM_STATE_TEMPLATES = (
    REPO_ROOT / "assets" / "android_comm_state" / "k9_app_data.tar.gz",
    REPO_ROOT / "assets" / "android_comm_state" / "deltachat_app_data.tar.gz",
)


@dataclass
class CheckResult:
    level: str
    name: str
    message: str


class Reporter:
    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def ok(self, name: str, message: str) -> None:
        self._add("OK", name, message)

    def warn(self, name: str, message: str) -> None:
        self._add("WARN", name, message)

    def fail(self, name: str, message: str) -> None:
        self._add("FAIL", name, message)

    def _add(self, level: str, name: str, message: str) -> None:
        self.results.append(CheckResult(level, name, message))
        print(f"[{level}] {name}: {message}")

    @property
    def has_failures(self) -> bool:
        return any(item.level == "FAIL" for item in self.results)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a cross-platform Android benchmark setup. By default this "
            "does not touch a running emulator."
        )
    )
    parser.add_argument("--avd-name", default=DEFAULT_AVD_NAME)
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--avd-home", default=os.environ.get("ANDROID_AVD_HOME"))
    parser.add_argument("--sdk-root", default=os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT"))
    parser.add_argument(
        "--check-device",
        action="store_true",
        help="Read-only ADB checks against the running emulator/device.",
    )
    parser.add_argument(
        "--check-greenmail",
        action="store_true",
        help="Check GreenMail readiness at --greenmail-url.",
    )
    parser.add_argument(
        "--greenmail-url",
        default="http://127.0.0.1:8081/api/service/readiness",
    )
    parser.add_argument(
        "--restore-comm-state",
        action="store_true",
        help=(
            "Restore K-9 and Delta Chat app data templates. This mutates the "
            "running emulator and should only be used when no benchmark episode is running."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    reporter = Reporter()

    reporter.ok("host", f"{platform.system()} {platform.machine()} / Python {platform.python_version()}")
    sdk_root = resolve_sdk_root(args.sdk_root)
    avd_home = resolve_avd_home(args.avd_home)

    check_android_tools(reporter, sdk_root)
    check_system_image_hint(reporter, sdk_root)
    check_avd_files(reporter, avd_home, args.avd_name)
    check_local_assets(reporter)
    check_optional_apk_cache(reporter)

    if args.check_greenmail:
        check_greenmail(reporter, args.greenmail_url)

    if args.check_device or args.restore_comm_state:
        check_device(reporter, args.device)

    if args.restore_comm_state:
        restore_comm_state(reporter, args.device)

    print()
    if reporter.has_failures:
        print("Android benchmark environment check completed with failures.")
        return 1
    print("Android benchmark environment check completed without failures.")
    return 0


def resolve_sdk_root(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit).expanduser()
    candidates: list[Path] = []
    home = Path.home()
    system = platform.system().lower()
    if system == "windows":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            candidates.append(Path(local_appdata) / "Android" / "Sdk")
        candidates.append(home / "AppData" / "Local" / "Android" / "Sdk")
    elif system == "darwin":
        candidates.append(home / "Library" / "Android" / "sdk")
    else:
        candidates.extend([home / "Android" / "Sdk", home / "android-sdk"])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def resolve_avd_home(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".android" / "avd"


def check_android_tools(reporter: Reporter, sdk_root: Path | None) -> None:
    for tool in ("adb", "emulator", "sdkmanager"):
        resolved = resolve_android_tool(tool, sdk_root)
        if resolved:
            reporter.ok(f"tool:{tool}", str(resolved))
        else:
            reporter.fail(
                f"tool:{tool}",
                "not found in PATH or Android SDK. Install Android SDK command-line tools.",
            )


def resolve_android_tool(tool: str, sdk_root: Path | None) -> Path | None:
    found = shutil.which(tool)
    if found:
        return Path(found)

    if not sdk_root:
        return None

    names = [tool]
    if platform.system().lower() == "windows":
        names.extend([f"{tool}.exe", f"{tool}.bat", f"{tool}.cmd"])

    subdirs = {
        "adb": ["platform-tools"],
        "emulator": ["emulator"],
        "sdkmanager": ["cmdline-tools/latest/bin", "cmdline-tools/bin", "tools/bin"],
    }.get(tool, [""])
    for subdir in subdirs:
        for name in names:
            candidate = sdk_root / subdir / name
            if candidate.exists():
                return candidate
    return None


def check_system_image_hint(reporter: Reporter, sdk_root: Path | None) -> None:
    if not sdk_root:
        reporter.warn("system-image", f"cannot verify {REQUIRED_SYSTEM_IMAGE}; Android SDK root not found")
        return
    image_dir = sdk_root / "system-images" / "android-33" / "google_apis" / "x86_64"
    if image_dir.exists():
        reporter.ok("system-image", str(image_dir))
    else:
        reporter.fail(
            "system-image",
            f"missing {REQUIRED_SYSTEM_IMAGE}. Install it with sdkmanager.",
        )


def check_avd_files(reporter: Reporter, avd_home: Path, avd_name: str) -> None:
    avd_dir = avd_home / f"{avd_name}.avd"
    ini_path = avd_home / f"{avd_name}.ini"
    config_path = avd_dir / "config.ini"
    hardware_path = avd_dir / "hardware-qemu.ini"

    if ini_path.is_file():
        reporter.ok("avd-ini", str(ini_path))
        ini = read_key_value_file(ini_path)
        path_value = ini.get("path")
        if path_value:
            resolved_path = Path(path_value).expanduser()
            if resolved_path == avd_dir:
                reporter.ok("avd-ini:path", path_value)
            else:
                reporter.warn(
                    "avd-ini:path",
                    f"path={path_value!r}; expected local path {avd_dir}",
                )
        else:
            reporter.fail("avd-ini:path", "missing path= entry")
    else:
        reporter.fail("avd-ini", f"missing {ini_path}")

    if avd_dir.is_dir():
        reporter.ok("avd-dir", str(avd_dir))
    else:
        reporter.fail("avd-dir", f"missing {avd_dir}")
        return

    if config_path.is_file():
        reporter.ok("config.ini", str(config_path))
        config = read_key_value_file(config_path)
        check_config_value(reporter, config, "abi.type", "x86_64")
        check_config_value(reporter, config, "hw.lcd.width", "1080")
        check_config_value(reporter, config, "hw.lcd.height", "2400")
        check_config_value(reporter, config, "hw.lcd.density", "420")
        image_sysdir = config.get("image.sysdir.1", "")
        normalized = image_sysdir.replace("\\", "/")
        if normalized == EXPECTED_IMAGE_SYSDIR_UNIX:
            reporter.ok("config.ini:image.sysdir.1", image_sysdir)
        else:
            reporter.warn(
                "config.ini:image.sysdir.1",
                f"{image_sysdir!r}; expected {EXPECTED_IMAGE_SYSDIR_UNIX!r}",
            )
    else:
        reporter.fail("config.ini", f"missing {config_path}")

    if hardware_path.exists():
        text = hardware_path.read_text(encoding="utf-8", errors="replace")
        if "C:\\Users\\" in text or "\\Android\\Sdk" in text:
            reporter.warn(
                "hardware-qemu.ini",
                "contains exported Windows host paths; delete it before first launch on Linux/macOS.",
            )
        else:
            reporter.ok("hardware-qemu.ini", "present without obvious Windows paths")
    else:
        reporter.ok("hardware-qemu.ini", "missing; emulator will regenerate it")


def check_config_value(reporter: Reporter, payload: dict[str, str], key: str, expected: str) -> None:
    actual = payload.get(key)
    if actual == expected:
        reporter.ok(f"config.ini:{key}", actual)
    else:
        reporter.warn(f"config.ini:{key}", f"{actual!r}; expected {expected!r}")


def read_key_value_file(path: Path) -> dict[str, str]:
    payload: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        payload[key.strip()] = value.strip()
    return payload


def check_local_assets(reporter: Reporter) -> None:
    for path in COMM_STATE_TEMPLATES:
        if path.is_file():
            reporter.ok(f"asset:{path.name}", f"{path} ({path.stat().st_size} bytes)")
        else:
            reporter.warn(f"asset:{path.name}", f"missing optional local template: {path}")


def check_optional_apk_cache(reporter: Reporter) -> None:
    apk_dirs = [REPO_ROOT / "assets" / "android_apks", REPO_ROOT / ".cache" / "apks"]
    found = [path for root in apk_dirs if root.exists() for path in root.glob("*.apk")]
    if found:
        reporter.ok("apk-cache", f"{len(found)} APK files available")
    else:
        reporter.warn(
            "apk-cache",
            "no local APK cache found. This is OK for the packaged AVD, but fresh AVD setup cannot install apps offline yet.",
        )


def check_greenmail(reporter: Reporter, readiness_url: str) -> None:
    try:
        with urllib.request.urlopen(readiness_url, timeout=5) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        reporter.fail("greenmail", f"not ready at {readiness_url}: {exc}")
        return
    if "Service running" in body or "RUNNING" in body.upper():
        reporter.ok("greenmail", readiness_url)
    else:
        reporter.warn("greenmail", f"unexpected readiness payload: {body[:200]!r}")


def check_device(reporter: Reporter, device: str) -> None:
    adb = shutil.which("adb")
    if not adb:
        reporter.fail("device", "adb not found")
        return

    state = run_adb(adb, device, ["get-state"])
    if state.returncode != 0 or "device" not in state.stdout:
        reporter.fail("device", f"{device} is not connected: {state.stderr.strip() or state.stdout.strip()}")
        return
    reporter.ok("device", f"{device} is connected")

    root = run_adb(adb, device, ["root"], timeout=15)
    root_text = f"{root.stdout}\n{root.stderr}".lower()
    if "cannot run as root" in root_text or "production builds" in root_text:
        reporter.fail("adb-root", root_text.strip())
    else:
        reporter.ok("adb-root", (root.stdout or root.stderr or "root accepted").strip())
        run_adb(adb, device, ["wait-for-device"], timeout=15)

    props = {
        "android-version": ["shell", "getprop", "ro.build.version.release"],
        "api-level": ["shell", "getprop", "ro.build.version.sdk"],
        "abi": ["shell", "getprop", "ro.product.cpu.abi"],
        "model": ["shell", "getprop", "ro.product.model"],
    }
    for name, adb_args in props.items():
        result = run_adb(adb, device, adb_args)
        reporter.ok(name, result.stdout.strip() or "<empty>")

    size = run_adb(adb, device, ["shell", "wm", "size"])
    density = run_adb(adb, device, ["shell", "wm", "density"])
    reporter.ok("wm-size", size.stdout.strip() or "<empty>")
    reporter.ok("wm-density", density.stdout.strip() or "<empty>")

    package_result = run_adb(adb, device, ["shell", "pm", "list", "packages"])
    installed = {
        line.strip().removeprefix("package:")
        for line in package_result.stdout.splitlines()
        if line.strip().startswith("package:")
    }
    missing = [f"{package} ({label})" for package, label in REQUIRED_PACKAGES.items() if package not in installed]
    if missing:
        reporter.fail("packages", "missing: " + ", ".join(missing))
    else:
        reporter.ok("packages", f"all {len(REQUIRED_PACKAGES)} benchmark packages found")


def run_adb(adb: str, device: str, args: Iterable[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [adb, "-s", device, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def restore_comm_state(reporter: Reporter, device: str) -> None:
    from platforms.android.comm_state import ensure_adb_reverse_for_greenmail, restore_app_data_template
    from platforms.android.controller import AdbController

    controller = AdbController(adb_device=device)
    ensure_adb_reverse_for_greenmail(controller)
    for app_name in ("k9", "deltachat"):
        restored = restore_app_data_template(controller, app_name)
        reporter.ok(f"restore:{app_name}", str(restored))


if __name__ == "__main__":
    raise SystemExit(main())
