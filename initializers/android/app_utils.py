"""Shared Android initializer helpers."""

from __future__ import annotations

import time
from typing import Any, Iterable

from platforms.android.apk_cache import ensure_package_installed_from_cache


KNOWN_BENCH_APP_PACKAGES = (
    "chat.delta",
    "com.fsck.k9",
    "com.killt.openshop",
    "me.zhanghai.android.files",
    "net.gsantner.markor",
    "org.documentfoundation.libreoffice",
    "org.fossify.calendar",
    "org.fossify.gallery",
    "org.fossify.math",
    "oss.krtirtho.spotube",
    "com.github.emavgl.piggybankpro",
    "com.google.android.contacts",
    "com.google.android.deskclock",
    "org.tasks",
)


def ensure_package_installed(controller: Any, app_package: str, *, label: str) -> str:
    return ensure_package_installed_from_cache(controller, app_package, label=label)


def force_stop_known_apps(controller: Any, *, except_package: str = "") -> None:
    for package in KNOWN_BENCH_APP_PACKAGES:
        if package != except_package:
            controller.execute_adb(["shell", "am", "force-stop", package])


def foreground_summary(controller: Any) -> str:
    """Return a stable foreground diagnostic without shell grep."""
    parts: list[str] = []
    try:
        activity_dump = str(controller.execute_adb(["shell", "dumpsys", "activity", "activities"]) or "")
        for line in activity_dump.splitlines():
            if "mResumedActivity" in line or "mFocusedActivity" in line or "topResumedActivity" in line:
                parts.append(line.strip())
    except Exception as exc:
        parts.append(f"activity_error={type(exc).__name__}: {exc}")

    try:
        window_dump = str(controller.execute_adb(["shell", "dumpsys", "window"]) or "")
        for line in window_dump.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                parts.append(line.strip())
    except Exception as exc:
        parts.append(f"window_error={type(exc).__name__}: {exc}")

    return " | ".join(parts)


def wait_for_foreground(
    controller: Any,
    app_package: str,
    *,
    timeout_seconds: float = 10.0,
    poll_interval_seconds: float = 0.5,
) -> tuple[bool, str]:
    deadline = time.time() + max(timeout_seconds, 0.0)
    last_summary = ""
    while True:
        last_summary = foreground_summary(controller)
        if app_package in last_summary:
            return True, last_summary
        if time.time() >= deadline:
            return False, last_summary
        time.sleep(max(poll_interval_seconds, 0.1))


def launch_app_cleanly(
    controller: Any,
    *,
    app_package: str,
    app_activity: str = "",
    clear_app_data: bool = False,
    wait_ms: int = 1000,
    stop_other_bench_apps: bool = True,
    foreground_timeout_seconds: float = 10.0,
) -> tuple[bool, str]:
    """Force a clean launch and verify that the target app reaches foreground."""
    if stop_other_bench_apps:
        force_stop_known_apps(controller, except_package=app_package)

    controller.execute_adb(["shell", "am", "force-stop", app_package])
    if clear_app_data:
        controller.execute_adb(["shell", "pm", "clear", app_package])

    if app_activity:
        controller.execute_adb(["shell", "am", "start", "-n", f"{app_package}/{app_activity}"])
    else:
        controller.execute_adb(["shell", "monkey", "-p", app_package, "-c", "android.intent.category.LAUNCHER", "1"])

    if wait_ms > 0:
        time.sleep(wait_ms / 1000.0)

    ok, summary = wait_for_foreground(
        controller,
        app_package,
        timeout_seconds=foreground_timeout_seconds,
    )
    if ok:
        return ok, summary

    # Some packaged activities drift across app versions; monkey is a useful launcher fallback.
    controller.execute_adb(["shell", "monkey", "-p", app_package, "-c", "android.intent.category.LAUNCHER", "1"])
    if wait_ms > 0:
        time.sleep(wait_ms / 1000.0)
    return wait_for_foreground(
        controller,
        app_package,
        timeout_seconds=max(3.0, foreground_timeout_seconds / 2.0),
    )


def force_stop_packages(controller: Any, packages: Iterable[str]) -> None:
    for package in packages:
        package = str(package or "").strip()
        if package:
            controller.execute_adb(["shell", "am", "force-stop", package])
