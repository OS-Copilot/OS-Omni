"""OpenBlender snapshot preflight recovered from successful review runs."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import launch_guest, verify_paths


class OpenBlenderLoftInitializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        workspace_root = str(params.get("workspace_root") or "/home/user/Desktop/Blender/02_recent_projects")
        workspace_name = str(params.get("workspace_name") or "loft_room_lighting_study")
        scene_name = str(params.get("scene_name") or "loft_room_lighting_v03_final.blend")
        webpage_dir = str(params.get("webpage_dir") or "/home/user/Desktop/webpage")
        workspace_path = f"{workspace_root.rstrip('/')}/{workspace_name}"
        blend_path = f"{workspace_path}/{scene_name}"
        entry = f"{webpage_dir.rstrip('/')}/OpenBlender"
        try:
            verify_paths(controller, [workspace_path, blend_path, webpage_dir, entry])
            if bool(params.get("launch_prepared_file", False)):
                launch_guest(controller, blend_path, wait_ms=int(params.get("wait_ms", 3000) or 0))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"OpenBlender snapshot prerequisites failed: {exc}")
        return InitResult(
            InitStatus.PASS,
            "Prepared OpenBlender initial state; no final task edits were applied",
            {
                "workspace_path": workspace_path,
                "blend_path": blend_path,
                "webpage_dir": webpage_dir,
                "openblender_entry": entry,
                "snapshot_name": str(params.get("snapshot_name") or ""),
                "launch_prepared_file": bool(params.get("launch_prepared_file", False)),
            },
        )
