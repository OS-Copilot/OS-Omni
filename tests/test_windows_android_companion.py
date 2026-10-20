from pathlib import Path

import pytest
import yaml

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.linux import android_companion as linux_composite
from evaluators.windows.android_companion import WindowsAndroidCompositeEvaluator
from initializers.windows.android_companion import WindowsAndroidCompanionInitializer
from platforms.linux.android_companion import CompanionSettings
from platforms.windows.android_companion import file_sha256_powershell, scrcpy_powershell

ROOT = Path(__file__).resolve().parents[1]
TASKS = sorted((ROOT / "tasks/v1/cross_device").glob("windows_android_*.yaml"))
SETTINGS = CompanionSettings("emulator-5576", "adb", 5037, "172.17.0.1", 15577, "osomni_cross_ready")


class _Fixed(BaseEvaluator):
    status = EvalStatus.PASS

    def evaluate(self, context):
        return EvalResult(status=self.status, message=self.status.value)


class _Fail(_Fixed):
    status = EvalStatus.FAIL


class _Desktop:
    def __init__(self, sha=""):
        self.sha = sha
        self.scripts = []

    def run_powershell_script(self, script, timeout=30):
        self.scripts.append(script)
        return {"output": self.sha + "\r\n"}


def test_scrcpy_powershell_targets_forwarded_adbd_without_inheriting_pipes():
    script = scrcpy_powershell(SETTINGS, x=1420, y=40, height=940)
    assert "$target = '172.17.0.1:15577'" in script and "'connect', $target" in script
    assert "--keyboard=uhid" in script and "--shortcut-mod=rsuper" in script and "SCRCPY_READY" in script
    assert '--window-title "Android phone"' in script
    # Daemons must not inherit the runtime's pipes, and scrcpy's own window must stay visible.
    assert "wscript.exe" in script and "-RedirectStandardError" in script
    assert "scrcpy.exe' -ArgumentList" not in script


def test_windows_initializer_uses_powershell_and_windows_params():
    desktop = _Desktop()
    initializer = WindowsAndroidCompanionInitializer()
    assert initializer.DESKTOP == "windows"
    initializer.open_phone_window(desktop, SETTINGS, initializer.DEFAULT_WINDOW)
    assert "SCRCPY_READY" in desktop.scripts[0]


def test_windows_composite_reads_windows_params(tmp_path, monkeypatch):
    monkeypatch.setenv("OS_OMNI_ANDROID_SERIAL", "emulator-5576")
    monkeypatch.setenv("OS_OMNI_ANDROID_FORWARD", "172.17.0.1:15577")
    monkeypatch.setattr(linux_composite, "phone_controller", lambda settings: object())
    path = tmp_path / "trajectory.jsonl"
    path.write_text("")

    def evaluate(android, windows):
        params = {"android": {"evaluator_id": android}, "windows": [{"evaluator_id": spec} for spec in windows]}
        return WindowsAndroidCompositeEvaluator().evaluate({"params": params, "trajectory_path": path})

    assert evaluate(_Fixed, [_Fixed, _Fixed]).status == EvalStatus.PASS
    assert evaluate(_Fixed, [_Fixed, _Fail]).status == EvalStatus.FAIL
    assert evaluate(_Fail, [_Fixed]).status == EvalStatus.FAIL


def test_windows_phone_copy_hashes_the_desktop_file_with_powershell():
    sha = "b" * 64
    desktop = _Desktop(sha)
    assert WindowsAndroidCompositeEvaluator().desktop_sha256(desktop, r"C:\Users\User\Documents\x.csv") == sha
    assert "Get-FileHash" in desktop.scripts[0] and r"C:\Users\User\Documents\x.csv" in file_sha256_powershell(
        r"C:\Users\User\Documents\x.csv")


@pytest.mark.parametrize("path", TASKS, ids=[path.stem for path in TASKS])
def test_windows_android_tasks_are_single_screen_round_trips(path):
    task = yaml.safe_load(path.read_text())
    assert task["platform"] == "windows"
    assert task["init"]["initializer_id"] == "initializers.windows.android_companion:WindowsAndroidCompanionInitializer"
    assert task["evaluation"]["evaluator_id"] == "evaluators.windows.android_companion:WindowsAndroidCompositeEvaluator"
    params = task["evaluation"]["params"]
    name = Path(params["android"][0]["params"]["path"]).name
    assert len(params["android"]) > 1 or params["phone_copies"]
    assert "back on the phone" in task["instruction"]
    assert f"C:\\Users\\User\\Desktop\\{name}" in task["instruction"]
    assert "Linux" not in task["instruction"] and "/home/user" not in task["instruction"]
    # The agent brings the file over itself: the initializer must not pre-place it.
    setup = task["init"]["params"]["windows"]["steps"][0]["script"]
    assert f"'C:\\Users\\User\\Desktop\\{name}'" in setup.split("Remove-Item -LiteralPath", 1)[1].splitlines()[0]
    # The desktop checks run on Windows paths.
    for spec in params["windows"]:
        assert "/home/user" not in spec["params"]["command"]


def test_windows_step_prompt_states_the_screen_size():
    from types import SimpleNamespace

    from platforms.windows.agent.prompt_builder import WindowsPromptBuilder

    builder = WindowsPromptBuilder(observation_mode="screenshot_only", tool_calling=False)
    prompt = builder.build_step_prompt(observation=SimpleNamespace(ui_nodes=[], width=1920, height=1080))
    assert "The screen is 1920×1080 pixels" in prompt


def test_scancode_prelude_is_opt_in_and_compiles(monkeypatch):
    from platforms.linux.runners.base_episode import code_prelude

    monkeypatch.delenv("OS_OMNI_KEY_SCANCODES", raising=False)
    assert "MapVirtualKeyW" not in code_prelude()
    monkeypatch.setenv("OS_OMNI_KEY_SCANCODES", "1")
    prelude = code_prelude()
    # Real scan codes, so the scrcpy (SDL) phone window receives letters, digits and shortcuts.
    assert "MapVirtualKeyW" in prelude and "sys.platform == 'win32'" in prelude
    compile(prelude, "prelude", "exec")


def test_phone_window_can_be_reopened_and_open_documents_hashed():
    script = scrcpy_powershell(SETTINGS, x=1420, y=40, height=940)
    assert "CreateShortcut" in script and "android_phone.vbs" in script
    assert "'ReadWrite'" in file_sha256_powershell(r"C:\Users\User\Documents\x.docx")


def test_pointer_settle_moves_before_pressing(monkeypatch):
    import sys
    import types

    from platforms.linux.runners.base_episode import code_prelude

    monkeypatch.delenv("OS_OMNI_POINTER_SETTLE", raising=False)
    assert "_osomni_settled" not in code_prelude()
    monkeypatch.setenv("OS_OMNI_POINTER_SETTLE", "0.05")
    calls = []
    fake = types.SimpleNamespace(
        moveTo=lambda x, y: calls.append(("move", x, y)),
        click=lambda x=None, y=None, *a, **k: calls.append(("click", x, y, k.get("button"))),
        mouseDown=lambda x=None, y=None, *a, **k: calls.append(("down", x, y)),
        mouseUp=lambda x=None, y=None, *a, **k: calls.append(("up", x, y)),
        _normalizeXYArgs=lambda x, y: (x[0], x[1]) if isinstance(x, tuple) else (x, y),
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    sleeps = []
    monkeypatch.setitem(sys.modules, "time", types.SimpleNamespace(sleep=sleeps.append))
    exec(code_prelude(), {})
    fake.click(10, 20, button="right")
    fake.mouseDown((30, 40))
    fake.mouseUp()
    # The press itself happens at the current (settled) cursor position.
    assert calls == [("move", 10, 20), ("click", None, None, "right"), ("move", 30, 40), ("down", None, None), ("up", None, None)]
    assert sleeps == [0.05, 0.05, 0.05]


def test_phone_shortcut_restores_a_minimized_window():
    from platforms.windows.android_companion import RESTORE_WINDOW_PS1

    script = scrcpy_powershell(SETTINGS, x=1420, y=40, height=940)
    assert "restore_phone.ps1" in script and "open_phone.vbs" in script
    assert "$lnk.Arguments = '\"' + $open + '\"'" in script
    # Called twice: the hidden launcher's first ShowWindow takes the hidden start flag.
    assert RESTORE_WINDOW_PS1.count("ShowWindow($p.MainWindowHandle, 9)") == 2
    assert "MainWindowTitle -eq $title" in RESTORE_WINDOW_PS1


def test_semicolons_in_comments_do_not_split_statements():
    from platforms.windows.agent.planners.reflection_pyautogui_planner import _split_code_semicolons

    assert _split_code_semicolons("pyautogui.click(1625, 1134)  # too low; need actual") == [
        "pyautogui.click(1625, 1134)  # too low; need actual"]
    assert _split_code_semicolons("a = 1; b = '#;'  # c; d") == ["a = 1", "b = '#;'  # c; d"]
