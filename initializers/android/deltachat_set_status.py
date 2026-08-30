"""Android initializer for the Delta Chat set-status task."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.android.mail_app_utils import (
    launch_mail_or_chat_app,
    reset_delta_chat_account_if_requested,
)


class DeltaChatSetStatusInitializer(BaseInitializer):
    """Launch Delta Chat and ensure it is in the foreground for status setting."""

    DEFAULT_APP_PACKAGE = "chat.delta"
    DEFAULT_APP_ACTIVITY = "org.thoughtcrime.securesms.RoutingActivity"
    DEFAULT_WAIT_MS = 2000

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None or not hasattr(controller, "execute_adb"):
            return InitResult(
                status=InitStatus.ERROR,
                message="controller.execute_adb is required for Delta Chat initialization",
            )

        app_package = str(params.get("app_package") or self.DEFAULT_APP_PACKAGE).strip()
        app_activity = str(params.get("app_activity") or self.DEFAULT_APP_ACTIVITY).strip()
        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)
        api_base_url = str(params.get("api_base_url") or "http://127.0.0.1:8081").rstrip("/")

        try:
            reset_delta_chat_account_if_requested(
                controller,
                params,
                api_base_url=api_base_url,
            )
            ok, focus_output = launch_mail_or_chat_app(
                controller,
                app_package=app_package,
                app_activity=app_activity,
                label="Delta Chat",
                wait_ms=wait_ms,
            )
            if not ok:
                return InitResult(
                    status=InitStatus.FAIL,
                    message=f"Delta Chat did not become the foreground app: {focus_output or 'no focus output'}",
                    metadata={"app_package": app_package, "focus_output": focus_output},
                )

        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to prepare Delta Chat task: {type(exc).__name__}: {exc}",
                metadata={"app_package": app_package},
            )

        return InitResult(
            status=InitStatus.PASS,
            message="Delta Chat opened for status setting",
            metadata={
                "app_package": app_package,
                "app_activity": app_activity,
                "reset_app_data": bool(params.get("reset_app_data", False)),
            },
        )
