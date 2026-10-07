"""OpenMail initializers reconstructed from reviewed Linux artifacts."""

from __future__ import annotations

import shlex
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import SnapshotOpenAppInitializer, run_guest


class OpenMailInitializer(SnapshotOpenAppInitializer):
    default_app_name = "OpenMail"
    default_app_command = "openmail"


class OpenMailShortcutInitializer(BaseInitializer):
    """Validate the snapshot shortcut while leaving OpenMail closed."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        webpage_dirs = [str(value) for value in params.get("webpage_dirs", [])]
        shortcut_names = [str(value) for value in params.get("shortcut_names", ["OpenMail"])]
        conditions = []
        for directory in webpage_dirs:
            for name in shortcut_names:
                conditions.append(f"test -e {shlex.quote(directory.rstrip('/') + '/' + name)}")
        probe = " || ".join(conditions) or "false"
        try:
            run_guest(controller, probe, timeout=20)
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"OpenMail shortcut is unavailable: {exc}")
        return InitResult(
            InitStatus.PASS,
            "OpenMail initial desktop state prepared",
            {
                "vm_snapshot": str(params.get("vm_snapshot") or ""),
                "webpage_dirs": webpage_dirs,
                "shortcut_names": shortcut_names,
                "business_state_mutated": False,
            },
        )


class OpenMailDesktopInitializer(BaseInitializer):
    """Validate a snapshot-provided OpenMail desktop entry."""

    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        desktop_dir = str(params.get("desktop_dir") or "/home/user/Desktop").rstrip("/")
        webpage_dir = f"{desktop_dir}/{params.get('webpage_dir_name') or 'webpage'}"
        tokens = [str(value).lower() for value in params.get("launcher_name_tokens", ["openmail"])]
        token_tests = " || ".join(
            f"printf '%s\\n' \"$candidate\" | grep -qi -- {shlex.quote(token)}" for token in tokens
        )
        script = (
            f"test -d {shlex.quote(webpage_dir)}\n"
            f"for candidate in {shlex.quote(webpage_dir)}/*; do "
            f"[ -e \"$candidate\" ] || continue; if {token_tests}; then exit 0; fi; done\nexit 1"
        )
        try:
            run_guest(controller, script, timeout=int(params.get("timeout", 20) or 20))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"OpenMail desktop launcher is unavailable: {exc}")
        return InitResult(
            InitStatus.PASS,
            "OpenMail desktop launcher is present",
            {"webpage_dir": webpage_dir, "snapshot_name": str(params.get("snapshot_name") or "")},
        )
