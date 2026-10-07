"""Compatibility initializers for partially reconstructed reviewed tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.android.app_utils import launch_app_cleanly


class SnapshotOpenAppInitializer(BaseInitializer):
    """Open an app while preserving the state supplied by a VM snapshot."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for Android initialization",
            )

        candidates = [
            str(value).strip()
            for value in (params.get("package_candidates") or [])
            if str(value).strip()
        ]
        primary = str(params.get("app_package") or "").strip()
        if primary and primary not in candidates:
            candidates.insert(0, primary)
        if not candidates:
            return InitResult(
                status=InitStatus.ERROR,
                message="initializer requires app_package or package_candidates",
            )

        app_activity = str(params.get("app_activity") or "").strip()
        if app_activity.lower() == "launcher":
            app_activity = ""
        wait_ms = int(params.get("wait_ms", 1500) or 0)
        clear_app_data = bool(params.get("clear_app_data", False))
        snapshot_name = str(
            params.get("snapshot_name") or params.get("requested_snapshot_label") or ""
        ).strip()

        errors: list[str] = []
        for app_package in candidates:
            try:
                package_path = str(
                    controller.execute_adb(["shell", "pm", "path", app_package]) or ""
                )
                if "package:" not in package_path:
                    errors.append(f"{app_package}: not installed")
                    continue
                ok, foreground = launch_app_cleanly(
                    controller,
                    app_package=app_package,
                    app_activity=app_activity,
                    clear_app_data=clear_app_data,
                    wait_ms=wait_ms,
                )
                if not ok:
                    errors.append(f"{app_package}: not foreground ({foreground})")
                    continue
                return InitResult(
                    status=InitStatus.PASS,
                    message=f"Opened {app_package} using existing snapshot state",
                    metadata={
                        "app_package": app_package,
                        "snapshot_name": snapshot_name,
                        "clear_app_data": clear_app_data,
                        "foreground": foreground,
                    },
                )
            except Exception as exc:
                errors.append(f"{app_package}: {type(exc).__name__}: {exc}")

        return InitResult(
            status=InitStatus.ERROR,
            message="Failed to open any configured Android package",
            metadata={"snapshot_name": snapshot_name, "errors": errors},
        )
