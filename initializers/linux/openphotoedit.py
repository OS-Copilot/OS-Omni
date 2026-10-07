"""OpenPhotoEdit desktop prerequisite initializer."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import launch_guest, seed_bundled_attachments, verify_paths


class OpenPhotoEditDesktopPrerequisiteInitializer(BaseInitializer):
    REQUIRED_PATHS = [
        "/home/user/Desktop/webpage/OpenPhotoEdit",
        "/home/user/Desktop/attachment/portrait_window_before.jpg",
        "/home/user/Desktop/attachment/portrait_window_detail.jpg",
    ]

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        required_paths = [str(value) for value in params.get("required_paths", self.REQUIRED_PATHS)]
        try:
            seeded = seed_bundled_attachments(controller, required_paths)
            verify_paths(controller, required_paths)
            launch_guest(controller, required_paths[0], wait_ms=int(params.get("wait_ms", 3000) or 0))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"OpenPhotoEdit prerequisites failed: {exc}")
        return InitResult(
            InitStatus.PASS,
            "OpenPhotoEdit is foreground and source photos are present",
            {"required_paths": required_paths, "seeded_attachments": seeded, "business_state_mutated": False},
        )
