"""Simple Windows app-launch initializer."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class OpenAppInitializer(BaseInitializer):
    """Launch the target Windows app before the episode starts."""

    DEFAULT_WAIT_MS = 800

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(status=InitStatus.ERROR, message="controller is required for Windows initialization")

        app_name = str(params.get("app_name") or params.get("launch_app") or "").strip()
        if not app_name:
            return InitResult(status=InitStatus.FAIL, message="initializer requires params.app_name or params.launch_app")

        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        # A fixed wait can end before a slow app shows its window; the agent then sees only the desktop and launches
        # a second instance, whose state the evaluator never reads. wait_for_window waits for the foreground title.
        wait_for_window = str(params.get("wait_for_window") or "").strip()
        window_timeout_ms = int(params.get("window_timeout_ms", 60000) or 0)
        metadata = {"app_name": app_name, "wait_ms": wait_ms}

        try:
            if hasattr(controller, "launch_app"):
                controller.launch_app(app_name)
            else:
                controller.execute_action({"type": "launch_app", "app_name": app_name}, [])
            if wait_for_window:
                started = time.monotonic()
                title = ""
                while True:
                    title = str(controller.observe(include_ui_tree=False, include_screenshot_data=False).foreground_window)
                    if wait_for_window.casefold() in title.casefold():
                        break
                    if (time.monotonic() - started) * 1000 >= window_timeout_ms:
                        return InitResult(
                            status=InitStatus.ERROR,
                            message=f"'{app_name}' window '{wait_for_window}' not in the foreground after "
                                    f"{window_timeout_ms} ms (foreground: '{title}')",
                            metadata=metadata,
                        )
                    time.sleep(0.5)
                metadata.update(window=title, window_wait_ms=round((time.monotonic() - started) * 1000))
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to open app '{app_name}': {exc}",
                metadata=metadata,
            )

        return InitResult(
            status=InitStatus.PASS,
            message=f"Opened app '{app_name}'",
            metadata=metadata,
        )
