"""Initializer for resetting the Clock app on Android.

Clears Clock app data via ADB to reset the stopwatch to its initial
paused state (00:00:00) before the task begins.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


_CLOCK_CANDIDATES = (
    "com.google.android.deskclock",
    "com.android.deskclock",
)
_CLOCK_ACTIVITY = "com.android.deskclock.DeskClock"


class ResetClockInitializer(BaseInitializer):
    """Clear Clock app data and relaunch it before the episode starts."""

    DEFAULT_WAIT_MS = 800

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="controller is required for Clock reset initialization",
            )

        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)

        try:
            if not hasattr(controller, "execute_adb"):
                return InitResult(
                    status=InitStatus.ERROR,
                    message="controller.execute_adb is required for Clock reset",
                )

            package = ""
            for candidate in _CLOCK_CANDIDATES:
                package_path = str(controller.execute_adb(["shell", "pm", "path", candidate]) or "")
                if "package:" in package_path:
                    package = candidate
                    break
            if not package:
                return InitResult(
                    status=InitStatus.FAIL,
                    message=f"Clock app is not installed: {', '.join(_CLOCK_CANDIDATES)}",
                )

            controller.execute_adb(["shell", "pm", "clear", package])
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

            controller.execute_adb(["shell", "am", "start", "-n", f"{package}/{_CLOCK_ACTIVITY}"])
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to reset Clock app: {exc}",
                metadata={"wait_ms": wait_ms},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Reset Clock app data and relaunched",
            metadata={"package": package, "wait_ms": wait_ms},
        )
