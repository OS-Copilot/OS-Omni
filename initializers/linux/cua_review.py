"""Shared helpers for Linux tasks recovered from CUA-Tasks-Review artifacts."""

from __future__ import annotations

import json
import shlex
import time
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


def run_guest(controller: Any, script: str, *, timeout: int = 30) -> Mapping[str, Any]:
    if controller is None or not hasattr(controller, "run_bash_script"):
        raise RuntimeError("controller.run_bash_script is required")
    result = controller.run_bash_script(script, timeout=timeout)
    returncode = int(result.get("returncode", -1))
    if returncode != 0:
        detail = str(result.get("output") or result.get("error") or "").strip()
        raise RuntimeError(detail or f"guest command failed with exit code {returncode}")
    return result


def launch_guest(controller: Any, target: str, *, wait_ms: int = 0) -> None:
    target = str(target or "").strip()
    if not target:
        raise ValueError("launch target is required")
    preflight = ""
    if target.startswith("file://"):
        path = target.removeprefix("file://")
        preflight = f"test -e {shlex.quote(path)}"
        command = f"xdg-open {shlex.quote(target)}"
    elif target.startswith(("http://", "https://")):
        command = f"xdg-open {shlex.quote(target)}"
    elif target.startswith("/"):
        quoted = shlex.quote(target)
        preflight = f"test -e {quoted}"
        if PurePosixPath(target).suffix:
            command = f"xdg-open {quoted}"
        else:
            # Desktop webpage entries are often extensionless symlinks, while
            # OpenApps launchers are extensionless executables.
            command = f"if [ -x {quoted} ]; then {quoted}; else xdg-open {quoted}; fi"
    else:
        command = target
        if all(character.isalnum() or character in "._+-" for character in target):
            preflight = f"command -v {shlex.quote(target)} >/dev/null 2>&1"
    script = "\n".join(
        [
            *([preflight] if preflight else []),
            "export DISPLAY=${DISPLAY:-:0}",
            "export XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}",
            'export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}',
            'export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}',
            f"setsid -f bash -lc {shlex.quote(command)} >/dev/null 2>&1",
        ]
    )
    run_guest(controller, script, timeout=15)
    if wait_ms > 0:
        time.sleep(wait_ms / 1000.0)


def verify_paths(controller: Any, paths: Iterable[str], *, timeout: int = 20) -> None:
    normalized = [str(path).strip() for path in paths if str(path).strip()]
    if not normalized:
        return
    run_guest(
        controller,
        "\n".join(f"test -e {shlex.quote(path)}" for path in normalized),
        timeout=timeout,
    )


BUNDLED_ATTACHMENTS_DIR = Path(__file__).resolve().parent / "assets" / "openphotoedit"


def seed_bundled_attachments(controller: Any, paths: Iterable[str], *, timeout: int = 20) -> list[str]:
    """Upload bundled stand-ins for guest attachment files the VM image lacks."""

    seeded: list[str] = []
    for path in [str(value).strip() for value in paths if str(value).strip()]:
        local = BUNDLED_ATTACHMENTS_DIR / PurePosixPath(path).name
        if not local.is_file():
            continue
        try:
            run_guest(controller, f"test -e {shlex.quote(path)}", timeout=timeout)
            continue
        except RuntimeError:
            pass
        run_guest(controller, f"mkdir -p {shlex.quote(str(PurePosixPath(path).parent))}", timeout=timeout)
        controller.upload_file(str(local), path)
        seeded.append(path)
    return seeded


def cleanup_paths(controller: Any, paths: Iterable[str], *, timeout: int = 20) -> list[str]:
    normalized = [str(path).strip() for path in paths if str(path).strip()]
    if normalized:
        run_guest(
            controller,
            "rm -f -- " + " ".join(shlex.quote(path) for path in normalized),
            timeout=timeout,
        )
    return normalized


def write_text_files(controller: Any, files: Iterable[Mapping[str, Any]]) -> list[str]:
    written: list[str] = []
    for item in files:
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        content = str(item.get("content") or "")
        if hasattr(controller, "write_file"):
            controller.write_file(path, content)
        else:
            payload = json.dumps({"path": path, "content": content}, ensure_ascii=False)
            run_guest(
                controller,
                "python3 - <<'PY'\n"
                "import json, pathlib\n"
                f"payload = json.loads({payload!r})\n"
                "path = pathlib.Path(payload['path'])\n"
                "path.parent.mkdir(parents=True, exist_ok=True)\n"
                "path.write_text(payload['content'], encoding='utf-8')\n"
                "PY",
            )
        written.append(path)
    return written


# The reviewed snapshots put these commands on PATH; the v3 image instead has
# the OpenApps launchers or the desktop webpage entries the evaluators read.
GUEST_COMMAND_FALLBACKS = {
    "openfood": "/home/user/OpenApps/bin/launch-openfood",
    "opennote": "/home/user/OpenApps/bin/launch-openrednote",
    "openmail": "/home/user/Desktop/webpage/OpenMail",
}


def resolve_guest_command(controller: Any, command: str) -> str:
    """Return ``command``, or its known fallback when it is not on the guest PATH."""

    fallback = GUEST_COMMAND_FALLBACKS.get(command)
    if not fallback:
        return command
    try:
        run_guest(controller, f"command -v {shlex.quote(command)} >/dev/null 2>&1", timeout=10)
    except RuntimeError:
        return fallback
    return command


class SnapshotOpenAppInitializer(BaseInitializer):
    """Launch an app without changing snapshot-provided business state."""

    default_app_name = ""
    default_app_command = ""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        app_name = str(params.get("app_name") or self.default_app_name).strip()
        # Some reviewed tasks name the launcher path in app_name and set no app_command.
        app_command = str(
            params.get("app_command")
            or (app_name if app_name.startswith("/") else "")
            or self.default_app_command
            or app_name
        ).strip()
        snapshot_name = str(params.get("snapshot_name") or params.get("vm_snapshot_name") or "").strip()
        wait_ms = int(params.get("wait_ms", 3000) or 0)
        try:
            app_command = resolve_guest_command(controller, app_command)
            launch_guest(controller, app_command, wait_ms=wait_ms)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to open {app_name or app_command}: {exc}",
                metadata={"app_name": app_name, "app_command": app_command, "snapshot_name": snapshot_name},
            )
        return InitResult(
            status=InitStatus.PASS,
            message=f"Opened {app_name or app_command} using existing snapshot state",
            metadata={
                "app_name": app_name,
                "app_command": app_command,
                "snapshot_name": snapshot_name,
                "business_state_mutated": False,
            },
        )
