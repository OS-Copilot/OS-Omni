"""Prepare VSCodium in a predictable macOS state before an episode starts."""

from __future__ import annotations

import json
import shlex
import time
from pathlib import Path, PurePosixPath
from textwrap import dedent
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class VSCodiumInitializer(BaseInitializer):
    """Reset lightweight VSCodium state, then open either settings or a workspace."""

    DEFAULT_APP_NAME = "VSCodium"
    DEFAULT_APP_PATH = "/Applications/VSCodium.app"
    DEFAULT_BUNDLE_ID = "com.vscodium"
    DEFAULT_WAIT_MS = 5000
    DEFAULT_SETTINGS_PATH = "~/Library/Application Support/VSCodium/User/settings.json"
    DEFAULT_SAVED_STATE_PATH = "~/Library/Saved Application State/com.vscodium.savedState"
    DEFAULT_STATE_ROOT = "~/Library/Application Support/VSCodium"
    DEFAULT_OPEN_SETTINGS_FILE = True
    DEFAULT_PRESELECT_ALL = True
    DEFAULT_EDITOR_FOCUS_TARGET = {"x": 0.34, "y": 0.31}
    DEFAULT_BASELINE_SETTINGS = {
        "workbench.startupEditor": "none",
        "window.restoreWindows": "none",
        "update.mode": "none",
        "telemetry.telemetryLevel": "off",
        "security.workspace.trust.enabled": False,
        "workbench.editor.enablePreview": False,
    }

    @staticmethod
    def _resolve_local_path(raw_path: str, *, task: Any, run_dir: Any) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path

        task_source = getattr(task, "source_file", None)
        if task_source:
            candidate = (Path(task_source).expanduser().resolve().parent / path).resolve()
            if candidate.exists():
                return candidate

        if run_dir is not None:
            candidate = (Path(run_dir) / path).resolve()
            if candidate.exists():
                return candidate

        return (Path.cwd() / path).resolve()

    @staticmethod
    def _result_error_message(result: Mapping[str, Any]) -> str:
        for key in ("error", "message", "stderr", "stdout", "output"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "unknown VSCodium initialization failure"

    def _upload_fixture_tree(self, controller: Any, *, local_root: Path, remote_root: str) -> None:
        for local_file in sorted(p for p in local_root.rglob("*") if p.is_file()):
            relative = local_file.relative_to(local_root).as_posix()
            remote_path = str(PurePosixPath(remote_root) / PurePosixPath(relative))
            remote_parent = str(PurePosixPath(remote_path).parent)
            controller.run_bash_script(
                f"mkdir -p {shlex.quote(remote_parent)}",
                timeout=20,
            )
            controller.upload_file(str(local_file), remote_path)

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        task = context.get("task")
        run_dir = context.get("run_dir")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.run_bash_script is required for VSCodium initialization",
            )

        app_name = str(params.get("app_name") or self.DEFAULT_APP_NAME).strip() or self.DEFAULT_APP_NAME
        app_path = str(params.get("app_path") or self.DEFAULT_APP_PATH).strip() or self.DEFAULT_APP_PATH
        bundle_id = str(params.get("bundle_id") or self.DEFAULT_BUNDLE_ID).strip() or self.DEFAULT_BUNDLE_ID
        settings_path = str(params.get("settings_path") or self.DEFAULT_SETTINGS_PATH).strip() or self.DEFAULT_SETTINGS_PATH
        saved_state_path = str(params.get("saved_state_path") or self.DEFAULT_SAVED_STATE_PATH).strip() or self.DEFAULT_SAVED_STATE_PATH
        state_root = str(params.get("state_root") or self.DEFAULT_STATE_ROOT).strip() or self.DEFAULT_STATE_ROOT
        workspace_root = str(params.get("workspace_root") or "").strip()
        fixture_root_raw = str(params.get("fixture_root") or "").strip()
        starter_file = str(params.get("starter_file") or "").strip()
        starter_files_raw = params.get("starter_files")
        starter_files = [
            str(item).strip()
            for item in list(starter_files_raw or [])
            if str(item).strip()
        ]
        file_aliases_raw = params.get("file_aliases")
        file_aliases: list[dict[str, str]] = []
        for item in list(file_aliases_raw or []):
            if not isinstance(item, Mapping):
                continue
            alias = str(item.get("alias") or "").strip()
            target = str(item.get("target") or "").strip()
            if alias and target:
                file_aliases.append({"alias": alias, "target": target})
        if starter_file and starter_file not in starter_files:
            starter_files.insert(0, starter_file)
        active_file = str(params.get("active_file") or starter_file or (starter_files[0] if starter_files else "")).strip()
        open_workspace = bool(params.get("open_workspace", bool(workspace_root)))
        open_settings_file_raw = params.get("open_settings_file")
        open_settings_file = (
            bool(open_settings_file_raw)
            if open_settings_file_raw is not None
            else not bool(workspace_root)
        )
        preselect_all = bool(params.get("preselect_all", self.DEFAULT_PRESELECT_ALL)) and open_settings_file
        editor_focus_target = dict(self.DEFAULT_EDITOR_FOCUS_TARGET)
        editor_focus_target.update(dict(params.get("editor_focus_target") or {}))
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        timeout = int(params.get("timeout", 60) or 60)

        baseline_settings = dict(self.DEFAULT_BASELINE_SETTINGS)
        baseline_settings.update(dict(params.get("baseline_settings") or {}))

        app_name_shell = shlex.quote(app_name)
        app_path_shell = shlex.quote(app_path)
        open_mode = (
            "workspace"
            if workspace_root
            else "settings-file"
            if open_settings_file
            else "app-home"
        )

        local_fixture_root: Path | None = None
        if fixture_root_raw:
            if not hasattr(controller, "upload_file"):
                return InitResult(
                    status=InitStatus.ERROR,
                    message="controller.upload_file is required when fixture_root is provided",
                )
            local_fixture_root = self._resolve_local_path(fixture_root_raw, task=task, run_dir=run_dir)
            if not local_fixture_root.exists() or not local_fixture_root.is_dir():
                return InitResult(
                    status=InitStatus.ERROR,
                    message=f"fixture_root does not exist or is not a directory: {local_fixture_root}",
                )
            if not workspace_root:
                return InitResult(
                    status=InitStatus.ERROR,
                    message="workspace_root is required when fixture_root is provided",
                )

        reset_script = dedent(
            f"""
            set -euo pipefail
            killall -9 {app_name_shell} >/dev/null 2>&1 || true
            pkill -9 -f {app_path_shell} >/dev/null 2>&1 || true
            sleep 1
            python3 - <<'INNER_PY'
            from pathlib import Path
            import json
            import shutil

            settings_path = Path({settings_path!r}).expanduser()
            state_root = Path({state_root!r}).expanduser()
            saved_state_path = Path({saved_state_path!r}).expanduser()
            workspace_root = Path({workspace_root!r}).expanduser() if {bool(workspace_root)!r} else None

            shutil.rmtree(saved_state_path, ignore_errors=True)
            shutil.rmtree(state_root / "Backups", ignore_errors=True)
            shutil.rmtree(state_root / "User" / "workspaceStorage", ignore_errors=True)
            shutil.rmtree(state_root / "logs", ignore_errors=True)

            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(
                json.dumps({baseline_settings!r}, ensure_ascii=False, indent=2) + "\\n",
                encoding="utf-8",
            )
            keybindings_path = settings_path.parent / "keybindings.json"
            if keybindings_path.exists():
                keybindings_path.unlink()

            if workspace_root is not None:
                shutil.rmtree(workspace_root, ignore_errors=True)
                workspace_root.mkdir(parents=True, exist_ok=True)
            INNER_PY
            """
        ).strip()

        try:
            reset_result = controller.run_bash_script(reset_script, timeout=timeout)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to initialize VSCodium: {exc}",
                metadata={
                    "app_name": app_name,
                    "app_path": app_path,
                    "settings_path": settings_path,
                    "workspace_root": workspace_root,
                    "open_mode": open_mode,
                },
            )

        return_code = reset_result.get("returncode") if isinstance(reset_result, Mapping) else None
        if isinstance(return_code, int) and return_code != 0:
            return InitResult(
                status=InitStatus.ERROR,
                message="VSCodium initialization bash script failed",
                metadata={
                    "app_name": app_name,
                    "app_path": app_path,
                    "settings_path": settings_path,
                    "workspace_root": workspace_root,
                    "open_mode": open_mode,
                    "runtime_result": dict(reset_result),
                },
            )

        if local_fixture_root is not None:
            try:
                self._upload_fixture_tree(
                    controller,
                    local_root=local_fixture_root,
                    remote_root=workspace_root,
                )
            except Exception as exc:
                return InitResult(
                    status=InitStatus.ERROR,
                    message=f"Failed to upload VSCodium workspace fixture: {exc}",
                    metadata={
                        "workspace_root": workspace_root,
                        "fixture_root": str(local_fixture_root),
                    },
                )

        if workspace_root and file_aliases:
            alias_lines = ["set -euo pipefail", f"cd {shlex.quote(workspace_root)}"]
            for alias_mapping in file_aliases:
                alias_path = alias_mapping["alias"]
                target_path = alias_mapping["target"]
                alias_parent = str(PurePosixPath(alias_path).parent)
                if alias_parent not in ("", "."):
                    alias_lines.append(f"mkdir -p {shlex.quote(alias_parent)}")
                alias_lines.append(f"rm -f {shlex.quote(alias_path)}")
                alias_lines.append(f"ln -s {shlex.quote(target_path)} {shlex.quote(alias_path)}")

            try:
                alias_result = controller.run_bash_script("\n".join(alias_lines), timeout=timeout)
            except Exception as exc:
                return InitResult(
                    status=InitStatus.ERROR,
                    message=f"Failed to create VSCodium file aliases: {exc}",
                    metadata={
                        "workspace_root": workspace_root,
                        "file_aliases": file_aliases,
                    },
                )

            alias_return_code = alias_result.get("returncode") if isinstance(alias_result, Mapping) else None
            if isinstance(alias_return_code, int) and alias_return_code != 0:
                return InitResult(
                    status=InitStatus.ERROR,
                    message="VSCodium alias creation bash script failed",
                    metadata={
                        "workspace_root": workspace_root,
                        "file_aliases": file_aliases,
                        "runtime_result": dict(alias_result),
                    },
                )

        resolved_app_path = self._resolve_remote_app_path(
            controller,
            app_name=app_name,
            app_path=app_path,
            bundle_id=bundle_id,
        )
        if not resolved_app_path:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"VSCodium app not found in guest (checked {app_path}, ~/Applications, /Applications, Spotlight)",
                metadata={
                    "app_name": app_name,
                    "app_path": app_path,
                    "bundle_id": bundle_id,
                    "workspace_root": workspace_root,
                    "open_mode": open_mode,
                },
            )

        launch_lines = [
            "set -euo pipefail",
            f"APP_PATH={json.dumps(resolved_app_path)}",
            "settings_path_expanded=\"$(python3 - <<'INNER_PY'",
            "from pathlib import Path",
            f"print(Path({settings_path!r}).expanduser())",
            "INNER_PY",
            ")\"",
        ]
        if workspace_root and open_workspace:
            workspace_root_shell = shlex.quote(workspace_root)
            launch_lines.append(f'open -a "$APP_PATH" {workspace_root_shell} >/dev/null 2>&1')
            launch_lines.append("sleep 1")
        for relative_file in starter_files:
            if not workspace_root:
                break
            starter_path = str(PurePosixPath(workspace_root) / PurePosixPath(relative_file))
            starter_path_shell = shlex.quote(starter_path)
            launch_lines.append(f'open -a "$APP_PATH" {starter_path_shell} >/dev/null 2>&1')
            launch_lines.append("sleep 1")
        if active_file and workspace_root and active_file not in starter_files:
            active_path = str(PurePosixPath(workspace_root) / PurePosixPath(active_file))
            active_path_shell = shlex.quote(active_path)
            launch_lines.append(f'open -a "$APP_PATH" {active_path_shell} >/dev/null 2>&1')
            launch_lines.append("sleep 1")
        elif active_file and workspace_root and starter_files:
            active_path = str(PurePosixPath(workspace_root) / PurePosixPath(active_file))
            active_path_shell = shlex.quote(active_path)
            launch_lines.append(f'open -a "$APP_PATH" {active_path_shell} >/dev/null 2>&1')
            launch_lines.append("sleep 1")
        if open_settings_file:
            launch_lines.append('open -a "$APP_PATH" "$settings_path_expanded" >/dev/null 2>&1')
        elif not workspace_root:
            launch_lines.append('open -a "$APP_PATH" >/dev/null 2>&1')
        launch_lines.append(f"osascript -e 'tell application id \"{bundle_id}\" to activate' >/dev/null 2>&1 || true")

        launch_script = "\n".join(launch_lines)
        try:
            launch_result = controller.run_bash_script(launch_script, timeout=timeout)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to launch VSCodium: {exc}",
                metadata={
                    "app_name": app_name,
                    "app_path": resolved_app_path,
                    "workspace_root": workspace_root,
                    "starter_file": starter_file,
                    "open_settings_file": open_settings_file,
                },
            )

        launch_return_code = launch_result.get("returncode") if isinstance(launch_result, Mapping) else None
        if isinstance(launch_return_code, int) and launch_return_code != 0:
            return InitResult(
                status=InitStatus.ERROR,
                message=self._result_error_message(dict(launch_result)),
                metadata={
                    "app_name": app_name,
                    "app_path": resolved_app_path,
                    "workspace_root": workspace_root,
                    "starter_file": starter_file,
                    "open_settings_file": open_settings_file,
                    "runtime_result": dict(launch_result),
                },
            )

        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)

        if preselect_all and hasattr(controller, "execute_action"):
            try:
                controller.execute_action({"type": "tap", "target": editor_focus_target}, [])
                time.sleep(0.4)
                controller.execute_action({"type": "hotkey", "keys": "cmd+a"}, [])
                time.sleep(0.4)
            except Exception as exc:
                return InitResult(
                    status=InitStatus.ERROR,
                    message=f"VSCodium editor preselection failed: {exc}",
                    metadata={
                        "app_name": app_name,
                        "app_path": app_path,
                        "settings_path": settings_path,
                        "open_settings_file": open_settings_file,
                        "preselect_all": preselect_all,
                        "editor_focus_target": editor_focus_target,
                    },
                )

        if preselect_all:
            message = "Prepared VSCodium, opened the user settings file, and selected its contents"
        elif workspace_root:
            message = "Prepared VSCodium and opened the requested workspace"
        elif open_settings_file:
            message = "Prepared VSCodium and opened the user settings file"
        else:
            message = "Prepared and opened VSCodium"

        return InitResult(
            status=InitStatus.PASS,
            message=message,
            metadata={
                "app_name": app_name,
                "app_path": resolved_app_path,
                "settings_path": settings_path,
                "workspace_root": workspace_root,
                "fixture_root": str(local_fixture_root) if local_fixture_root is not None else "",
                "file_aliases": file_aliases,
                "starter_file": starter_file,
                "starter_files": starter_files,
                "active_file": active_file,
                "baseline_settings": json.loads(json.dumps(baseline_settings, ensure_ascii=False)),
                "open_settings_file": open_settings_file,
                "open_workspace": open_workspace,
                "preselect_all": preselect_all,
                "editor_focus_target": editor_focus_target,
                "open_mode": open_mode,
                "wait_ms": wait_ms,
            },
        )

    @staticmethod
    def _resolve_remote_app_path(controller: Any, *, app_name: str, app_path: str, bundle_id: str) -> str | None:
        script = dedent(
            f"""
            python3 - <<'PY'
            import subprocess
            from pathlib import Path

            app_name = {json.dumps(app_name)}
            bundle_id = {json.dumps(bundle_id)}
            candidates = [
                Path({json.dumps(app_path)}).expanduser(),
                Path.home() / "Applications" / f"{{app_name}}.app",
                Path("/Applications") / f"{{app_name}}.app",
                Path.home() / "Applications" / "Codium.app",
                Path("/Applications") / "Codium.app",
            ]
            for candidate in candidates:
                if candidate.is_dir():
                    print(candidate)
                    raise SystemExit(0)

            queries = [
                f'kMDItemCFBundleIdentifier == "{{bundle_id}}"',
                f'kMDItemFSName == "{{app_name}}.app"',
                'kMDItemFSName == "Codium.app"',
            ]
            for query in queries:
                proc = subprocess.run(["mdfind", query], check=False, capture_output=True, text=True)
                for line in proc.stdout.splitlines():
                    path = Path(line.strip())
                    if path.suffix == ".app" and path.is_dir():
                        print(path)
                        raise SystemExit(0)

            raise SystemExit(1)
            PY
            """
        ).strip()
        result = controller.run_bash_script(script, timeout=20)
        if int(result.get("returncode", 1)) != 0:
            return None
        output = str(result.get("stdout") or result.get("output") or "").strip()
        return output or None
