"""OpenZotero snapshot preflight initializers."""

from __future__ import annotations

import shlex
from typing import Any, Mapping

from core.init import BaseInitializer, InitResult, InitStatus
from initializers.linux.cua_review import run_guest


def _launcher_probe(directory: str, tokens: list[str]) -> str:
    tests = " || ".join(
        f"printf '%s\\n' \"$candidate\" | grep -qi -- {shlex.quote(token)}" for token in tokens
    )
    return (
        f"test -d {shlex.quote(directory)}\n"
        "found_launcher=\n"
        f"for candidate in {shlex.quote(directory)}/*; do [ -e \"$candidate\" ] || continue; "
        f"if {tests}; then found_launcher=$candidate; break; fi; done\n"
        "test -n \"$found_launcher\"\nprintf '%s\\n' \"$found_launcher\""
    )


class OpenZoteroDesktopInitializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        desktop = str(params.get("desktop_dir") or "/home/user/Desktop").rstrip("/")
        webpage_dir = f"{desktop}/{params.get('webpage_dir_name') or 'webpage'}"
        tokens = [str(value).lower() for value in params.get("launcher_name_tokens", ["openzotero"])]
        try:
            result = run_guest(controller, _launcher_probe(webpage_dir, tokens), timeout=int(params.get("timeout", 20) or 20))
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"OpenZotero launcher validation failed: {exc}")
        return InitResult(
            InitStatus.PASS,
            "OpenZotero desktop launcher is present",
            {
                "webpage_dir": webpage_dir,
                "snapshot_name": str(params.get("snapshot_name") or ""),
                "found_launcher": str(result.get("output") or "").strip(),
            },
        )


class OpenZoteroInitializer(BaseInitializer):
    def initialize(self, context: Mapping[str, Any]) -> InitResult:
        controller = context.get("controller")
        params = dict(context.get("params") or {})
        directory = str(params.get("desktop_webpage_dir") or "/home/user/Desktop/webpage")
        tokens = [str(value).lower() for value in params.get("entry_name_patterns", ["openzotero"])]
        chrome = [str(value) for value in params.get("chrome_commands", ["google-chrome", "chromium"])]
        commands = " || ".join(f"command -v {shlex.quote(value)} >/dev/null 2>&1" for value in chrome)
        try:
            run_guest(
                controller,
                _launcher_probe(directory, tokens) + "\n" + f"({commands})",
                timeout=int(params.get("timeout", 30) or 30),
            )
        except Exception as exc:
            return InitResult(InitStatus.ERROR, f"OpenZotero prerequisites failed: {exc}")
        return InitResult(
            InitStatus.PASS,
            "Validated OpenZotero launcher prerequisites from existing VM state",
            {
                "desktop_webpage_dir": directory,
                "snapshot_name": str(params.get("snapshot_name") or ""),
                "business_state_mutated": False,
            },
        )
