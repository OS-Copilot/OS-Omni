"""Initializer for the browser-based OpenWireshark application."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import launch_guest, verify_paths


class OpenWiresharkInitializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        launch_url = str(
            params.get("launch_url")
            or "file:///home/user/Applications/openwireshark_web/public/index.html"
        )
        try:
            if launch_url.startswith("file://"):
                verify_paths(controller, [launch_url.removeprefix("file://")])
            launch_guest(controller, launch_url, wait_ms=int(params.get("wait_ms", 5000) or 0))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"Failed to open OpenWireshark: {exc}", {"launch_url": launch_url})
        return InitResult(InitStatus.PASS, "OpenWireshark launched", {"launch_url": launch_url})
