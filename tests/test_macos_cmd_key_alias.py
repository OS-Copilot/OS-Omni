import sys
import types

from platforms.macos.host.runners.base_episode import BaseEpisodeRunner


def _exec_prelude_with_fake_pyautogui(monkeypatch, fake):
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    exec(BaseEpisodeRunner._build_python_action_prelude(None), {})
    return fake


def _fake_pyautogui(keyboard_mapping):
    fake = types.ModuleType("pyautogui")
    fake.platformModule = types.SimpleNamespace(keyboardMapping=dict(keyboard_mapping))
    fake.KEY_NAMES = list(keyboard_mapping)
    fake.typewrite = lambda *args, **kwargs: None
    return fake


def test_prelude_aliases_cmd_to_command(monkeypatch):
    fake = _exec_prelude_with_fake_pyautogui(monkeypatch, _fake_pyautogui({"command": 0x37, "a": 0x00}))

    assert fake.platformModule.keyboardMapping["cmd"] == 0x37
    assert "cmd" in fake.KEY_NAMES


def test_prelude_keeps_existing_cmd_mapping(monkeypatch):
    fake = _exec_prelude_with_fake_pyautogui(monkeypatch, _fake_pyautogui({"command": 0x37, "cmd": 0x36}))

    assert fake.platformModule.keyboardMapping["cmd"] == 0x36


def test_prelude_tolerates_backend_without_keyboard_mapping(monkeypatch):
    fake = types.ModuleType("pyautogui")
    fake.typewrite = lambda *args, **kwargs: None

    _exec_prelude_with_fake_pyautogui(monkeypatch, fake)

    assert not hasattr(fake, "platformModule")
