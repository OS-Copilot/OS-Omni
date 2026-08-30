"""Android initializer for the Oinkoin create-expense benchmark task."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from platforms.android.bootstrap import AndroidBootstrapDriver
from platforms.android.oinkoin_support import ensure_app_installed


class OinkoinCreateExpenseInitializer(BaseInitializer):
    """Prepare Oinkoin from a fresh state for the create-expense benchmark."""

    DEFAULT_APP_PACKAGE = "com.github.emavgl.piggybankpro"
    DEFAULT_APP_ACTIVITY = "com.example.piggybank.MainActivity"
    DEFAULT_WAIT_MS = 1500

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for Oinkoin initialization",
            )

        app_package = str(params.get("app_package") or self.DEFAULT_APP_PACKAGE).strip()
        app_activity = str(params.get("app_activity") or self.DEFAULT_APP_ACTIVITY).strip()
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        clear_app_data = bool(params.get("clear_app_data", True))

        if not app_package or not app_activity:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires app_package and app_activity",
            )

        try:
            ensure_app_installed(controller, app_package)

            controller.execute_adb(["shell", "am", "force-stop", app_package])
            if clear_app_data:
                controller.execute_adb(["shell", "pm", "clear", app_package])

            controller.execute_adb(["shell", "am", "start", "-n", f"{app_package}/{app_activity}"])
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

            self._wait_for_home_ready(controller, app_package)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Oinkoin task: {type(exc).__name__}: {exc}",
                metadata={
                    "app_package": app_package,
                    "app_activity": app_activity,
                    "clear_app_data": clear_app_data,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Oinkoin opened from a fresh state",
            metadata={
                "app_package": app_package,
                "app_activity": app_activity,
                "wait_ms": wait_ms,
                "clear_app_data": clear_app_data,
            },
        )

    @staticmethod
    def _wait_for_home_ready(controller: Any, app_package: str) -> None:
        driver = AndroidBootstrapDriver(controller, expected_package=app_package, settle_delay_seconds=0.5)
        node = driver.wait_for_node(
            [
                {"resource_id": "add-record", "package": app_package},
                {"resource_id": "home-tab-selected", "package": app_package},
            ],
            timeout_seconds=12.0,
            raise_on_timeout=False,
        )
        if node is not None:
            return

        focus_output = str(
            controller.execute_adb(
                [
                    "shell",
                    "sh",
                    "-c",
                    "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'",
                ]
            )
            or ""
        )
        if app_package not in focus_output:
            raise RuntimeError(
                f"Oinkoin did not become the foreground app: {focus_output or 'no focus output'}"
            )
