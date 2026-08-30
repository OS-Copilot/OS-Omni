"""Install Android benchmark apps from the local APK cache when needed."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
COMM_STATE_ASSET_DIR = REPO_ROOT / "assets" / "android_comm_state"
APK_CACHE_DIR = REPO_ROOT / ".cache" / "apks"
DEFAULT_APK_SEARCH_DIRS = (COMM_STATE_ASSET_DIR, APK_CACHE_DIR)

DEFAULT_APK_CACHE: dict[str, str] = {
    "com.fsck.k9": "com.fsck.k9_39034.apk",
    "chat.delta": "deltachat-gplay-release-2.47.0.apk",
    "com.github.emavgl.piggybankpro": "app-x86_64-pro-release.apk",
    "me.zhanghai.android.files": "me.zhanghai.android.files_39.apk",
    "net.gsantner.markor": "net.gsantner.markor_163.apk",
    "org.documentfoundation.libreoffice": "org.documentfoundation.libreoffice_113.apk",
    "org.fossify.calendar": "calendar-20-foss-release.apk",
    "org.fossify.gallery": "org.fossify.gallery_28.apk",
    "org.fossify.math": "org.fossify.math_10.apk",
    "org.tasks": "org.tasks_150204.apk",
    "oss.krtirtho.spotube": "oss.krtirtho.spotube_44.apk",
    "app.organicmaps.web": "OrganicMaps-26040708-web-release.apk",
}


def package_path(
    controller: Any,
    package_name: str,
    *,
    attempts: int = 6,
    delay_seconds: float = 1.0,
) -> str:
    last_output = ""
    for attempt in range(max(1, attempts)):
        controller.execute_adb(["wait-for-device"])
        if attempt:
            time.sleep(max(delay_seconds, 0.0))
        output = _query_package_path(controller, package_name)
        if "package:" in output:
            return output
        last_output = output
    return last_output


def _query_package_path(controller: Any, package_name: str) -> str:
    outputs = [
        str(controller.execute_adb(["shell", "pm", "path", package_name]) or "").strip(),
        str(controller.execute_adb(["shell", "cmd", "package", "path", package_name]) or "").strip(),
    ]
    for output in outputs:
        if "package:" in output:
            return output

    listed = str(controller.execute_adb(["shell", "pm", "list", "packages", package_name]) or "").strip()
    if any(line.strip() == f"package:{package_name}" for line in listed.splitlines()):
        return f"package:{package_name}"
    return "\n".join(output for output in [*outputs, listed] if output)


def ensure_package_installed_from_cache(
    controller: Any,
    package_name: str,
    *,
    label: str,
    cache_dir: str | Path | None = None,
) -> str:
    """Return pm path, installing a known cached APK first if the package is missing."""
    installed_path = package_path(controller, package_name)
    if "package:" in installed_path:
        return installed_path

    apk_name = DEFAULT_APK_CACHE.get(package_name)
    search_dirs = (Path(cache_dir),) if cache_dir else DEFAULT_APK_SEARCH_DIRS
    apk_path = None
    for search_dir in search_dirs:
        candidate = search_dir / apk_name if apk_name else None
        if candidate is not None and candidate.is_file():
            apk_path = candidate
            break
    if apk_path is None or not apk_path.is_file():
        raise RuntimeError(f"{label} is not installed: {package_name}")

    controller.execute_adb(["wait-for-device"])
    install_output = str(controller.execute_adb(["install", "-r", str(apk_path)]) or "")
    controller.execute_adb(["wait-for-device"])
    time.sleep(1.0)
    installed_path = package_path(controller, package_name, attempts=6, delay_seconds=1.0)
    if "package:" in installed_path:
        return installed_path

    raise RuntimeError(
        f"{label} is not installed: {package_name}; cached APK install did not make it available. "
        f"install_output={install_output.strip()!r}, apk={apk_path}"
    )
