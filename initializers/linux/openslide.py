"""Initializer for the snapshot-backed OpenSlide application."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import launch_guest, verify_paths


class OpenSlideInitializer(BaseInitializer):
    APP_PATH = "/home/user/Applications/openslide_web/public/index.html"

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        app_path = str(params.get("app_path") or self.APP_PATH)
        try:
            verify_paths(controller, [app_path])
            launch_guest(controller, f"file://{app_path}", wait_ms=int(params.get("wait_ms", 3000) or 0))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"Failed to prepare OpenSlide: {exc}", {"app_path": app_path})
        return InitResult(
            InitStatus.PASS,
            "OpenSlide ready without resetting persisted state",
            {"app_path": app_path, "cleared_state": False},
        )
