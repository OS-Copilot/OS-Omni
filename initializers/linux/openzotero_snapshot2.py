"""OpenZotero Snapshot 2 compatibility initializer."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import launch_guest, verify_paths


class OpenZoteroSnapshot2Initializer(BaseInitializer):
    APP_PATH = "/home/user/Desktop/webpage/OpenZotero"

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        try:
            verify_paths(controller, [self.APP_PATH])
            launch_guest(controller, self.APP_PATH, wait_ms=int(params.get("wait_ms", 3000) or 0))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"Failed to prepare OpenZotero: {exc}")
        return InitResult(
            InitStatus.PASS,
            "OpenZotero ready without changing persisted business state",
            {
                "app_path": self.APP_PATH,
                "snapshot_name": str(params.get("snapshot_name") or ""),
                "business_state_mutated": False,
                "cleared_state": False,
            },
        )
