"""Shared Android storage helpers for benchmark initializers and evaluators."""

from __future__ import annotations

import base64
import shlex
import tempfile
import time
from pathlib import PurePosixPath, Path
from typing import Any, Iterable, Sequence

from initializers.android.app_utils import force_stop_known_apps
from platforms.android.apk_cache import ensure_package_installed_from_cache
from platforms.android.bootstrap import AndroidBootstrapDriver


def ensure_app_installed(controller: Any, app_package: str, *, label: str) -> str:
    return ensure_package_installed_from_cache(controller, app_package, label=label)


def clear_and_launch_app(
    controller: Any,
    *,
    app_package: str,
    app_activity: str,
    clear_app_data: bool,
    wait_ms: int,
) -> None:
    # Storage apps often show Android permission screens on the first launch.
    # Initializers grant permissions immediately after launching, so foreground
    # verification here would make a valid permission screen look like a failed
    # app launch.
    force_stop_known_apps(controller, except_package=app_package)
    controller.execute_adb(["shell", "am", "force-stop", app_package])
    if clear_app_data:
        controller.execute_adb(["shell", "pm", "clear", app_package])
    controller.execute_adb(["shell", "am", "start", "-n", f"{app_package}/{app_activity}"])
    if wait_ms > 0:
        time.sleep(wait_ms / 1000.0)


def ensure_directory(controller: Any, remote_path: str) -> None:
    quoted = shlex.quote(remote_path)
    controller.execute_adb(["shell", f"mkdir -p {quoted}"])


def remove_path(controller: Any, remote_path: str) -> None:
    quoted = shlex.quote(remote_path)
    controller.execute_adb(["shell", f"rm -rf {quoted}"])


def delete_media_store_relative_dirs(controller: Any, relative_dirs: Iterable[str]) -> None:
    for relative_dir in relative_dirs:
        cleaned = str(relative_dir or "").strip().strip("/")
        if not cleaned:
            continue
        if not cleaned.endswith("/"):
            cleaned += "/"
        escaped = cleaned.replace("'", "'\\''")
        controller.execute_adb(
            [
                "shell",
                (
                    "content delete --uri content://media/external/images/media "
                    f"--where relative_path=\\'{escaped}\\'"
                ),
            ]
        )


def push_bytes(controller: Any, remote_path: str, payload: bytes) -> None:
    remote = PurePosixPath(remote_path)
    ensure_directory(controller, str(remote.parent))
    with tempfile.TemporaryDirectory(prefix="android-push-") as tmpdir:
        local_path = Path(tmpdir) / remote.name
        local_path.write_bytes(payload)
        controller.execute_adb(["push", str(local_path), remote_path])


def push_text(controller: Any, remote_path: str, text: str, *, encoding: str = "utf-8") -> None:
    push_bytes(controller, remote_path, text.encode(encoding))


def push_base64_file(controller: Any, remote_path: str, encoded_payload: str) -> None:
    push_bytes(controller, remote_path, base64.b64decode(encoded_payload.encode("ascii")))


def path_status(controller: Any, remote_path: str) -> str:
    quoted = shlex.quote(remote_path)
    command = (
        f"if [ -d {quoted} ]; then echo dir; "
        f"elif [ -f {quoted} ]; then echo file; "
        f"elif [ -e {quoted} ]; then echo exists; "
        "else echo missing; fi"
    )
    return str(controller.execute_adb(["shell", command]) or "missing").strip().lower()


def list_directory_entries(controller: Any, remote_path: str) -> list[str]:
    quoted = shlex.quote(remote_path)
    command = f"if [ -d {quoted} ]; then ls -1A {quoted}; fi"
    output = str(controller.execute_adb(["shell", command]) or "")
    return sorted(line.strip() for line in output.splitlines() if line.strip())


def grant_post_notifications(controller: Any, app_package: str) -> None:
    quoted_package = shlex.quote(app_package)
    controller.execute_adb(
        ["shell", f"pm grant {quoted_package} android.permission.POST_NOTIFICATIONS 2>/dev/null || true"]
    )


def allow_manage_external_storage(controller: Any, app_package: str) -> None:
    controller.execute_adb(["shell", "appops", "set", app_package, "MANAGE_EXTERNAL_STORAGE", "allow"])


def grant_permissions(controller: Any, app_package: str, permissions: Iterable[str]) -> None:
    quoted_package = shlex.quote(app_package)
    for permission in permissions:
        quoted_permission = shlex.quote(permission)
        controller.execute_adb(["shell", f"pm grant {quoted_package} {quoted_permission} 2>/dev/null || true"])


def scan_media_paths(controller: Any, remote_paths: Sequence[str]) -> None:
    for remote_path in remote_paths:
        controller.execute_adb(
            [
                "shell",
                "am",
                "broadcast",
                "-a",
                "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                "-d",
                f"file://{remote_path}",
            ]
        )


def wait_for_breadcrumb(driver: AndroidBootstrapDriver, text: str, *, timeout_seconds: float = 10.0) -> None:
    driver.wait_for_node(
        [
            {"resource_id": "me.zhanghai.android.files:id/text", "text": text},
            {"text": text},
        ],
        timeout_seconds=timeout_seconds,
    )


def tap_material_files_entry(driver: AndroidBootstrapDriver, label: str, *, timeout_seconds: float = 10.0) -> None:
    driver.tap_selector(
        [
            {"resource_id": "me.zhanghai.android.files:id/nameText", "text": label},
            {"text": label},
        ],
        timeout_seconds=timeout_seconds,
    )


def tap_gallery_album(driver: AndroidBootstrapDriver, label: str, *, timeout_seconds: float = 10.0) -> None:
    driver.tap_selector(
        [
            {"resource_id": "org.fossify.gallery:id/dir_name", "text": label},
            {"text": label},
        ],
        timeout_seconds=timeout_seconds,
    )


def wait_for_gallery_media_grid(driver: AndroidBootstrapDriver, *, timeout_seconds: float = 10.0) -> None:
    driver.wait_for_node(
        [
            {"resource_id": "org.fossify.gallery:id/media_grid"},
            {"resource_id": "org.fossify.gallery:id/directories_grid"},
        ],
        timeout_seconds=timeout_seconds,
    )
