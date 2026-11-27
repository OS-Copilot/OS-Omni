from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from platforms.macos.host.runners.base_episode import BaseEpisodeRunner


class TypingPreludeTests(unittest.TestCase):
    def _fake_pyautogui(self, events):
        module = types.ModuleType("pyautogui")
        module.PAUSE = 0
        module.FAILSAFE = True
        module.typewrite = lambda *args, **kwargs: events.append(("fallback", args, kwargs))
        module.write = module.typewrite
        module.press = lambda key, *args, **kwargs: events.append(("press", key))
        module.keyDown = lambda key, *args, **kwargs: events.append(("keyDown", key))
        module.keyUp = lambda key, *args, **kwargs: events.append(("keyUp", key))
        module.hotkey = lambda *keys, **kwargs: events.append(("hotkey", keys))
        return module

    def _fake_time(self, events):
        module = types.ModuleType("time")
        module.sleep = lambda duration: events.append(("sleep", duration))
        return module

    def _fake_subprocess(self, events, returncode=0):
        module = types.ModuleType("subprocess")

        class Result:
            stdout = ""
            stderr = ""

        def run(args, **kwargs):
            events.append(("osascript", args, kwargs))
            result = Result()
            result.returncode = returncode
            return result

        module.run = run
        return module

    def test_ascii_text_uses_layout_independent_system_events_keystroke(self) -> None:
        events = []
        with mock.patch.dict(sys.modules, {
            "pyautogui": self._fake_pyautogui(events),
            "subprocess": self._fake_subprocess(events),
            "time": self._fake_time(events),
        }):
            prelude = BaseEpisodeRunner._build_python_action_prelude(None)
            exec(prelude + "\npyautogui.typewrite('Driver@2026!', interval=0.05)\n", {})

        call = next(event for event in events if event[0] == "osascript")
        self.assertEqual(call[1][-1], "Driver@2026!")
        self.assertIn("System Events", call[1][2])
        self.assertFalse(any(event[0] == "press" for event in events))
        self.assertIn(("sleep", 0.05), events)

    def test_non_ascii_text_uses_system_events_keystroke(self) -> None:
        events = []
        with mock.patch.dict(sys.modules, {
            "pyautogui": self._fake_pyautogui(events),
            "subprocess": self._fake_subprocess(events),
            "time": self._fake_time(events),
        }):
            prelude = BaseEpisodeRunner._build_python_action_prelude(None)
            exec(prelude + "\npyautogui.write('你好', interval=0)\n", {})

        call = next(event for event in events if event[0] == "osascript")
        self.assertEqual(call[1][-1], "你好")

    def test_newline_uses_enter_key(self) -> None:
        events = []
        with mock.patch.dict(sys.modules, {
            "pyautogui": self._fake_pyautogui(events),
            "subprocess": self._fake_subprocess(events),
            "time": self._fake_time(events),
        }):
            prelude = BaseEpisodeRunner._build_python_action_prelude(None)
            exec(prelude + "\npyautogui.write('x\\n', interval=0)\n", {})

        call = next(event for event in events if event[0] == "osascript")
        self.assertEqual(call[1][-1], "x")
        self.assertIn(("press", "enter"), events)

    def test_nonzero_osascript_exit_is_not_reported_as_success(self) -> None:
        events = []
        with mock.patch.dict(sys.modules, {
            "pyautogui": self._fake_pyautogui(events),
            "subprocess": self._fake_subprocess(events, returncode=1),
            "time": self._fake_time(events),
        }):
            prelude = BaseEpisodeRunner._build_python_action_prelude(None)
            with self.assertRaisesRegex(RuntimeError, "text injection failed"):
                exec(prelude + "\npyautogui.typewrite('text')\n", {})


if __name__ == "__main__":
    unittest.main()
