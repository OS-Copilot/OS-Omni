"""Prepare deterministic macOS GIMP benchmark workspaces."""

from __future__ import annotations

import shlex
import time
from pathlib import Path
from textwrap import dedent
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class GimpInitializer(BaseInitializer):
    """Reset GIMP, seed task assets, and open the starter image on macOS."""

    DEFAULT_APP_NAME = "GIMP"
    LOCAL_NETWORK_PROMPT_APP_NAMES = {"UserNotificationCenter", "NotificationCenter", "CoreServicesUIAgent"}
    LOCAL_NETWORK_PROMPT_BUNDLE_ID = "com.apple.UserNotificationCenter"
    DENY_BUTTON_TEXTS = {"Don't Allow", "不允许"}
    DENY_BUTTON_IDENTIFIERS = {"action-button-3"}
    WELCOME_CLOSE_TARGET = {"x": 0.265, "y": 0.54}
    DEFAULT_WAIT_MS = 5000
    DEFAULT_TIMEOUT = 120
    DEFAULT_WORKSPACE = "/Users/bench/Downloads/gimp-bench"
    DEFAULT_WINDOW_BOUNDS = {"x": 40, "y": 60, "width": 1800, "height": 1000}

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        task = context.get("task")
        run_dir = context.get("run_dir")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(status=InitStatus.ERROR, message="controller is required for GIMP initialization")
        if not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required for GIMP initialization")

        app_name = str(params.get("app_name") or self.DEFAULT_APP_NAME).strip() or self.DEFAULT_APP_NAME
        timeout = int(params.get("timeout", self.DEFAULT_TIMEOUT) or self.DEFAULT_TIMEOUT)
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        workspace = str(params.get("workspace") or self.DEFAULT_WORKSPACE).strip() or self.DEFAULT_WORKSPACE
        upload_files = [item for item in (params.get("upload_files") or []) if isinstance(item, Mapping)]
        remove_paths = [str(item).strip() for item in (params.get("remove_paths") or []) if str(item).strip()]
        post_launch_remove_paths = [
            str(item).strip() for item in (params.get("post_launch_remove_paths") or []) if str(item).strip()
        ]
        open_file = str(params.get("open_file") or "").strip()
        dismiss_dialogs = bool(params.get("dismiss_dialogs", True))
        arrange_window = bool(params.get("arrange_window", True))
        window_bounds = dict(self.DEFAULT_WINDOW_BOUNDS)
        window_bounds.update(dict(params.get("window_bounds") or {}))

        uploaded: list[dict[str, str]] = []
        arrange_warning: str | None = None
        try:
            prepare_result = controller.run_bash_script(
                self._build_prepare_script(workspace=workspace, remove_paths=remove_paths),
                timeout=timeout,
            )
            self._raise_for_result(prepare_result, "GIMP prepare script failed")

            for upload in upload_files:
                local_path_raw = str(upload.get("local_path") or "").strip()
                remote_path = str(upload.get("path") or upload.get("remote_path") or "").strip()
                if not local_path_raw or not remote_path:
                    raise ValueError("each upload_file entry requires local_path and path")
                local_path = self._resolve_local_path(local_path_raw, task=task, run_dir=run_dir)
                if not local_path.exists() or not local_path.is_file():
                    raise FileNotFoundError(f"GIMP fixture missing: {local_path}")
                if not hasattr(controller, "upload_file"):
                    raise AttributeError("controller.upload_file is required when upload_files are provided")
                controller.upload_file(str(local_path), remote_path)
                uploaded.append({"local_path": str(local_path), "remote_path": remote_path})

            launch_result = controller.run_bash_script(
                self._build_launch_script(app_name=app_name, open_file=open_file),
                timeout=45,
            )
            self._raise_for_result(launch_result, "GIMP launch script failed")

            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

            if post_launch_remove_paths:
                cleanup_result = controller.run_bash_script(
                    self._build_remove_script(post_launch_remove_paths),
                    timeout=timeout,
                )
                self._raise_for_result(cleanup_result, "GIMP post-launch cleanup failed")

            self._dismiss_local_network_prompt(controller, app_name=app_name)
            self._dismiss_startup_screen(controller)
            self._dismiss_welcome_dialog(controller)
            self._stabilize_launch_state(controller, app_name=app_name)

            if dismiss_dialogs or arrange_window:
                try:
                    arrange_result = controller.run_bash_script(
                        self._build_arrange_script(
                            app_name=app_name,
                            dismiss_dialogs=dismiss_dialogs,
                            arrange_window=arrange_window,
                            window_bounds=window_bounds,
                        ),
                        timeout=12,
                    )
                    self._raise_for_result(arrange_result, "GIMP arrange script failed")
                except Exception as exc:
                    arrange_warning = str(exc)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to initialize GIMP workspace: {exc}",
                metadata={
                    "app_name": app_name,
                    "workspace": workspace,
                    "open_file": open_file or None,
                    "uploaded_files": uploaded,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared GIMP benchmark workspace",
            metadata={
                "app_name": app_name,
                "workspace": workspace,
                "open_file": open_file or None,
                "uploaded_files": uploaded,
                "remove_paths": remove_paths,
                "post_launch_remove_paths": post_launch_remove_paths,
                "dismiss_dialogs": dismiss_dialogs,
                "arrange_window": arrange_window,
                "window_bounds": window_bounds,
                "arrange_warning": arrange_warning,
            },
        )

    def _dismiss_local_network_prompt(self, controller: Any, *, app_name: str) -> None:
        if not hasattr(controller, "observe") or not hasattr(controller, "execute_action"):
            return
        for _ in range(4):
            observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
            ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
            target = self._find_prompt_button(ui_nodes)
            if target:
                controller.execute_action({"type": "tap", "target": target}, ui_nodes)
                time.sleep(1.0)
                if hasattr(controller, "launch_app"):
                    try:
                        controller.launch_app(app_name)
                    except Exception:
                        pass
                time.sleep(1.0)
                return
            foreground_bundle = str(getattr(observation, "foreground_bundle_id", "") or "").strip()
            foreground_app = str(getattr(observation, "foreground_app", "") or "").strip()
            if (
                foreground_bundle != self.LOCAL_NETWORK_PROMPT_BUNDLE_ID
                and foreground_app not in self.LOCAL_NETWORK_PROMPT_APP_NAMES
            ):
                return
            time.sleep(0.5)

    def _dismiss_startup_screen(self, controller: Any) -> None:
        if not hasattr(controller, "observe") or not hasattr(controller, "execute_action"):
            return
        for _ in range(3):
            observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
            foreground_app = str(getattr(observation, "foreground_app", "") or "").strip().lower()
            ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
            if foreground_app != "gimp" and not any("gimp startup" in str(node.get("text") or "").lower() for node in ui_nodes if isinstance(node, Mapping)):
                return
            if not any("gimp startup" in str(node.get("text") or "").lower() for node in ui_nodes if isinstance(node, Mapping)):
                return
            controller.execute_action({"type": "keyboard", "action": "escape", "count": 1}, ui_nodes)
            time.sleep(1.0)

    def _dismiss_welcome_dialog(self, controller: Any) -> None:
        if not hasattr(controller, "execute_action"):
            return
        coordinate_fallback = {"type": "tap", "target": dict(self.WELCOME_CLOSE_TARGET)}
        for _ in range(4):
            try:
                ui_nodes = []
                has_welcome_dialog = False
                if hasattr(controller, "observe"):
                    observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
                    ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
                    has_welcome_dialog = any(
                        "welcome to gimp" in str(node.get("text") or "").lower()
                        for node in ui_nodes
                        if isinstance(node, Mapping)
                    )
                if not has_welcome_dialog:
                    return
                close_target = self._find_welcome_close_button(ui_nodes)
                if close_target:
                    controller.execute_action({"type": "tap", "target": close_target}, ui_nodes)
                else:
                    controller.execute_action({"type": "hotkey", "keys": "cmd+w"}, ui_nodes)
                    time.sleep(0.5)
                    controller.execute_action(coordinate_fallback, ui_nodes)
                time.sleep(0.8)
            except Exception:
                return

    def _stabilize_launch_state(self, controller: Any, *, app_name: str) -> None:
        if not hasattr(controller, "observe"):
            return
        for _ in range(6):
            observation = controller.observe(include_ui_tree=True, include_screenshot_data=False)
            ui_nodes = list(getattr(observation, "ui_nodes", []) or [])
            if self._find_prompt_button(ui_nodes):
                self._dismiss_local_network_prompt(controller, app_name=app_name)
                continue
            if self._has_startup_screen(ui_nodes):
                self._dismiss_startup_screen(controller)
                continue
            if self._has_welcome_dialog(ui_nodes):
                self._dismiss_welcome_dialog(controller)
                continue

            foreground_app = str(getattr(observation, "foreground_app", "") or "").strip().lower()
            foreground_bundle = str(getattr(observation, "foreground_bundle_id", "") or "").strip().lower()
            if foreground_app == app_name.lower() or "gimp" in foreground_bundle:
                return

            if hasattr(controller, "launch_app"):
                try:
                    controller.launch_app(app_name)
                except Exception:
                    return
            time.sleep(1.0)

    def _find_prompt_button(self, ui_nodes: list[dict[str, Any]]) -> str | None:
        for node in ui_nodes:
            text = str(node.get("text") or "").strip()
            identifier = str(node.get("identifier") or "").strip()
            if text in self.DENY_BUTTON_TEXTS or identifier in self.DENY_BUTTON_IDENTIFIERS:
                node_id = str(node.get("id") or "").strip()
                if node_id:
                    return node_id
        return None

    @staticmethod
    def _has_startup_screen(ui_nodes: list[dict[str, Any]]) -> bool:
        return any(
            "gimp startup" in str(node.get("text") or "").lower()
            for node in ui_nodes
            if isinstance(node, Mapping)
        )

    def _has_welcome_dialog(self, ui_nodes: list[dict[str, Any]]) -> bool:
        return any(
            "welcome to gimp" in str(node.get("text") or "").lower()
            for node in ui_nodes
            if isinstance(node, Mapping)
        )

    def _find_welcome_close_button(self, ui_nodes: list[dict[str, Any]]) -> str | None:
        if not self._has_welcome_dialog(ui_nodes):
            return None

        for node in ui_nodes:
            if not isinstance(node, Mapping):
                continue
            if str(node.get("subrole") or "").strip() != "AXCloseButton":
                continue
            node_id = str(node.get("id") or "").strip()
            if node_id:
                return node_id
        return None

    @staticmethod
    def _raise_for_result(result: Any, message: str) -> None:
        if not isinstance(result, Mapping):
            return
        status = str(result.get("status") or "").strip().lower()
        returncode = result.get("returncode")
        if status in {"error", "failed", "fail", "verification_failed"} or (
            isinstance(returncode, int) and returncode != 0
        ):
            detail = (
                result.get("error")
                or result.get("message")
                or result.get("output")
                or result
            )
            raise RuntimeError(f"{message}: {detail}")

    @classmethod
    def _build_prepare_script(cls, *, workspace: str, remove_paths: list[str]) -> str:
        quoted_workspace = shlex.quote(workspace)
        remove_lines = [f"rm -f {shlex.quote(path)}" for path in remove_paths]
        remove_block = "\n".join(remove_lines) if remove_lines else ":"
        kill_targets = ["GIMP", "gimp", "gimp-2.10"]
        kill_lines = [f"killall {shlex.quote(name)} >/dev/null 2>&1 || true" for name in kill_targets]
        kill_lines.append("pkill -f '/Applications/GIMP.app' >/dev/null 2>&1 || true")
        kill_lines.append("pkill -f 'GIMP.app' >/dev/null 2>&1 || true")
        kill_block = "\n".join(kill_lines)

        return dedent(
            f"""
            set -euo pipefail
            {kill_block}
            sleep 1
            APP_PATH=""
            for candidate in "/Applications/GIMP.app" "$HOME/Applications/GIMP.app"; do
              if [ -d "$candidate" ]; then
                APP_PATH="$candidate"
                break
              fi
            done
            if [ -z "$APP_PATH" ]; then
              APP_PATH="$(mdfind 'kMDItemFSName == "GIMP.app"' | head -n 1 || true)"
            fi
            [ -n "$APP_PATH" ] && [ -d "$APP_PATH" ] || {{ echo "GIMP.app missing from standard locations" >&2; exit 1; }}
            mkdir -p {quoted_workspace}
            {remove_block}
            printf '%s\n' "$APP_PATH"
            """
        ).strip()

    @staticmethod
    def _build_launch_script(*, app_name: str, open_file: str) -> str:
        app_name_shell = shlex.quote(app_name)
        if open_file:
            command = (
                f"nohup /Applications/GIMP.app/Contents/MacOS/gimp {shlex.quote(open_file)} "
                ">/tmp/helloworld_gimp_launch.log 2>&1 &"
            )
        else:
            command = f"open -a {app_name_shell} >/dev/null 2>&1"
        return dedent(
            f"""
            set -euo pipefail
            {command}
            """
        ).strip()

    @staticmethod
    def _build_remove_script(remove_paths: list[str]) -> str:
        remove_lines = [f"rm -f {shlex.quote(path)}" for path in remove_paths]
        remove_block = "\n".join(remove_lines) if remove_lines else ":"
        return dedent(
            f"""
            set -euo pipefail
            {remove_block}
            """
        ).strip()

    @staticmethod
    def _build_arrange_script(
        *,
        app_name: str,
        dismiss_dialogs: bool,
        arrange_window: bool,
        window_bounds: Mapping[str, Any],
    ) -> str:
        app_name_escaped = app_name.replace("\\", "\\\\").replace('"', '\\"')
        x = int(window_bounds.get("x", 40) or 40)
        y = int(window_bounds.get("y", 60) or 60)
        width = int(window_bounds.get("width", 1800) or 1800)
        height = int(window_bounds.get("height", 1000) or 1000)
        escape_block = ""
        if dismiss_dialogs:
            escape_block = dedent(
                """
                key code 53
                delay 0.3
                key code 53
                delay 0.3
                """
            ).strip()
        window_block = ""
        if arrange_window:
            window_block = dedent(
                f"""
                try
                  tell process \"{app_name_escaped}\"
                    if exists window 1 then
                      set position of window 1 to {{{x}, {y}}}
                      set size of window 1 to {{{width}, {height}}}
                    end if
                  end tell
                end try
                """
            ).strip()
        applescript_lines = [
            f'tell application "{app_name_escaped}" to activate',
            'delay 1',
            'tell application "System Events"',
        ]
        if escape_block:
            applescript_lines.append(escape_block)
        if window_block:
            applescript_lines.append(window_block)
        applescript_lines.append('end tell')
        applescript = "\n".join(applescript_lines)
        return dedent(
            f"""
            set -euo pipefail
            osascript <<'APPLESCRIPT'
            {applescript}
            APPLESCRIPT
            """
        ).strip()

    @staticmethod
    def _resolve_local_path(raw_path: str, *, task: Any, run_dir: Any) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path.resolve()

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
