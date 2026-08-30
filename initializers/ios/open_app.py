"""Simple iOS app-launch initializer."""

from __future__ import annotations

import time
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus


class OpenAppInitializer(BaseInitializer):
    """Bring the target iOS app to foreground before the episode starts."""

    DEFAULT_WAIT_MS = 500

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})

        if controller is None:
            return InitResult(
                status=InitStatus.ERROR,
                message="controller is required for iOS initialization",
            )

        bundle_id = str(
            params.get("bundle_id")
            or params.get("app_id")
            or params.get("launch_app_bundle_id")
            or ""
        ).strip()
        if not bundle_id:
            return InitResult(
                status=InitStatus.FAIL,
                message="initializer requires params.bundle_id or params.app_id",
            )

        wait_ms = int(params.get("wait_ms", self.DEFAULT_WAIT_MS) or 0)

        try:
            if hasattr(controller, "press_home"):
                controller.press_home()
                time.sleep(0.5)
            controller.activate_app(bundle_id)
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        except Exception as exc:
            return InitResult(
                status=InitStatus.ERROR,
                message=f"Failed to open app '{bundle_id}': {exc}",
                metadata={"bundle_id": bundle_id, "wait_ms": wait_ms},
            )

        return InitResult(
            status=InitStatus.PASS,
            message=f"Opened app '{bundle_id}'",
            metadata={"bundle_id": bundle_id, "wait_ms": wait_ms},
        )
