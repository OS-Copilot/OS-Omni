"""Initializer utilities for GIMP image editing tasks on Linux."""

from __future__ import annotations

import json
import shlex
import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class GimpInitializer(BaseInitializer):
    """Prepare a test image workspace and launch GIMP for benchmark tasks."""

    DEFAULT_APP_COMMAND = "gimp"
    DEFAULT_WORKSPACE = "/tmp/helloworld_gimp"
    DEFAULT_INPUT_IMAGE = "/tmp/helloworld_gimp/input.png"
    DEFAULT_IMAGE_WIDTH = 1920
    DEFAULT_IMAGE_HEIGHT = 1080
    DEFAULT_FINAL_WAIT_MS = 5000
    DEFAULT_BOOT_TIMEOUT = 60

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "run_bash_script"):
            return InitResult(status=InitStatus.ERROR, message="controller.run_bash_script is required")

        app_command = str(params.get("app_command") or self.DEFAULT_APP_COMMAND).strip()
        workspace = str(params.get("workspace") or self.DEFAULT_WORKSPACE).strip()
        input_image = str(params.get("input_image") or self.DEFAULT_INPUT_IMAGE).strip()
        image_width = int(params.get("image_width", self.DEFAULT_IMAGE_WIDTH) or self.DEFAULT_IMAGE_WIDTH)
        image_height = int(params.get("image_height", self.DEFAULT_IMAGE_HEIGHT) or self.DEFAULT_IMAGE_HEIGHT)
        final_wait_ms = int(params.get("final_wait_ms", self.DEFAULT_FINAL_WAIT_MS) or self.DEFAULT_FINAL_WAIT_MS)

        try:
            self._run(controller, f"command -v {shlex.quote(app_command)} >/dev/null 2>&1", timeout=10)
            self._stop_app(controller)
            self._prepare_workspace(
                controller,
                workspace=workspace,
                input_image=input_image,
                image_width=image_width,
                image_height=image_height,
            )
            self._launch_app(controller, app_command=app_command, input_image=input_image)
            if final_wait_ms > 0:
                time.sleep(final_wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare GIMP workspace: {exc}",
                metadata={"workspace": workspace, "input_image": input_image},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Prepared GIMP benchmark workspace",
            metadata={"workspace": workspace, "input_image": input_image},
        )

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
            "\n".join([
                "pkill -TERM -f 'gimp' || true",
                "sleep 1",
                "pkill -KILL -f 'gimp' || true",
                "sleep 1",
            ]),
            timeout=15,
        )

    def _prepare_workspace(
        self,
        controller: Any,
        *,
        workspace: str,
        input_image: str,
        image_width: int,
        image_height: int,
    ) -> None:
        create_script = "\n".join([
            f"mkdir -p {shlex.quote(workspace)}",
            f"rm -f {shlex.quote(workspace)}/*.png {shlex.quote(workspace)}/*.jpg 2>/dev/null || true",
            "python3 - <<'PY'",
            "import sys",
            "try:",
            "    from PIL import Image, ImageDraw",
            "except ImportError:",
            "    sys.exit('Pillow is not installed; run: pip3 install Pillow')",
            f"w, h = {image_width}, {image_height}",
            "img = Image.new(\"RGB\", (w, h), color=(70, 130, 180))",
            "draw = ImageDraw.Draw(img)",
            "for i in range(0, w, 120):",
            "    draw.line([(i, 0), (i, h)], fill=(220, 220, 220), width=1)",
            "for j in range(0, h, 120):",
            "    draw.line([(0, j), (w, j)], fill=(220, 220, 220), width=1)",
            "draw.ellipse([(w//4, h//4), (3*w//4, 3*h//4)], outline=(255, 200, 0), width=8)",
            "draw.rectangle([(w//3, h//3), (2*w//3, 2*h//3)], outline=(220, 80, 80), width=6)",
            f"img.save({json.dumps(input_image)}, \"PNG\")",
            "PY",
        ])
        self._run(controller, create_script, timeout=30)

    def _launch_app(self, controller: Any, *, app_command: str, input_image: str) -> None:
        launch_script = "\n".join([
            "export DISPLAY=${DISPLAY:-:0}",
            "export XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}",
            "export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}",
            "export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}",
            f"setsid -f bash -lc {shlex.quote(app_command + ' ' + shlex.quote(input_image))} >/tmp/helloworld_gimp_launch.log 2>&1",
        ])
        self._run(controller, launch_script, timeout=15)
