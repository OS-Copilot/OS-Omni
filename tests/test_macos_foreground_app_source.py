from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from platforms.macos.guest import runtime_server


class ForegroundAppSourceTests(unittest.TestCase):
    def test_system_events_frontmost_app_wins_over_stale_workspace_and_ax(self) -> None:
        class StaleApp:
            def localizedName(self):
                return "Blender"

            def bundleIdentifier(self):
                return "org.blenderfoundation.blender"

        class Workspace:
            @staticmethod
            def sharedWorkspace():
                return Workspace()

            @staticmethod
            def frontmostApplication():
                return StaleApp()

        runtime = object.__new__(runtime_server.RuntimeAutomation)
        with mock.patch.object(runtime_server, "APPKIT_AVAILABLE", True), \
             mock.patch.object(runtime_server, "NSWorkspace", Workspace, create=True), \
             mock.patch.object(runtime_server, "ACCESSIBILITY_AVAILABLE", True), \
             mock.patch.object(
                 runtime_server.subprocess,
                 "run",
                 return_value=SimpleNamespace(
                     returncode=0,
                     stdout="Actual|com.actualbudget.desktop\n",
                 ),
             ) as run, \
             mock.patch.object(runtime, "is_accessibility_trusted", side_effect=AssertionError("stale AX path used")):
            self.assertEqual(runtime._foreground_app(), ("Actual", "com.actualbudget.desktop"))
            self.assertEqual(run.call_args.args[0][0], "osascript")


if __name__ == "__main__":
    unittest.main()
