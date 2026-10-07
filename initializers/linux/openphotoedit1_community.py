"""OpenPhotoEdit source-integrity and launch initializer."""

from __future__ import annotations

import shlex
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import launch_guest, run_guest


class OpenPhotoEdit1Initializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        sources = dict(params.get("sources") or {})
        checks = [
            f"printf '%s  %s\\n' {shlex.quote(str(digest))} {shlex.quote(str(path))} | sha256sum -c -"
            for path, digest in sources.items()
        ]
        try:
            run_guest(controller, "\n".join(checks) if checks else "true", timeout=30)
            launch_guest(controller, "/home/user/Desktop/webpage/OpenPhotoEdit", wait_ms=3000)
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"Failed to prepare OpenPhotoEdit: {exc}")
        return InitResult(
            InitStatus.PASS,
            "OpenPhotoEdit ready",
            {"sources_verified": sources, "business_state_mutations": []},
        )
