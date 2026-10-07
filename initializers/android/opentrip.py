"""Initializers for Android OpenTrip tasks restored from reviewed runs."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.android.app_utils import launch_app_cleanly
from platforms.android.opentrip_support import DEFAULT_APP_ACTIVITY, DEFAULT_APP_PACKAGE


class OpenTripSnapshotOpenInitializer(BaseInitializer):
    """Open an already-seeded OpenTrip snapshot without mutating task state."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for OpenTrip initialization",
            )

        app_package = str(params.get("app_package") or DEFAULT_APP_PACKAGE).strip()
        app_activity = str(params.get("app_activity") or DEFAULT_APP_ACTIVITY).strip()
        wait_ms = int(params.get("wait_ms", 1800) or 0)
        clear_app_data = bool(params.get("clear_app_data", False))
        snapshot_name = str(params.get("snapshot_name") or "").strip()

        try:
            package_path = str(
                controller.execute_adb(["shell", "pm", "path", app_package]) or ""
            )
            if "package:" not in package_path:
                raise RuntimeError(f"OpenTrip package is not installed: {app_package}")
            ok, foreground = launch_app_cleanly(
                controller,
                app_package=app_package,
                app_activity=app_activity,
                clear_app_data=clear_app_data,
                wait_ms=wait_ms,
            )
            if not ok:
                raise RuntimeError(f"OpenTrip did not reach foreground: {foreground}")
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to open OpenTrip: {type(exc).__name__}: {exc}",
                metadata={"app_package": app_package, "snapshot_name": snapshot_name},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Opened OpenTrip using the existing seeded snapshot state",
            metadata={
                "app_package": app_package,
                "app_activity": app_activity,
                "snapshot_name": snapshot_name,
                "clear_app_data": clear_app_data,
                "foreground": foreground,
            },
        )
