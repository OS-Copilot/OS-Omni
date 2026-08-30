"""Linux desktop setup initializer."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.asset_cache import local_cache_for_url


class DesktopSetupInitializer(BaseInitializer):
    """Execute OSWorld-style setup steps through the HelloWorld Linux controller."""

    DEFAULT_WAIT_MS = 800

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        run_dir = context.get("run_dir")

        if controller is None:
            return InitResult(status=InitStatus.ERROR, message="controller is required for Linux initialization")

        try:
            steps = self._normalize_steps(params, run_dir=run_dir)
        except Exception as exc:
            return InitResult(status=InitStatus.ERROR, message=f"Invalid setup params: {exc}")

        executed: list[dict[str, Any]] = []
        for index, step in enumerate(steps, start=1):
            try:
                result = self._execute_step(controller, step, run_dir=run_dir)
                executed.append(
                    {
                        "index": index,
                        "type": step["type"],
                        "optional": bool(step.get("optional", False)),
                        "result": result,
                    }
                )
            except Exception as exc:
                if step.get("optional", False):
                    executed.append(
                        {
                            "index": index,
                            "type": step["type"],
                            "optional": True,
                            "error": str(exc),
                        }
                    )
                    continue
                return InitResult(
                    status=InitStatus.ERROR,
                    message=f"Setup step {index} failed ({step['type']}): {exc}",
                    metadata={"steps": executed},
                )

        return InitResult(
            status=InitStatus.PASS,
            message=f"Executed {len(executed)} Linux setup steps",
            metadata={"steps": executed},
        )

    def _normalize_steps(self, params: Mapping[str, Any], *, run_dir: Any) -> list[dict[str, Any]]:
        raw_steps = params.get("steps")
        if isinstance(raw_steps, list):
            normalized: list[dict[str, Any]] = []
            for item in raw_steps:
                if not isinstance(item, Mapping):
                    raise TypeError("each setup step must be an object")
                step = dict(item)
                step_type = str(step.get("type") or "").strip()
                if not step_type:
                    raise ValueError("each setup step requires a non-empty type")
                step["type"] = step_type
                normalized.append(step)
            if normalized:
                return normalized

        synthesized: list[dict[str, Any]] = []
        app_name = str(params.get("app_name") or params.get("launch_app") or "").strip()
        if app_name:
            synthesized.append(
                {
                    "type": "launch",
                    "app_name": app_name,
                    "optional": bool(params.get("launch_optional", False)),
                }
            )

        for upload in self._coerce_sequence(params.get("upload_files")):
            synthesized.append({"type": "upload_file", **dict(upload)})

        for download in self._coerce_sequence(params.get("downloads")):
            synthesized.append({"type": "download", **dict(download)})

        for write_file in self._coerce_sequence(params.get("write_files")):
            synthesized.append({"type": "write_file", **dict(write_file)})

        bash_script = str(params.get("bash_script") or params.get("bash") or "").strip()
        if bash_script:
            synthesized.append({"type": "run_bash", "script": bash_script})

        python_code = str(params.get("python_code") or params.get("python") or "").strip()
        if python_code:
            synthesized.append({"type": "run_python", "code": python_code})

        wallpaper_path = str(params.get("wallpaper_path") or "").strip()
        if wallpaper_path:
            synthesized.append({"type": "change_wallpaper", "path": wallpaper_path})

        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        if wait_ms > 0:
            synthesized.append({"type": "wait", "ms": wait_ms})

        if not synthesized:
            raise ValueError("no setup steps were provided")
        return synthesized

    @staticmethod
    def _coerce_sequence(value: Any) -> Iterable[Mapping[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, Mapping)]

    @staticmethod
    def _resolve_local_path(raw_path: str, run_dir: Any) -> str:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return str(path)
        if run_dir is not None:
            return str((Path(run_dir) / path).resolve())
        return str(path.resolve())

    def _execute_step(self, controller: Any, step: Mapping[str, Any], *, run_dir: Any) -> Any:
        step_type = str(step.get("type") or "").strip()
        if step_type == "launch_app":
            step_type = "launch"
        elif step_type == "run_command":
            step_type = "execute_command"

        if step_type == "launch":
            app_name = str(step.get("app_name") or step.get("command") or "").strip()
            if not app_name:
                raise ValueError("launch step requires app_name")
            return controller.launch_app(app_name)

        if step_type == "wait":
            wait_ms = max(0, int(step.get("ms", self.DEFAULT_WAIT_MS) or 0))
            time.sleep(wait_ms / 1000.0)
            return {"status": "success", "wait_ms": wait_ms}

        if step_type == "run_bash":
            script = str(step.get("script") or "").strip()
            if not script:
                raise ValueError("run_bash step requires script")
            timeout = int(step.get("timeout", 30) or 30)
            working_dir = step.get("working_dir")
            return controller.run_bash_script(script, timeout=timeout, working_dir=working_dir)

        if step_type == "run_python":
            code = str(step.get("code") or "").strip()
            if not code:
                raise ValueError("run_python step requires code")
            return controller.run_python_script(code)

        if step_type == "execute_command":
            command = step.get("command")
            if not command:
                raise ValueError("execute_command step requires command")
            return controller.execute_command(
                command,
                shell=bool(step.get("shell", isinstance(command, str))),
                timeout=int(step.get("timeout", 120) or 120),
            )

        if step_type == "execute_with_verification":
            command = step.get("command")
            if not command:
                raise ValueError("execute_with_verification step requires command")
            verification = step.get("verification")
            return controller.execute_command_with_verification(
                command,
                shell=bool(step.get("shell", isinstance(command, str))),
                verification=dict(verification or {}),
                max_wait_time=int(step.get("max_wait_time", 10) or 10),
                check_interval=float(step.get("check_interval", 1.0) or 1.0),
            )

        if step_type == "upload_file":
            local_path = str(step.get("local_path") or "").strip()
            remote_path = str(step.get("path") or step.get("remote_path") or "").strip()
            if not local_path or not remote_path:
                raise ValueError("upload_file step requires local_path and path")
            resolved_local = self._resolve_local_path(local_path, run_dir)
            return controller.upload_file(resolved_local, remote_path)

        if step_type == "download":
            url = str(step.get("url") or "").strip()
            remote_path = str(step.get("path") or step.get("remote_path") or "").strip()
            if not url or not remote_path:
                raise ValueError("download step requires url and path")
            cached_path = local_cache_for_url(url)
            if cached_path is not None:
                return controller.upload_file(str(cached_path), remote_path)
            return controller.download_file(url, remote_path, overwrite=bool(step.get("overwrite", True)))

        if step_type == "write_file":
            remote_path = str(step.get("path") or step.get("remote_path") or "").strip()
            content = step.get("content")
            if not remote_path or not isinstance(content, str):
                raise ValueError("write_file step requires path and string content")
            return controller.write_file(
                remote_path,
                content,
                encoding=str(step.get("encoding") or "utf-8"),
                overwrite=bool(step.get("overwrite", True)),
            )

        if step_type == "change_wallpaper":
            wallpaper_path = str(step.get("path") or "").strip()
            if not wallpaper_path:
                raise ValueError("change_wallpaper step requires path")
            resolved_path = self._resolve_local_path(wallpaper_path, run_dir)
            return controller.change_wallpaper(resolved_path)

        raise ValueError(f"Unsupported setup step type: {step_type}")
