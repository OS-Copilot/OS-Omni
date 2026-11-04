"""OpenSheet monthly-budget snapshot initializer."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import launch_guest, verify_paths
from initializers.linux.opensheet import patch_edit_commit


class LinuxOpenSheetMonthlyBudgetInitializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        app_path = str(params.get("app_path") or "/home/user/Applications/opensheet_web/public/index.html")
        try:
            verify_paths(controller, [app_path])
            patch = patch_edit_commit(controller, str(PurePosixPath(app_path).with_name("app.js")))
            launch_guest(controller, f"file://{app_path}", wait_ms=int(params.get("wait_ms", 3000) or 0))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"Failed to prepare OpenSheet: {exc}")
        return InitResult(
            InitStatus.PASS,
            "Initializer validated and opened OpenSheet without changing workbook state",
            {"app_path": app_path, "snapshot_name": str(params.get("snapshot_name") or ""), "edit_commit_patch": patch},
        )
