import json
from pathlib import Path

import pytest
import yaml

from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.linux import android_companion as composite
from platforms.linux.android_companion import CompanionSettings, scrcpy_script

ROOT = Path(__file__).resolve().parents[1]
TASKS = sorted((ROOT / "tasks/v1/cross_device").glob("linux_android_*.yaml"))


def _trajectory(tmp_path, codes):
    path = tmp_path / "trajectory.jsonl"
    path.write_text("\n".join(json.dumps({"step_index": i, "action_parse": {"type": "python_code", "code": code}})
                              for i, code in enumerate(codes, start=1)))
    return path


def test_forbidden_actions_flags_adb_and_scrcpy(tmp_path):
    path = _trajectory(tmp_path, [
        "pyautogui.click(1460, 600)",
        "import subprocess\nsubprocess.run(['adb', 'pull', '/sdcard/x.csv'])",
        "pyautogui.write('scrcpy --help')",
        "pyautogui.write('Load balancing, adbook')",
    ])
    hits = composite.forbidden_actions(path, composite.DEFAULT_FORBIDDEN)
    assert [hit["step"] for hit in hits] == [2, 3]


def test_forbidden_actions_reads_recorded_trajectories(tmp_path):
    # Episode trajectories store the action as the repr of the parsed action dict.
    def record(step, code):
        action = {"type": "python_code", "language": "python", "code": code, "timeout_seconds": 120}
        return json.dumps({"step_index": step, "action_parse": {"status": "SUCCESS", "action": repr(action), "error": "None"}})

    path = tmp_path / "trajectory.jsonl"
    path.write_text("\n".join([
        record(1, "pyautogui.click(995, 67)\npyautogui.typewrite('scrcpy', interval=0.05)"),
        record(2, "# bring the scrcpy window to the front\npyautogui.click(1460, 600)"),
        record(3, "pyautogui.click(10, 10)  # adb is not used"),
        record(4, "pyautogui.write('adb devices')"),
    ]))
    hits = composite.forbidden_actions(path, composite.DEFAULT_FORBIDDEN)
    assert [hit["step"] for hit in hits] == [1, 4]


class _Fixed(BaseEvaluator):
    status = EvalStatus.PASS

    def evaluate(self, context):
        return EvalResult(status=self.status, message=self.status.value)


class _Fail(_Fixed):
    status = EvalStatus.FAIL


@pytest.fixture
def phone_env(monkeypatch):
    monkeypatch.setenv("OS_OMNI_ANDROID_SERIAL", "emulator-5570")
    monkeypatch.setenv("OS_OMNI_ANDROID_FORWARD", "172.17.0.1:15571")
    monkeypatch.setattr(composite, "phone_controller", lambda settings: object())


def _evaluate(trajectory, android, linux):
    params = {"android": {"evaluator_id": android}, "linux": [{"evaluator_id": spec} for spec in linux]}
    return composite.LinuxAndroidCompositeEvaluator().evaluate({"params": params, "trajectory_path": trajectory})


def test_composite_needs_every_part(tmp_path, phone_env):
    clean = _trajectory(tmp_path, ["pyautogui.click(1, 1)"])
    assert _evaluate(clean, _Fixed, [_Fixed, _Fixed]).status == EvalStatus.PASS
    assert _evaluate(clean, _Fail, [_Fixed, _Fixed]).status == EvalStatus.FAIL
    assert _evaluate(clean, _Fixed, [_Fixed, _Fail]).status == EvalStatus.FAIL
    dirty = _trajectory(tmp_path, ["import os\nos.system('adb shell input text x')"])
    result = _evaluate(dirty, _Fixed, [_Fixed, _Fixed])
    assert result.status == EvalStatus.FAIL and "gui_only" in result.message


def test_scrcpy_script_targets_forwarded_adbd():
    settings = CompanionSettings("emulator-5570", "adb", 5037, "172.17.0.1", 15571, "osomni_cross_ready")
    assert settings.adbd_port == 5571
    script = scrcpy_script(settings, x=1240, y=60, height=990)
    assert "adb connect 172.17.0.1:15571" in script
    assert "--keyboard=uhid" in script and "SCRCPY_READY" in script
    # Alt+Left (the agents' "back") must not rotate the phone view.
    assert "--shortcut-mod=rsuper" in script


@pytest.mark.parametrize("path", TASKS, ids=[path.stem for path in TASKS])
def test_linux_android_tasks_are_single_screen(path):
    task = yaml.safe_load(path.read_text())
    assert task["platform"] == "linux"
    assert task["init"]["initializer_id"] == "initializers.linux.android_companion:LinuxAndroidCompanionInitializer"
    assert task["evaluation"]["evaluator_id"] == "evaluators.linux.android_companion:LinuxAndroidCompositeEvaluator"
    params = task["evaluation"]["params"]
    name = Path(params["android"][0]["params"]["path"]).name
    # Round trip: results computed on the desktop must also go back to the phone.
    assert len(params["android"]) > 1 or params["phone_copies"]
    assert "back on the phone" in task["instruction"]
    assert f"~/Desktop/{name}" in task["instruction"]
    assert "Windows" not in task["instruction"] and "Notepad" not in task["instruction"]
    # The agent brings the file over itself: the initializer must not pre-place it.
    setup = task["init"]["params"]["linux"]["steps"][0]["script"]
    assert f"rm -f /home/user/Desktop/{name}" in setup


def test_min_type_interval_prelude(monkeypatch):
    source = (ROOT / "platforms/linux/runners/base_episode.py").read_text()
    assert "OS_OMNI_MIN_TYPE_INTERVAL" in source and "pyautogui.write = pyautogui.typewrite" in source


class _Phone:
    def __init__(self, outputs):
        self.outputs = outputs

    def execute_adb(self, args):
        command = args[-1]
        return next(value for key, value in self.outputs.items() if key in command)


def _hex(text):
    return text.encode().hex().upper()


def test_tasks_items_need_exact_titles_dates_and_no_extras():
    from evaluators.android.companion_records import TasksAppItemsEvaluator
    rows = f"{_hex('Old task')}|0\n{_hex('Fix A - 1')}|1792152000000\n"
    params = {"tasks": [{"title": "Fix A - 1", "due": "2026-10-16"}], "baseline_count": 1}
    ok = TasksAppItemsEvaluator().evaluate({"controller": _Phone({"tasks": rows}), "params": params})
    assert ok.status == EvalStatus.PASS
    wrong_day = TasksAppItemsEvaluator().evaluate(
        {"controller": _Phone({"tasks": rows}), "params": {**params, "tasks": [{"title": "Fix A - 1", "due": "2026-10-17"}]}})
    assert wrong_day.status == EvalStatus.FAIL
    extra = TasksAppItemsEvaluator().evaluate(
        {"controller": _Phone({"tasks": rows + f"{_hex('Fix A - 1')}|1792152000000\n"}), "params": params})
    assert extra.status == EvalStatus.FAIL


def test_calendar_events_compare_utc_start_and_end():
    from evaluators.android.companion_records import CalendarEventsEvaluator
    rows = f"{_hex('Keynote (Room A)')}|1792054800|1792058400\n"
    params = {"events": [{"title": "Keynote (Room A)", "start": "2026-10-15 09:00", "end": "2026-10-15 10:00"}],
              "baseline_count": 0}
    assert CalendarEventsEvaluator().evaluate({"controller": _Phone({"events": rows}), "params": params}).status == EvalStatus.PASS
    params["events"][0]["end"] = "2026-10-15 09:30"
    assert CalendarEventsEvaluator().evaluate({"controller": _Phone({"events": rows}), "params": params}).status == EvalStatus.FAIL


class _Desktop:
    def __init__(self, sha):
        self.sha = sha

    def run_bash_script(self, script, timeout=30):
        return {"output": self.sha}


def test_phone_copy_must_match_desktop_file():
    sha = "a" * 64
    item = {"desktop_path": "/home/user/Documents/x.pdf", "phone_path": "/sdcard/Download/x.pdf"}
    assert composite._phone_copy(_Phone({"sha256sum": sha}), _Desktop(sha), item)["status"] == "PASS"
    assert composite._phone_copy(_Phone({"sha256sum": ""}), _Desktop(sha), item)["status"] == "FAIL"
    assert composite._phone_copy(_Phone({"sha256sum": sha}), _Desktop(""), item)["status"] == "FAIL"
