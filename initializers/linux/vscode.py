"""Initializer utilities for VS Code desktop tasks on Linux."""

from __future__ import annotations

import json
import shlex
import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class VSCodeInitializer(BaseInitializer):
    """Reset a deterministic VS Code workspace and launch it in a fresh window."""

    DEFAULT_APP_COMMAND = "code"
    DEFAULT_WORKSPACE_ROOT = "/tmp/helloworld_vscode_workspace"
    DEFAULT_USER_DATA_DIR = "/tmp/helloworld_vscode_user_data"
    DEFAULT_FINAL_WAIT_MS = 4500

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required")

        app_command = str(params.get("app_command") or self.DEFAULT_APP_COMMAND).strip()
        workspace_name = str(params.get("workspace_name") or "bench").strip() or "bench"
        workspace_root = str(params.get("workspace_root") or self.DEFAULT_WORKSPACE_ROOT).strip()
        user_data_dir = str(params.get("user_data_dir") or self.DEFAULT_USER_DATA_DIR).strip()
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or self.DEFAULT_FINAL_WAIT_MS)
        files = self._normalize_files(params.get("files"))
        folders = self._normalize_folders(params.get("folders"))
        workspace_path = f"{workspace_root.rstrip('/')}/{workspace_name}"

        try:
            self._run(controller, f"command -v {shlex.quote(app_command)} >/dev/null 2>&1", timeout=10)
            self._stop_app(controller)
            self._prepare_workspace(
                controller,
                workspace_path=workspace_path,
                user_data_dir=user_data_dir,
                files=files,
                folders=folders,
            )
            self._launch_app(
                controller,
                app_command=app_command,
                workspace_path=workspace_path,
                user_data_dir=user_data_dir,
            )
            if final_wait_ms > 0:
                time.sleep(final_wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare VS Code workspace: {exc}",
                metadata={"workspace_path": workspace_path, "file_count": len(files)},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared VS Code workspace",
            metadata={
                "workspace_path": workspace_path,
                "user_data_dir": user_data_dir,
                "file_count": len(files),
            },
        )

    @staticmethod
    def _normalize_files(raw_files: Any) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        if not isinstance(raw_files, list):
            return normalized
        for item in raw_files:
            if not isinstance(item, Mapping):
                continue
            path = str(item.get("path") or "").strip()
            content = item.get("content")
            if not path or not isinstance(content, str):
                continue
            normalized.append({"path": path, "content": content})
        return normalized

    @staticmethod
    def _normalize_folders(raw_folders: Any) -> list[str]:
        if not isinstance(raw_folders, list):
            return []
        return [str(item).strip() for item in raw_folders if str(item).strip()]

    @staticmethod
    def _run(controller: Any, script: str, *, timeout: int) -> Mapping[str, Any]:
        result = controller.run_bash_script(script, timeout=timeout)
        returncode = int(result.get("returncode", -1))
        if returncode != 0:
            output = str(result.get("output", "")).strip()
            raise RuntimeError(output or f"guest command failed with exit code {returncode}")
        return result

    def _stop_app(self, controller: Any) -> None:
        self._run(
            controller,
            "\n".join(
                [
                    "pkill -TERM -f '/usr/share/code/code|/usr/bin/code' || true",
                    "sleep 1",
                    "pkill -KILL -f '/usr/share/code/code|/usr/bin/code' || true",
                    "sleep 1",
                ]
            ),
            timeout=20,
        )

    def _prepare_workspace(
        self,
        controller: Any,
        *,
        workspace_path: str,
        user_data_dir: str,
        files: list[dict[str, str]],
        folders: list[str],
    ) -> None:
        payload = json.dumps(
            {
                "workspace_path": workspace_path,
                "user_data_dir": user_data_dir,
                "files": files,
                "folders": folders,
            },
            ensure_ascii=False,
        )
        script = f"""python3 - <<'PY'
import json
import pathlib
import shutil

payload = json.loads({json.dumps(payload, ensure_ascii=False)})
workspace = pathlib.Path(payload["workspace_path"])
user_data_dir = pathlib.Path(payload["user_data_dir"])

if workspace.exists():
    shutil.rmtree(workspace)
workspace.mkdir(parents=True, exist_ok=True)

if user_data_dir.exists():
    shutil.rmtree(user_data_dir)
(user_data_dir / "User").mkdir(parents=True, exist_ok=True)
(user_data_dir / "User" / "settings.json").write_text(
    json.dumps(
        {{
            "workbench.startupEditor": "none",
            "security.workspace.trust.enabled": False,
            "telemetry.telemetryLevel": "off",
            "update.mode": "none",
        }},
        indent=2,
        ensure_ascii=False,
    )
    + "\\n",
    encoding="utf-8",
)

for folder in payload["folders"]:
    (workspace / folder).mkdir(parents=True, exist_ok=True)

for file_spec in payload["files"]:
    file_path = workspace / file_spec["path"]
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(file_spec["content"], encoding="utf-8")

print(json.dumps({{"status": "ok", "workspace_path": str(workspace)}}, ensure_ascii=False))
PY"""
        self._run(controller, script, timeout=90)

    def _launch_app(
        self,
        controller: Any,
        *,
        app_command: str,
        workspace_path: str,
        user_data_dir: str,
    ) -> None:
        command = " ".join(
            [
                shlex.quote(app_command),
                "--new-window",
                "--disable-workspace-trust",
                "--skip-welcome",
                "--user-data-dir",
                shlex.quote(user_data_dir),
                shlex.quote(workspace_path),
            ]
        )
        launch_script = "\n".join(
            [
                "export DISPLAY=${DISPLAY:-:0}",
                "export XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}",
                'export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}',
                'export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}',
                f"setsid -f bash -lc {shlex.quote(command)} >/dev/null 2>&1",
            ]
        )
        self._run(controller, launch_script, timeout=15)
