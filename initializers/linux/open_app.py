"""Simple Linux app-launch initializer."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class OpenAppInitializer(BaseInitializer):
    """Launch the target Linux app before the episode starts."""

    DEFAULT_WAIT_MS = 800

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(status=InitStatus.ERROR, message="controller is required for Linux initialization")

        app_name = str(params.get("app_name") or params.get("launch_app") or "").strip()
        if not app_name:
            return InitResult(status=InitStatus.FAIL, message="initializer requires params.app_name or params.launch_app")

        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)

        try:
            if hasattr(controller, "launch_app"):
                controller.launch_app(app_name)
            else:
                controller.execute_action({"type": "launch_app", "app_name": app_name}, [])
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to open app '{app_name}': {exc}",
                metadata={"app_name": app_name, "wait_ms": wait_ms},
            )

        return InitResult(
            status=InitStatus.PASS,
            message=f"Opened app '{app_name}'",
            metadata={"app_name": app_name, "wait_ms": wait_ms},
        )

