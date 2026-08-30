"""Android app-launch initializer.

Opens a specified app on the Android device before the task begins.
Uses ADB via the controller to launch the best available package/activity pair.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from platforms.android.bench_storage_support import remove_path
from initializers.android.app_utils import launch_app_cleanly


_APP_LAUNCH_MAP: dict[str, list[dict[str, str]]] = {
    "calculator": [
        {"package": "org.fossify.math", "activity": ".activities.SplashActivity.Green"},
        {"package": "com.android.calculator2", "activity": "com.android.calculator2.Calculator"},
        {"package": "com.google.android.calculator", "activity": "com.android.calculator2.Calculator"},
    ],
    "contacts": [
        {"package": "com.google.android.contacts", "activity": "com.google.android.contacts.activities.PeopleActivity"},
        {"package": "com.android.contacts", "activity": "com.android.contacts.activities.PeopleActivity"},
    ],
    "clock": [
        {"package": "com.google.android.deskclock", "activity": "com.android.deskclock.DeskClock"},
        {"package": "com.android.deskclock", "activity": "com.android.deskclock.DeskClock"},
    ],
    "settings": [
        {"package": "com.android.settings", "activity": "com.android.settings.Settings"},
    ],
    "markor": [
        {"package": "net.gsantner.markor", "activity": "net.gsantner.markor.activity.MainActivity"},
    ],
    "camera": [
        {"package": "com.android.camera2", "activity": "com.android.camera.CameraLauncher"},
    ],
    "dialer": [
        {"package": "com.google.android.dialer", "activity": "com.google.android.dialer.extensions.GoogleDialtactsActivity"},
        {"package": "com.android.dialer", "activity": "com.android.dialer.main.impl.MainActivity"},
    ],
}


class OpenAppInitializer(BaseInitializer):
    """Launch the target Android app before the episode starts."""

    DEFAULT_WAIT_MS = 1000

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="controller is required for Android initialization",
            )

        app_name = str(params.get("app_name") or "").strip()
        if not app_name:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires params.app_name",
            )

        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        clear_app_data = bool(params.get("clear_app_data", False))
        remove_paths = [str(path).strip() for path in (params.get("remove_paths") or []) if str(path).strip()]

        try:
            app_key = app_name.lower().strip()
            launch_candidates = _APP_LAUNCH_MAP.get(app_key, [])

            if hasattr(controller, "execute_adb") and launch_candidates:
                launched = False
                last_missing: list[str] = []
                for candidate in launch_candidates:
                    package = candidate["package"]
                    activity = candidate["activity"]
                    package_path = str(controller.execute_adb(["shell", "pm", "path", package]) or "")
                    if "package:" not in package_path:
                        last_missing.append(package)
                        continue
                    for remote_path in remove_paths:
                        remove_path(controller, remote_path)
                    ok, focus_output = launch_app_cleanly(
                        controller,
                        app_package=package,
                        app_activity=activity,
                        clear_app_data=clear_app_data,
                        wait_ms=wait_ms,
                    )
                    if not ok:
                        raise RuntimeError(
                            f"App did not become foreground: {focus_output or 'no focus output'}"
                        )
                    launched = True
                    break
                if not launched:
                    raise RuntimeError(
                        "App package is not installed: " + ", ".join(last_missing or [app_name])
                    )
            elif hasattr(controller, "launch_app"):
                controller.launch_app(app_name)
            elif hasattr(controller, "execute_action"):
                controller.execute_action({"type": "open_app", "app_name": app_name}, [])
            elif hasattr(controller, "execute_adb"):
                package = launch_candidates[0]["package"] if launch_candidates else app_name
                controller.execute_adb([
                    "shell", "monkey", "-p", package,
                    "-c", "android.intent.category.LAUNCHER", "1",
                ])
            else:
                return InitResult(
                    status=InitStatus.ERROR,
                    message="controller does not support any known app launch method",
                )

            if not launch_candidates and wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to open app '{app_name}': {exc}",
                metadata={"app_name": app_name, "wait_ms": wait_ms, "clear_app_data": clear_app_data},
            )

        return InitResult(
            status=InitStatus.PASS,
            message=f"Opened app '{app_name}'",
            metadata={
                "app_name": app_name,
                "wait_ms": wait_ms,
                "clear_app_data": clear_app_data,
                "remove_paths": remove_paths,
            },
        )
