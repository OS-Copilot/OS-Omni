"""OpenSheet quarterly-sales snapshot initializer."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import cleanup_paths, launch_guest, verify_paths


class LinuxOpenSheetAsterReviewInitializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        app_path = str(params.get("app_path") or "/home/user/Applications/opensheet_web/public/index.html")
        try:
            verify_paths(controller, [app_path])
            cleaned = cleanup_paths(controller, params.get("cleanup_paths", []))
            launch_guest(controller, f"file://{app_path}", wait_ms=int(params.get("wait_ms", 3000) or 0))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"Failed to prepare OpenSheet: {exc}")
        return InitResult(
            InitStatus.PASS,
            "Initializer validated and opened OpenSheet after removing stale exports",
            {
                "app_path": app_path,
                "cleanup_paths": cleaned,
                "snapshot_name": str(params.get("snapshot_name") or ""),
            },
        )
