"""Snapshot asset checks for OpenPhoto Edit tasks."""

from __future__ import annotations

from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import cleanup_paths, seed_bundled_attachments, verify_paths


class OpenPhotoEditInitializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        attachment_dir = str(params.get("attachment_dir") or "/home/user/Desktop/attachment").rstrip("/")
        required_files = [str(value) for value in params.get("required_files", [])]
        required_paths = [f"{attachment_dir}/{name}" for name in required_files]
        webpage_dir = str(params.get("webpage_dir") or "/home/user/Desktop/webpage")
        try:
            seeded = seed_bundled_attachments(controller, required_paths)
            verify_paths(controller, [webpage_dir, *required_paths])
            cleaned = cleanup_paths(controller, params.get("cleanup_paths", []))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"OpenPhoto Edit prerequisites failed: {exc}")
        return InitResult(
            InitStatus.PASS,
            "Verified OpenPhoto Edit desktop assets from the current VM snapshot",
            {
                "attachment_dir": attachment_dir,
                "required_files": required_files,
                "cleanup_paths": cleaned,
                "seeded_attachments": seeded,
                "snapshot_name": str(params.get("snapshot_name") or ""),
                "business_state_mutated": False,
            },
        )
