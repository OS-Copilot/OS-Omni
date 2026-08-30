"""Initializer utilities for Wireshark desktop tasks on Linux."""

from __future__ import annotations

import json
import shlex
import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


RETAIL_MIX_PCAPNG_B64 = (
    "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"
    "AABQAiAAoyUAAAAAWAAAAA=="
)


WIRESHARK_CAPTURE_TEMPLATES = {
    "retail_mix": RETAIL_MIX_PCAPNG_B64,
}


class WiresharkInitializer(BaseInitializer):
    """Prepare a deterministic capture workspace and launch Wireshark on a seeded file."""

    DEFAULT_APP_COMMAND = "wireshark"
    DEFAULT_WORKSPACE_ROOT = "/tmp/helloworld_wireshark"
    DEFAULT_FINAL_WAIT_MS = 4500

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required")

        app_command = str(params.get("app_command") or self.DEFAULT_APP_COMMAND).strip()
        workspace_root = str(params.get("workspace_root") or self.DEFAULT_WORKSPACE_ROOT).strip()
        capture_name = str(params.get("capture_name") or "retail_mix.pcapng").strip() or "retail_mix.pcapng"
        capture_template = str(params.get("capture_template") or "retail_mix").strip() or "retail_mix"
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or self.DEFAULT_FINAL_WAIT_MS)
        capture_path = f"{workspace_root.rstrip('/')}/{capture_name}"

        try:
            self._run(controller, f"command -v {shlex.quote(app_command)} >/dev/null 2>&1", timeout=10)
            self._run(controller, "command -v tshark >/dev/null 2>&1", timeout=10)
            self._stop_app(controller)
            self._prepare_workspace(
                controller,
                workspace_root=workspace_root,
                capture_path=capture_path,
                capture_b64=self._resolve_capture_template(capture_template),
            )
            self._launch_app(controller, app_command=app_command, capture_path=capture_path)
            if final_wait_ms > 0:
                time.sleep(final_wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Wireshark workspace: {exc}",
                metadata={"capture_path": capture_path},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared Wireshark workspace",
            metadata={"capture_path": capture_path, "workspace_root": workspace_root},
        )

    @staticmethod
    def _resolve_capture_template(capture_template: str) -> str:
        resolved = WIRESHARK_CAPTURE_TEMPLATES.get(capture_template)
        if resolved is None:
            raise RuntimeError(f"unknown Wireshark capture template: {capture_template}")
        return resolved

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
                    "pkill -TERM -f 'wireshark' || true",
                    "sleep 1",
                    "pkill -KILL -f 'wireshark' || true",
                    "sleep 1",
                ]
            ),
            timeout=15,
        )

    def _prepare_workspace(
        self,
        controller: Any,
        *,
        workspace_root: str,
        capture_path: str,
        capture_b64: str,
    ) -> None:
        payload = json.dumps(
            {
                "workspace_root": workspace_root,
                "capture_path": capture_path,
                "capture_b64": capture_b64,
            },
            ensure_ascii=False,
        )
        script = f"""python3 - <<'PY'
import base64
import json
import pathlib
import shutil

payload = json.loads({json.dumps(payload, ensure_ascii=False)})
workspace_root = pathlib.Path(payload["workspace_root"])
capture_path = pathlib.Path(payload["capture_path"])

if workspace_root.exists():
    shutil.rmtree(workspace_root)
workspace_root.mkdir(parents=True, exist_ok=True)
capture_path.parent.mkdir(parents=True, exist_ok=True)
capture_path.write_bytes(base64.b64decode(payload["capture_b64"]))

print(json.dumps({{"status": "ok", "capture_path": str(capture_path)}}, ensure_ascii=False))
PY"""
        self._run(controller, script, timeout=30)

    def _launch_app(self, controller: Any, *, app_command: str, capture_path: str) -> None:
        command = " ".join([shlex.quote(app_command), shlex.quote(capture_path)])
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
