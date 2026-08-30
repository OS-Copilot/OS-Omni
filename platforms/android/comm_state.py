"""Reusable Android communication app state templates.

The mail/chat benchmark tasks should not repeat first-run account onboarding for
every episode. This module lets a prepared K-9 or Delta Chat app-data directory
be exported once and restored before each task.
"""

from __future__ import annotations

import shlex
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from platforms.android.apk_cache import ensure_package_installed_from_cache


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE_DIR = REPO_ROOT / "assets" / "android_comm_state"


@dataclass(frozen=True)
class CommAppStateSpec:
    name: str
    package: str
    label: str
    template_filename: str


APP_STATE_SPECS: dict[str, CommAppStateSpec] = {
    "deltachat": CommAppStateSpec(
        name="deltachat",
        package="chat.delta",
        label="Delta Chat",
        template_filename="deltachat_app_data.tar.gz",
    ),
    "k9": CommAppStateSpec(
        name="k9",
        package="com.fsck.k9",
        label="K-9 Mail",
        template_filename="k9_app_data.tar.gz",
    ),
}


def template_path_for(app_name: str, template_dir: str | Path | None = None) -> Path:
    spec = _get_spec(app_name)
    root = Path(template_dir) if template_dir else DEFAULT_TEMPLATE_DIR
    return root / spec.template_filename


def restore_app_data_template_if_available(
    controller: Any,
    app_name: str,
    *,
    template_dir: str | Path | None = None,
) -> bool:
    template_path = template_path_for(app_name, template_dir)
    if not template_path.is_file():
        return False
    restore_app_data_template(controller, app_name, template_path=template_path)
    return True


def restore_app_data_template(
    controller: Any,
    app_name: str,
    *,
    template_path: str | Path | None = None,
) -> Path:
    spec = _get_spec(app_name)
    local_template = Path(template_path) if template_path else template_path_for(app_name)
    if not local_template.is_file():
        raise RuntimeError(f"{spec.label} app-data template not found: {local_template}")

    _ensure_package_installed(controller, spec)
    _ensure_adb_root(controller)

    remote_template = f"/data/local/tmp/helloworld_{spec.name}_app_data.tar.gz"
    package_q = shlex.quote(spec.package)
    data_dirs = _app_data_dirs(spec.package)
    remote_template_q = shlex.quote(remote_template)

    controller.execute_adb(["shell", f"rm -f {remote_template_q}"])
    controller.execute_adb(["push", str(local_template), remote_template])
    restore_commands = [
        f"owner_{idx}=$(stat -c '%u:%g' {shlex.quote(data_dir)} 2>/dev/null || true)"
        for idx, data_dir in enumerate(data_dirs)
    ]
    restore_commands.extend(
        f"ctx_{idx}=$(ls -Zd {shlex.quote(data_dir)} 2>/dev/null | awk '{{print $1}}')"
        for idx, data_dir in enumerate(data_dirs)
    )
    restore_commands.extend(f"rm -rf {shlex.quote(data_dir)}" for data_dir in data_dirs)
    restore_commands.append(f"tar -xzf {remote_template_q} -C /data")
    restore_commands.extend(
        (
            f"if [ -d {shlex.quote(data_dir)} ] && [ -n \"$owner_{idx}\" ]; "
            f"then chown -R \"$owner_{idx}\" {shlex.quote(data_dir)}; fi"
        )
        for idx, data_dir in enumerate(data_dirs)
    )
    restore_commands.extend(
        (
            f"if [ -d {shlex.quote(data_dir)} ] && [ -n \"$ctx_{idx}\" ]; "
            f"then chcon -R \"$ctx_{idx}\" {shlex.quote(data_dir)}; fi"
        )
        for idx, data_dir in enumerate(data_dirs)
    )
    restore_commands.extend(
        f"restorecon -RF {shlex.quote(data_dir)} 2>/dev/null || true"
        for data_dir in data_dirs
    )
    restore_commands.append(f"rm -f {remote_template_q}")
    command = (
        f"am force-stop {package_q}; "
        f"pm clear {package_q}; "
        + "; ".join(restore_commands)
    )
    controller.execute_adb(["shell", command])
    return local_template


def export_app_data_template(
    controller: Any,
    app_name: str,
    *,
    template_path: str | Path | None = None,
) -> Path:
    spec = _get_spec(app_name)
    local_template = Path(template_path) if template_path else template_path_for(app_name)
    local_template.parent.mkdir(parents=True, exist_ok=True)

    _ensure_package_installed(controller, spec)
    _ensure_adb_root(controller)

    remote_template = f"/data/local/tmp/helloworld_{spec.name}_app_data.tar.gz"
    remote_template_q = shlex.quote(remote_template)
    package_q = shlex.quote(spec.package)
    controller.execute_adb(["shell", f"am force-stop {package_q}"])
    time.sleep(0.5)
    controller.execute_adb(["shell", f"rm -f {remote_template_q}"])
    rel_paths = " ".join(
        shlex.quote(_strip_data_prefix(path))
        for path in _app_data_dirs(spec.package)
    )
    controller.execute_adb(
        ["shell", f"tar -czf {remote_template_q} -C /data {rel_paths}"]
    )

    with tempfile.TemporaryDirectory(prefix=f"android-{spec.name}-state-") as tmpdir:
        tmp_root = Path(tmpdir)
        controller.execute_adb(["pull", remote_template, str(tmp_root)])
        pulled = tmp_root / Path(remote_template).name
        if not pulled.is_file():
            raise RuntimeError(f"Failed to pull {spec.label} app-data template from {remote_template}")
        shutil.move(str(pulled), str(local_template))

    controller.execute_adb(["shell", f"rm -f {remote_template_q}"])
    return local_template


def ensure_adb_reverse_for_greenmail(controller: Any) -> None:
    controller.execute_adb(["reverse", "tcp:3025", "tcp:3025"])
    controller.execute_adb(["reverse", "tcp:3143", "tcp:3143"])


def _ensure_adb_root(controller: Any) -> None:
    root_output = str(controller.execute_adb(["root"]) or "").strip().lower()
    if "cannot run as root" in root_output or "production builds" in root_output:
        raise RuntimeError(root_output)
    if "restarting adbd as root" in root_output:
        controller.execute_adb(["wait-for-device"])
        time.sleep(1.0)


def _ensure_package_installed(controller: Any, spec: CommAppStateSpec) -> None:
    ensure_package_installed_from_cache(controller, spec.package, label=spec.label)


def _get_spec(app_name: str) -> CommAppStateSpec:
    key = str(app_name or "").strip().lower()
    if key not in APP_STATE_SPECS:
        raise ValueError(f"Unsupported communication app state template: {app_name!r}")
    return APP_STATE_SPECS[key]


def _app_data_dirs(package: str) -> list[str]:
    return [
        f"/data/user/0/{package}",
        f"/data/user_de/0/{package}",
    ]


def _strip_data_prefix(path: str) -> str:
    prefix = "/data/"
    return path[len(prefix) :] if path.startswith(prefix) else path
