"""Android initializer for OpenShop shopping tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from platforms.android.openshop_support import (
    DEFAULT_APP_ACTIVITY,
    DEFAULT_APP_PACKAGE,
    DEFAULT_WAIT_MS,
    prepare_fresh_openshop,
)


class OpenShopFreshOpenInitializer(BaseInitializer):
    """Reset OpenShop and leave it open on the home screen."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for OpenShop initialization",
            )

        app_package = str(params.get("app_package") or DEFAULT_APP_PACKAGE).strip()
        app_activity = str(params.get("app_activity") or DEFAULT_APP_ACTIVITY).strip()
        wait_ms = int(params.get("wait_ms", DEFAULT_WAIT_MS) or 0)
        clear_app_data = bool(params.get("clear_app_data", True))

        if not app_package or not app_activity:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires app_package and app_activity",
            )

        try:
            metadata = prepare_fresh_openshop(
                controller,
                app_package=app_package,
                app_activity=app_activity,
                clear_app_data=clear_app_data,
                wait_ms=wait_ms,
            )
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare OpenShop: {type(exc).__name__}: {exc}",
                metadata={
                    "app_package": app_package,
                    "app_activity": app_activity,
                    "clear_app_data": clear_app_data,
                },
            )

        return InitResult(
            status=InitStatus.PASS,
            message="OpenShop opened from a fresh local state",
            metadata=metadata,
        )
