"""Evaluator for single-screen Windows + Android tasks (phone mirrored with scrcpy).

Same rules as the Linux version (evaluators.linux.android_companion): the phone-side
evaluators (run from the host over adb), the Windows-side evaluators, every required
desktop-to-phone copy, and the GUI-only rule (no executed action invokes or types
``adb``/``scrcpy``) must all pass.

params:
  android: {evaluator_id, params} or a list of them, run against the phone (all must pass)
  windows: {evaluator_id, params} or a list of them, run against the desktop (all must pass)
  phone_copies: [{desktop_path, phone_path}] files the agent must copy from the desktop to the
           phone; each phone copy must have the desktop file's SHA-256
  forbidden_patterns: regexes checked against each executed action (default: adb, scrcpy)
"""

from __future__ import annotations

from typing import Any

from evaluators.linux.android_companion import LinuxAndroidCompositeEvaluator
from platforms.windows.android_companion import file_sha256_powershell


class WindowsAndroidCompositeEvaluator(LinuxAndroidCompositeEvaluator):
    DESKTOP = "windows"

    def desktop_sha256(self, desktop: Any, path: str) -> str:
        reply = desktop.run_powershell_script(file_sha256_powershell(path), timeout=30)
        return str(reply.get("output") or "").strip()
