"""OpenBank Ubuntu snapshot launcher and session validator."""

from __future__ import annotations

import shlex
from pathlib import PurePosixPath
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import launch_guest, run_guest, verify_paths


class OpenBankUbuntu10Initializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        shortcut = str(params.get("shortcut") or "/home/user/Desktop/OpenBank")
        debug_port = int(params.get("debug_port", 1337) or 1337)
        login = str(params.get("login") or "")
        try:
            try:
                verify_paths(controller, [shortcut])
            except RuntimeError:
                # The v3 image keeps the desktop webpage entries under Desktop/webpage.
                fallback = str(PurePosixPath(shortcut).parent / "webpage" / PurePosixPath(shortcut).name)
                verify_paths(controller, [fallback])
                shortcut = fallback
            launch_guest(controller, shortcut, wait_ms=int(params.get("wait_ms", 4000) or 0))
            # Validate that Chrome exposes a live page. Login state remains snapshot-owned.
            run_guest(
                controller,
                f"curl -fsS --max-time 5 {shlex.quote(f'http://127.0.0.1:{debug_port}/json')} >/dev/null",
                timeout=10,
            )
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"Failed to open or validate OpenBank: {exc}")
        return InitResult(
            InitStatus.PASS,
            "Opened OpenBank from the Ubuntu desktop shortcut",
            {
                "shortcut": shortcut,
                "debug_port": debug_port,
                "login": login,
                "business_state_written": False,
            },
        )
